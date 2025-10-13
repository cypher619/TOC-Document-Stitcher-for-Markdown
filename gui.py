# gui.py
from pathlib import Path
import re
import yaml

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QShortcut, QKeySequence
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QFileDialog, QTreeWidget, QTreeWidgetItem, QTextEdit, QLabel
)
from PyQt6.QtCore import QUrl

from core import TOCStitcherCore, TOCEntry

# -------------------- constants & helpers --------------------

SETTINGS_FILE = "stitcher_settings.yaml"
LEVEL_ROLE = Qt.ItemDataRole.UserRole + 1

def slugify(title: str) -> str:
    s = title.lower()
    s = re.sub(r"[^a-z0-9\s-]", "", s)
    return re.sub(r"\s+", "-", s).strip("-")


# ----------------------- YAML helpers -----------------------

def settings_from_toc(entries: list[TOCEntry]) -> dict:
    return {
        "version": 1,
        "selections": [
            {"slug": slugify(e.title), "title": e.title, "level": int(e.level), "include": True}
            for e in entries
        ],
        "metadata": {
            "title": "Compiled Document",
            "subtitle": "",
            "author": "",
            "date": "",
            "license": "",
            "geometry": "margin=1in",
            "fontsize": "12pt",
            "toc": True,
            "toc-depth": 3,
        },
        "output": {
            "filename": "The_FTC_Software_Rule_Compiled.md",
            "mode": "overwrite",
            "pdf_engine_preference": "auto",
        },
        "toc": {"place": "by_toc"},
    }

def load_settings(path: Path) -> dict | None:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or None
    except FileNotFoundError:
        return None

def save_settings(path: Path, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)

def reconcile_settings_with_toc(settings: dict, entries: list[TOCEntry]) -> dict:
    prev = {s.get("slug"): s for s in settings.get("selections", [])}
    new_list = []
    for e in entries:
        slug = slugify(e.title)
        if slug in prev:
            item = dict(prev[slug])
            item["title"] = e.title
            item["level"] = int(e.level)
        else:
            item = {"slug": slug, "title": e.title, "level": int(e.level), "include": True}
        new_list.append(item)
    out = {
        "version": settings.get("version", 1),
        "selections": new_list,
        "metadata": settings.get("metadata", settings_from_toc(entries)["metadata"]),
        "output": settings.get("output", settings_from_toc(entries)["output"]),
        "toc": settings.get("toc", {"place": "by_toc"}),
    }
    return out


# ------------------------- worker ---------------------------

class BuilderThread(QThread):
    message = pyqtSignal(str)
    finished = pyqtSignal(bool)

    def __init__(self, base_dir: Path, selected_entries: list[TOCEntry], export_pdf: bool = True):
        super().__init__()
        self.base_dir = base_dir
        self.selected_entries = selected_entries
        self.export_pdf_flag = export_pdf

    def run(self):
        try:
            core = TOCStitcherCore(self.base_dir)
            self.message.emit("🧩 Building Markdown…")
            md_path, chars = core.build_markdown(self.selected_entries, log_fn=self.message.emit)
            self.message.emit(f"✅ Markdown compiled: {md_path}")
            self.message.emit(f"   • Characters written: {chars}")
            if self.export_pdf_flag:
                core.export_pdf(log_fn=self.message.emit)
            self.finished.emit(True)
        except Exception as e:
            self.message.emit(f"❌ Build failed: {e}")
            self.finished.emit(False)


# --------------------------- UI -----------------------------

class StitcherGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("TOC Document Stitcher for MD")
        self.base_dir: Path | None = None
        self.settings: dict = {}

        # central layout
        central = QWidget(self)
        layout = QVBoxLayout(central)

        # directory picker row
        row = QHBoxLayout()
        self.btn_pick = QPushButton("Pick Working Directory")
        self.lbl_dir = QLabel("(none)")
        self.btn_open_folder = QPushButton("Open Output Folder")  # NEW
        self.btn_open_folder.setEnabled(False)
        row.addWidget(self.btn_pick)
        row.addWidget(self.lbl_dir, 1)
        row.addWidget(self.btn_open_folder)  # NEW
        layout.addLayout(row)

        # TOC tree
        self.toc_tree = QTreeWidget()
        self.toc_tree.setHeaderLabels(["Table of Contents (check to include)"])
        layout.addWidget(self.toc_tree, 1)

        # buttons row
        btn_row = QHBoxLayout()
        self.btn_build = QPushButton("Build Selected Sections")
        self.btn_save = QPushButton("Save Project Settings")
        self.btn_build.setEnabled(False)
        self.btn_save.setEnabled(False)
        btn_row.addWidget(self.btn_build)
        btn_row.addWidget(self.btn_save)
        layout.addLayout(btn_row)

        # output box
        self.output = QTextEdit()
        self.output.setReadOnly(True)
        layout.addWidget(self.output, 1)

        self.setCentralWidget(central)

        # signals
        self.btn_pick.clicked.connect(self.pick_directory)
        self.btn_build.clicked.connect(self.start_build)
        self.btn_save.clicked.connect(self.save_project_settings)
        self.btn_open_folder.clicked.connect(self.open_output_folder)

        # hotkey: Ctrl+S to save settings
        QShortcut(QKeySequence("Ctrl+S"), self, activated=self.save_project_settings)

    # ---------- tree helpers ----------

    def populate_toc(self, entries: list[TOCEntry]) -> None:
        self.toc_tree.clear()
        parent_at_level: dict[int, QTreeWidgetItem] = {}
        for e in entries:
            item = QTreeWidgetItem([e.title])
            item.setData(0, LEVEL_ROLE, e.level)
            # default checked for H2; H3 default unchecked (settings will override)
            item.setCheckState(0, Qt.CheckState.Checked if e.level == 2 else Qt.CheckState.Unchecked)

            # place by hierarchy
            parent = None
            for lvl in range(e.level - 1, 1, -1):
                if lvl in parent_at_level:
                    parent = parent_at_level[lvl]
                    break
            if parent is None or e.level <= 2:
                self.toc_tree.addTopLevelItem(item)
            else:
                parent.addChild(item)
            parent_at_level[e.level] = item
        self.toc_tree.expandAll()

    def _iter_items_in_order(self, node: QTreeWidgetItem):
        for i in range(node.childCount()):
            child = node.child(i)
            yield child
            yield from self._iter_items_in_order(child)

    def collect_checked_entries(self) -> list[TOCEntry]:
        out: list[TOCEntry] = []
        root = self.toc_tree.invisibleRootItem()
        # top-level items first (pre-order)
        for i in range(root.childCount()):
            node = root.child(i)
            if node.checkState(0) == Qt.CheckState.Checked:
                level = int(node.data(0, LEVEL_ROLE) or 2)
                title = node.text(0)
                out.append(TOCEntry(level=level, title=title))
            for child in self._iter_items_in_order(node):
                if child.checkState(0) == Qt.CheckState.Checked:
                    level = int(child.data(0, LEVEL_ROLE) or 3)
                    title = child.text(0)
                    out.append(TOCEntry(level=level, title=title))
        return out

    # ---------- settings ----------

    def apply_selections_to_tree(self, settings: dict) -> None:
        include_by_slug = {s["slug"]: bool(s.get("include", True)) for s in settings.get("selections", [])}
        root = self.toc_tree.invisibleRootItem()
        def walk(node: QTreeWidgetItem):
            for i in range(node.childCount()):
                child = node.child(i)
                title = child.text(0)
                slug = slugify(title)
                state = Qt.CheckState.Checked if include_by_slug.get(slug, True) else Qt.CheckState.Unchecked
                child.setCheckState(0, state)
                walk(child)
        walk(root)

    def current_selection_slugs(self) -> list[dict]:
        out = []
        root = self.toc_tree.invisibleRootItem()
        def walk(node: QTreeWidgetItem):
            for i in range(node.childCount()):
                child = node.child(i)
                title = child.text(0)
                slug = slugify(title)
                include = (child.checkState(0) == Qt.CheckState.Checked)
                level = int(child.data(0, LEVEL_ROLE) or 2)
                out.append({"slug": slug, "title": title, "level": level, "include": include})
                walk(child)
        walk(root)
        return out

    # ---------- actions ----------

    def pick_directory(self):
        dir_path = QFileDialog.getExistingDirectory(self, "Select Working Directory")
        if not dir_path:
            return
        self.base_dir = Path(dir_path)
        self.lbl_dir.setText(str(self.base_dir))
        self.output.append(f"📁 Selected: {self.base_dir}")

        try:
            core = TOCStitcherCore(self.base_dir)
            entries = core.parse_toc()
            self.populate_toc(entries)

            # Build or reconcile settings from TOC
            cfg_path = self.base_dir / SETTINGS_FILE
            existing = load_settings(cfg_path)
            if existing is None:
                settings = settings_from_toc(entries)
                save_settings(cfg_path, settings)
                self.output.append(f"🆕 Created {cfg_path.name} from TOC.")
            else:
                settings = reconcile_settings_with_toc(existing, entries)
                if settings != existing:
                    save_settings(cfg_path, settings)
                    self.output.append(f"🔁 Updated {cfg_path.name} to match current TOC.")

            self.apply_selections_to_tree(settings)
            self.settings = settings

            self.btn_build.setEnabled(True)
            self.btn_save.setEnabled(True)
            self.btn_open_folder.setEnabled(True)
        except Exception as e:
            self.output.append(f"❌ Failed to load TOC/settings: {e}")

    def start_build(self):
        if not self.base_dir:
            self.output.append("⚠️ Pick a working directory first.")
            return
        selected_entries = self.collect_checked_entries()
        if not selected_entries:
            self.output.append("⚠️ No sections selected.")
            return
        self.output.append("🚀 Starting build…")
        self.thread = BuilderThread(self.base_dir, selected_entries, export_pdf=True)
        self.thread.message.connect(self.output.append)
        self.thread.finished.connect(self.on_finished)
        self.thread.start()

    def save_project_settings(self):
        if not self.base_dir:
            self.output.append("⚠️ Pick a working directory first.")
            return
        cfg_path = self.base_dir / SETTINGS_FILE
        existing = load_settings(cfg_path) or settings_from_toc([])
        existing["selections"] = self.current_selection_slugs()
        # keep existing metadata/output blocks if present
        existing.setdefault("metadata", settings_from_toc([])["metadata"])
        existing.setdefault("output", settings_from_toc([])["output"])
        existing.setdefault("toc", {"place": "by_toc"})
        save_settings(cfg_path, existing)
        self.output.append(f"💾 Saved project settings → {cfg_path}")

    def on_finished(self, ok: bool):
        if ok and self.base_dir:
            self.save_project_settings()

    def open_output_folder(self):
        if self.base_dir and self.base_dir.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.base_dir)))
            self.output.append(f"📂 Opened: {self.base_dir}")


if __name__ == "__main__":
    import sys as _sys
    app = QApplication(_sys.argv)
    w = StitcherGUI()
    w.resize(1000, 700)
    w.show()
    _sys.exit(app.exec())
