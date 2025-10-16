# gui.py - Updated with metadata editor
from pathlib import Path
import re
import yaml

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QShortcut, QKeySequence
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QFileDialog, QTreeWidget, QTreeWidgetItem, QTextEdit, QLabel,
    QDialog, QFormLayout, QLineEdit, QCheckBox, QTabWidget, QMessageBox
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
        },
        "output": {
            "filename": "compiled_document.md",
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


# ----------------------- Metadata Editor Dialog -----------------------

class MetadataEditorDialog(QDialog):
    """Dialog for editing YAML metadata settings"""
    
    def __init__(self, base_dir: Path, parent=None):
        super().__init__(parent)
        self.base_dir = Path(base_dir)
        self.settings_file = self.base_dir / SETTINGS_FILE
        
        self.setWindowTitle("Edit Metadata Settings")
        self.setMinimumWidth(600)
        self.setMinimumHeight(500)
        
        self.init_ui()
        self.load_settings()
    
    def init_ui(self):
        layout = QVBoxLayout(self)
        
        # Create tab widget
        self.tabs = QTabWidget()
        
        # Document metadata tab
        doc_tab = QWidget()
        doc_layout = QFormLayout(doc_tab)
        
        self.title_edit = QLineEdit()
        self.subtitle_edit = QLineEdit()
        self.author_edit = QLineEdit()
        self.date_edit = QLineEdit()
        self.license_edit = QLineEdit()
        
        doc_layout.addRow("Title:", self.title_edit)
        doc_layout.addRow("Subtitle:", self.subtitle_edit)
        doc_layout.addRow("Author:", self.author_edit)
        doc_layout.addRow("Date:", self.date_edit)
        doc_layout.addRow("License:", self.license_edit)
        
        self.tabs.addTab(doc_tab, "Document Info")
        
        # PDF settings tab
        pdf_tab = QWidget()
        pdf_layout = QFormLayout(pdf_tab)
        
        self.geometry_edit = QLineEdit()
        self.geometry_edit.setPlaceholderText("e.g., margin=1in")
        
        self.fontsize_edit = QLineEdit()
        self.fontsize_edit.setPlaceholderText("e.g., 12pt")
        
        self.toc_checkbox = QCheckBox("Generate Table of Contents (Pandoc auto-TOC)")
        self.toc_checkbox.setToolTip("Enable this if you want Pandoc to auto-generate a TOC")
        
        self.toc_depth_edit = QLineEdit()
        self.toc_depth_edit.setPlaceholderText("e.g., 3")
        
        pdf_layout.addRow("Page Geometry:", self.geometry_edit)
        pdf_layout.addRow("Font Size:", self.fontsize_edit)
        pdf_layout.addRow("", self.toc_checkbox)
        pdf_layout.addRow("TOC Depth:", self.toc_depth_edit)
        
        # Add warning label
        warning_label = QLabel("⚠️ Disable auto-TOC if you already have a manual TOC in your document")
        warning_label.setStyleSheet("QLabel { color: #d97706; font-style: italic; }")
        warning_label.setWordWrap(True)
        pdf_layout.addRow("", warning_label)
        
        self.tabs.addTab(pdf_tab, "PDF Settings")
        
        # Output settings tab
        output_tab = QWidget()
        output_layout = QFormLayout(output_tab)
        
        self.output_filename_edit = QLineEdit()
        self.output_filename_edit.setPlaceholderText("e.g., my_document.md")
        
        self.pdf_engine_edit = QLineEdit()
        self.pdf_engine_edit.setPlaceholderText("auto, xelatex, or wkhtmltopdf")
        
        output_layout.addRow("Output Filename:", self.output_filename_edit)
        output_layout.addRow("PDF Engine:", self.pdf_engine_edit)
        
        self.tabs.addTab(output_tab, "Output")
        
        # Raw YAML editor tab
        yaml_tab = QWidget()
        yaml_layout = QVBoxLayout(yaml_tab)
        
        yaml_label = QLabel("Advanced: Edit raw YAML (use with caution)")
        yaml_label.setStyleSheet("QLabel { font-weight: bold; }")
        yaml_layout.addWidget(yaml_label)
        
        self.yaml_editor = QTextEdit()
        self.yaml_editor.setPlaceholderText("metadata:\n  title: \"My Document\"\n  author: \"Author Name\"")
        yaml_layout.addWidget(self.yaml_editor)
        
        self.tabs.addTab(yaml_tab, "Raw YAML")
        
        layout.addWidget(self.tabs)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        self.save_button = QPushButton("Save Settings")
        self.save_button.clicked.connect(self.save_settings)
        
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        
        self.reset_button = QPushButton("Reset to Defaults")
        self.reset_button.clicked.connect(self.reset_to_defaults)
        
        button_layout.addWidget(self.reset_button)
        button_layout.addStretch()
        button_layout.addWidget(self.cancel_button)
        button_layout.addWidget(self.save_button)
        
        layout.addLayout(button_layout)
        
        # Connect tab changes to sync YAML
        self.tabs.currentChanged.connect(self.on_tab_changed)
    
    def load_settings(self):
        """Load existing settings from YAML file"""
        settings = load_settings(self.settings_file)
        if not settings:
            settings = settings_from_toc([])
        
        self.settings = settings
        
        # Populate form fields
        metadata = settings.get("metadata", {})
        self.title_edit.setText(metadata.get("title", ""))
        self.subtitle_edit.setText(metadata.get("subtitle", ""))
        self.author_edit.setText(metadata.get("author", ""))
        self.date_edit.setText(metadata.get("date", ""))
        self.license_edit.setText(metadata.get("license", ""))
        self.geometry_edit.setText(metadata.get("geometry", "margin=1in"))
        self.fontsize_edit.setText(metadata.get("fontsize", "12pt"))
        self.toc_checkbox.setChecked(metadata.get("toc", False))
        self.toc_depth_edit.setText(str(metadata.get("toc-depth", 3)))
        
        output = settings.get("output", {})
        self.output_filename_edit.setText(output.get("filename", "compiled_document.md"))
        self.pdf_engine_edit.setText(output.get("pdf_engine_preference", "auto"))
        
        # Populate YAML editor
        self.yaml_editor.setPlainText(yaml.dump(settings, default_flow_style=False, sort_keys=False))
    
    def on_tab_changed(self, index):
        """Sync form fields to YAML editor when switching tabs"""
        current_tab_name = self.tabs.tabText(index)
        
        # Always update internal settings from current form state first
        self.update_settings_from_form()
        
        if current_tab_name == "Raw YAML":
            # Switching TO YAML tab - update YAML editor with current form values
            self.yaml_editor.setPlainText(yaml.dump(self.settings, default_flow_style=False, sort_keys=False))
        else:
            # Switching FROM YAML tab - try to parse and update form fields
            try:
                yaml_text = self.yaml_editor.toPlainText()
                if yaml_text.strip():
                    parsed = yaml.safe_load(yaml_text)
                    if parsed:
                        self.settings = parsed
                        # Update form fields from parsed YAML
                        metadata = self.settings.get("metadata", {})
                        self.title_edit.setText(metadata.get("title", ""))
                        self.subtitle_edit.setText(metadata.get("subtitle", ""))
                        self.author_edit.setText(metadata.get("author", ""))
                        self.date_edit.setText(metadata.get("date", ""))
                        self.license_edit.setText(metadata.get("license", ""))
                        self.geometry_edit.setText(metadata.get("geometry", "margin=1in"))
                        self.fontsize_edit.setText(metadata.get("fontsize", "12pt"))
                        self.toc_checkbox.setChecked(metadata.get("toc", False))
                        self.toc_depth_edit.setText(str(metadata.get("toc-depth", 3)))
                        
                        output = self.settings.get("output", {})
                        self.output_filename_edit.setText(output.get("filename", "compiled_document.md"))
                        self.pdf_engine_edit.setText(output.get("pdf_engine_preference", "auto"))
            except yaml.YAMLError:
                pass  # Keep current form values if YAML is invalid
    
    def update_settings_from_form(self):
        """Update settings dictionary from form fields"""
        if "metadata" not in self.settings:
            self.settings["metadata"] = {}
        if "output" not in self.settings:
            self.settings["output"] = {}
        
        metadata = self.settings["metadata"]
        metadata["title"] = self.title_edit.text()
        metadata["subtitle"] = self.subtitle_edit.text()
        metadata["author"] = self.author_edit.text()
        metadata["date"] = self.date_edit.text()
        metadata["license"] = self.license_edit.text()
        metadata["geometry"] = self.geometry_edit.text()
        metadata["fontsize"] = self.fontsize_edit.text()
        
        # Only include toc settings if checkbox is checked
        if self.toc_checkbox.isChecked():
            metadata["toc"] = True
            try:
                metadata["toc-depth"] = int(self.toc_depth_edit.text())
            except ValueError:
                metadata["toc-depth"] = 3
        else:
            # Remove toc settings if unchecked
            metadata.pop("toc", None)
            metadata.pop("toc-depth", None)
        
        output = self.settings["output"]
        output["filename"] = self.output_filename_edit.text()
        output["pdf_engine_preference"] = self.pdf_engine_edit.text()
    
    def save_settings(self):
        """Save settings to YAML file"""
        try:
            # If on YAML tab, try to parse it first
            if self.tabs.tabText(self.tabs.currentIndex()) == "Raw YAML":
                yaml_text = self.yaml_editor.toPlainText()
                try:
                    self.settings = yaml.safe_load(yaml_text) or {}
                except yaml.YAMLError as e:
                    QMessageBox.warning(self, "YAML Error", f"Invalid YAML syntax:\n{e}")
                    return
            else:
                # Update from form fields
                self.update_settings_from_form()
            
            # Write to file
            save_settings(self.settings_file, self.settings)
            
            QMessageBox.information(self, "Success", f"Settings saved to:\n{self.settings_file}")
            self.accept()
            
        except Exception as e:
            QMessageBox.critical(self, "Save Error", f"Error saving settings:\n{e}")
    
    def reset_to_defaults(self):
        """Reset all fields to default values"""
        reply = QMessageBox.question(
            self,
            "Reset to Defaults",
            "Are you sure you want to reset all settings to defaults?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            self.title_edit.setText("Compiled Document")
            self.subtitle_edit.clear()
            self.author_edit.clear()
            self.date_edit.clear()
            self.license_edit.clear()
            self.geometry_edit.setText("margin=1in")
            self.fontsize_edit.setText("12pt")
            self.toc_checkbox.setChecked(False)
            self.toc_depth_edit.setText("3")
            self.output_filename_edit.setText("compiled_document.md")
            self.pdf_engine_edit.setText("auto")


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
        self.btn_open_folder = QPushButton("Open Output Folder")
        self.btn_open_folder.setEnabled(False)
        row.addWidget(self.btn_pick)
        row.addWidget(self.lbl_dir, 1)
        row.addWidget(self.btn_open_folder)
        layout.addLayout(row)

        # Metadata settings button row
        meta_row = QHBoxLayout()
        self.btn_metadata = QPushButton("⚙️ Metadata Settings")
        self.btn_metadata.setEnabled(False)
        meta_row.addStretch()
        meta_row.addWidget(self.btn_metadata)
        layout.addLayout(meta_row)

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
        self.btn_metadata.clicked.connect(self.open_metadata_editor)

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
                    self.output.append(f"🔄 Updated {cfg_path.name} to match current TOC.")

            self.apply_selections_to_tree(settings)
            self.settings = settings

            self.btn_build.setEnabled(True)
            self.btn_save.setEnabled(True)
            self.btn_open_folder.setEnabled(True)
            self.btn_metadata.setEnabled(True)
        except Exception as e:
            self.output.append(f"❌ Failed to load TOC/settings: {e}")

    def open_metadata_editor(self):
        """Open metadata settings dialog"""
        if not self.base_dir:
            return
        
        dialog = MetadataEditorDialog(self.base_dir, self)
        if dialog.exec():
            self.output.append("✅ Metadata settings saved")
            # Reload settings to pick up changes
            cfg_path = self.base_dir / SETTINGS_FILE
            self.settings = load_settings(cfg_path) or settings_from_toc([])

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