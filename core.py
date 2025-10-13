# core.py
import re
import sys
import shutil
import subprocess
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Iterable

import yaml


# ============================================================
# ---------------------  DATA STRUCTURES  --------------------
# ============================================================

@dataclass
class TOCEntry:
    level: int   # 2 for H2, 3 for H3, ...
    title: str   # exact text from the TOC


@dataclass
class TOCNode:
    level: int
    title: str
    children: List["TOCNode"] = field(default_factory=list)


# ============================================================
# ----------------------  MAIN CLASS  ------------------------
# ============================================================

class TOCStitcherCore:
    """
    Deterministic, TOC-driven stitcher:
      - Read TOC -> build tree -> process tree (pre-order).
      - 'Table of Contents' node is replaced with linked original Table_of_Contents.md.
      - Robust matching + heading alignment to node level.
      - Page breaks between top-level H2 siblings only.
      - Per-project settings in stitcher_settings.yaml (selections, metadata, output).
      - Live logging to GUI via log_fn callback.
    """

    HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)\s*$", re.MULTILINE)
    DATE_PREFIX = re.compile(r"^(?P<date>\d{8})(?:-(?P<rev>\d+))?_")

    def __init__(self, base_dir: Path, output_filename: Optional[str] = None):
        self.base_dir = Path(base_dir)
        self.toc_file = self.base_dir / "Table_of_Contents.md"

        # Load project settings if present
        self.project_settings: Dict = {}
        cfg_path = self.base_dir / "stitcher_settings.yaml"
        if cfg_path.exists():
            try:
                with open(cfg_path, "r", encoding="utf-8") as f:
                    self.project_settings = yaml.safe_load(f) or {}
            except Exception:
                self.project_settings = {}

        # Output defaults (can be overridden by settings or arg)
        default_name = "my_doc.md"
        name_from_cfg = (self.project_settings.get("output") or {}).get("filename")
        self.output_md = self.base_dir / (
            output_filename or name_from_cfg or default_name
        )
        self.output_pdf = self.output_md.with_suffix(".pdf")
        out_cfg = self.project_settings.get("output") or {}
        self._output_mode = out_cfg.get("mode", "overwrite")               # overwrite|timestamped|append
        self._pdf_pref = out_cfg.get("pdf_engine_preference", "auto")      # auto|xelatex|wkhtmltopdf

        self._all_md_files: List[Path] = []
        self._latest_norm_index: Dict[str, Path] = {}

    # ============================================================
    # ------------------------  TOC I/O  -------------------------
    # ============================================================

    def parse_toc(self) -> List[TOCEntry]:
        """
        Return TOC entries in exact document order.
        Headings (#, ##, ###, ...) retain their level.
        Bulleted list items ('- ') are treated as H3 by default.
        """
        lines = self.toc_file.read_text(encoding="utf-8").splitlines()
        out: List[TOCEntry] = []
        for raw in lines:
            line = raw.strip()
            if not line or line.startswith("---"):
                continue
            if line.startswith("#"):
                level = len(line.split()[0])
                title = re.sub(r"^#+\s*", "", line).strip()
                if title:
                    out.append(TOCEntry(level=level, title=title))
            elif line.lstrip().startswith("- "):
                title = re.sub(r"^-+\s*", "", line.strip()).strip()
                if title:
                    out.append(TOCEntry(level=3, title=title))
        return out

    @staticmethod
    def build_toc_tree(entries: List[TOCEntry]) -> List[TOCNode]:
        """Convert flat ordered entries into a proper tree."""
        roots: List[TOCNode] = []
        stack: List[TOCNode] = []
        for e in entries:
            node = TOCNode(level=e.level, title=e.title)
            while stack and stack[-1].level >= node.level:
                stack.pop()
            if stack:
                stack[-1].children.append(node)
            else:
                roots.append(node)
            stack.append(node)
        return roots

    # ============================================================
    # ----------------------  FILE INDEX  ------------------------
    # ============================================================

    @staticmethod
    def _strip_date_prefix(name: str) -> Tuple[str, Optional[str], Optional[int]]:
        m = TOCStitcherCore.DATE_PREFIX.match(name)
        if not m:
            return name, None, None
        return name[m.end():], m.group("date"), int(m.group("rev") or 0)

    @staticmethod
    def _normalize_text(s: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", s.lower())

    @staticmethod
    def _tokenize(s: str) -> List[str]:
        return re.findall(r"[a-z0-9]+", s.lower())

    @staticmethod
    def _jaccard(a: Iterable[str], b: Iterable[str]) -> float:
        sa, sb = set(a), set(b)
        if not sa or not sb:
            return 0.0
        return len(sa & sb) / len(sa | sb)

    def _index_files(self) -> None:
        """Build indices of latest *.md by normalized stem; keep all files list."""
        all_md = [p for p in self.base_dir.glob("*.md") if p.name != self.output_md.name]
        grouped: Dict[str, List[Tuple[Path, str, int]]] = {}
        for p in all_md:
            stem_no_date, date, rev = self._strip_date_prefix(p.stem)
            grouped.setdefault(stem_no_date, []).append((p, date or "", rev or 0))
        latest_norm: Dict[str, Path] = {}
        for stem, cands in grouped.items():
            best = max(cands, key=lambda t: (t[1], t[2]))
            norm_key = self._normalize_text(stem)
            latest_norm[norm_key] = best[0]
        self._all_md_files = all_md
        self._latest_norm_index = latest_norm

    def _match_title_to_file(self, title: str) -> Optional[Path]:
        """
        Match a TOC title to a file:
          1) exact normalized key
          2) substring/contains on normalized keys
          3) token Jaccard across all files (threshold 0.40)
        """
        if not self._latest_norm_index:
            self._index_files()

        target_norm = self._normalize_text(title)

        # exact
        if target_norm in self._latest_norm_index:
            return self._latest_norm_index[target_norm]

        # contains/contained by
        for k, p in self._latest_norm_index.items():
            if target_norm in k or k in target_norm:
                return p

        # fuzzy tokens
        target_tokens = self._tokenize(title)
        best_path, best_score = None, 0.0
        for p in self._all_md_files:
            stem_no_date = self._strip_date_prefix(p.stem)[0]
            cand_tokens = self._tokenize(stem_no_date.replace("_", " "))
            score = self._jaccard(target_tokens, cand_tokens)
            if score > best_score:
                best_score, best_path = score, p
        if best_path and best_score >= 0.40:
            return best_path
        return None

    # ============================================================
    # -------------------  HEADING UTILITIES  --------------------
    # ============================================================

    def _analyze_headings(self, text: str) -> Dict:
        levels: Dict[int, int] = {}
        first = None
        last_level = None
        jumps: List[Tuple[int, int, int]] = []
        for i, line in enumerate(text.splitlines(), start=1):
            m = self.HEADING_RE.match(line)
            if not m:
                continue
            lvl = len(m.group(1))
            ttl = m.group(2).strip()
            levels[lvl] = levels.get(lvl, 0) + 1
            if first is None:
                first = (lvl, ttl, i)
            if last_level is not None and lvl > last_level + 1:
                jumps.append((last_level, lvl, i))
            last_level = lvl
        min_level = min(levels) if levels else None
        return {
            "levels": levels,
            "first": first,
            "min_level": min_level,
            "jumps": jumps,
            "multiple_h1": levels.get(1, 0) > 1 if levels else False,
        }

    def _shift_headings(self, text: str, shift: int) -> str:
        def repl(m):
            hashes, title = m.group(1), m.group(2)
            lvl = len(hashes)
            new_lvl = max(1, min(6, lvl + shift))
            return f"{'#' * new_lvl} {title}"
        return self.HEADING_RE.sub(repl, text)

    # ============================================================
    # ------------------  SLUG + LINKIFY TOC  --------------------
    # ============================================================

    def _slug(self, title: str) -> str:
        s = title.lower()
        s = re.sub(r"[^a-z0-9\s-]", "", s)
        return re.sub(r"\s+", "-", s).strip("-")

    def _linkify_original_toc(self, toc_md: str, entries: List[TOCEntry]) -> str:
        """
        Linkify the original TOC content in-place:
          - Headings: wrap the title text in [text](#slug)
          - List items: wrap the whole list text in [text](#slug)
        No reordering or wording changes.
        """
        def slug_for_best_match(text: str) -> Optional[str]:
            norm = lambda s: re.sub(r"[^a-z0-9]+", "", s.lower())
            tnorm = norm(text)
            # exact normalized match
            for e in entries:
                if norm(e.title) == tnorm:
                    return self._slug(e.title)
            # contains/contained-by
            for e in entries:
                en = norm(e.title)
                if en in tnorm or tnorm in en:
                    return self._slug(e.title)
            # token overlap
            def toks(s): return set(re.findall(r"[a-z0-9]+", s.lower()))
            tt = toks(text)
            best, best_score = None, 0.0
            for e in entries:
                score = len(tt & toks(e.title)) / max(1, len(tt | toks(e.title)))
                if score > best_score:
                    best, best_score = self._slug(e.title), score
            return best if best_score >= 0.45 else None

        out = []
        for raw in toc_md.splitlines():
            line = raw.rstrip("\n")

            # Already linked? leave it
            if "](" in line:
                out.append(line)
                continue

            # Headings
            m = re.match(r"^(\s*)(#{1,6})[ \t]+(.+?)\s*$", line)
            if m:
                indent, hashes, title_text = m.groups()
                slug = slug_for_best_match(title_text)
                out.append(f"{indent}{hashes} [{title_text}](#{slug})" if slug else line)
                continue

            # List items
            m = re.match(r"^(\s*)-\s+(.+?)\s*$", line)
            if m:
                indent, li_text = m.groups()
                slug = slug_for_best_match(li_text)
                out.append(f"{indent}- [{li_text}](#{slug})" if slug else line)
                continue

            out.append(line)

        return "\n".join(out).rstrip()

    # ============================================================
    # ------------------  METADATA (YAML)  -----------------------
    # ============================================================

    def _metadata_header(self) -> str:
        # Defaults, overridden by per-project metadata (if provided)
        meta = {
            "title": "Compiled Document",
            "subtitle": "",
            "author": "",
            "date": "",
            "license": "",
            "geometry": "margin=1in",
            "fontsize": "12pt",
            "toc": True,
            "toc-depth": 3,
        }
        meta.update(self.project_settings.get("metadata", {}) or {})

        lines = ["---"]
        def emit(k, v):
            if isinstance(v, bool):
                v = "true" if v else "false"
            lines.append(f"{k}: {v}")
        for k in ["title", "subtitle", "author", "date", "license",
                  "geometry", "fontsize", "toc", "toc-depth"]:
            if k in meta and meta[k] not in (None, ""):
                emit(k, meta[k])
        lines.append("---")
        return "\n".join(lines) + "\n"

    # ============================================================
    # -------------------  BUILD (TREE-DRIVEN)  ------------------
    # ============================================================

    def build_markdown(self, selected_entries: List[TOCEntry], log_fn=None) -> Tuple[Path, int]:
        """
        1) Build TOC tree from ordered selection.
        2) Pre-order traversal to assemble content.
        3) If node is 'Table of Contents', linkify original TOC and insert here.
        """
        def _log(msg: str):
            if log_fn:
                try:
                    log_fn(msg)
                except Exception:
                    pass
            else:
                print(msg)

        self._index_files()
        roots = self.build_toc_tree(selected_entries)

        sections: List[str] = []

        def process_node(node: TOCNode, is_first_top_level: bool) -> None:
            title_lower = node.title.strip().lower()

            # Page break between top-level H2 siblings (not before the first)
            if node.level == 2 and not is_first_top_level:
                sections.append('<div style="page-break-after: always;"></div>\n')

            # Special: TOC node -> linkify original TOC in place
            if title_lower == "table of contents":
                toc_raw = self.toc_file.read_text(encoding="utf-8")
                linked = self._linkify_original_toc(toc_raw, selected_entries)
                sections.append(f'<a id="{self._slug(node.title)}"></a>\n')
                sections.append(linked)
                _log("📖 Inserted original TOC (linkified).")
            else:
                # Normal doc node
                path = self._match_title_to_file(node.title)
                if not path:
                    sections.append(f"<!-- Missing: {node.title} -->")
                    _log(f"⚠️ Missing: {node.title}")
                else:
                    raw = path.read_text(encoding="utf-8").strip()
                    meta = self._analyze_headings(raw)
                    if meta["min_level"] is None:
                        content = f"{'#' * node.level} {node.title}\n\n{raw}"
                        _log(f"ℹ️ {path.name}: no headings; inserted H{node.level}.")
                    else:
                        shift = node.level - meta["min_level"]
                        content = self._shift_headings(raw, shift) if shift != 0 else raw
                        if shift > 0:
                            _log(f"🔧 {path.name}: promoted by {abs(shift)} (→ H{node.level}).")
                        elif shift < 0:
                            _log(f"🔧 {path.name}: demoted by {abs(shift)} (→ H{node.level}).")
                    sections.append(f'<a id="{self._slug(node.title)}"></a>\n')
                    sections.append(content)

            # Process children (no page breaks between parent and children)
            for child in node.children:
                process_node(child, is_first_top_level=False)

        # Walk tree in document order
        for i, root in enumerate(roots):
            process_node(root, is_first_top_level=(i == 0))

        compiled = self._metadata_header() + "\n" + "\n".join(sections)

        # Write (overwrite by default; modes can be extended if desired)
        if self._output_mode == "append":
            with self.output_md.open("a", encoding="utf-8") as f:
                f.write(compiled)
            final_path = self.output_md
            chars = final_path.stat().st_size
        else:
            chars = self.output_md.write_text(compiled, encoding="utf-8")
            final_path = self.output_md

        if not final_path.exists() or final_path.stat().st_size == 0:
            raise IOError(f"Markdown write failed or empty: {final_path}")

        return final_path.resolve(), chars

    # ============================================================
    # -----------------------  PDF EXPORT  -----------------------
    # ============================================================

    def _which(self, exe: str) -> Optional[str]:
        p = shutil.which(exe)
        if p:
            return p
        # common Windows install locations (helps before PATH refresh)
        common = {
            "pandoc": [
                r"C:\Program Files\Pandoc\pandoc.exe",
                r"C:\Program Files (x86)\Pandoc\pandoc.exe",
            ],
            "xelatex": [
                r"C:\Program Files\MiKTeX\miktex\bin\x64\xelatex.exe",
                r"C:\Program Files\MiKTeX 2.9\miktex\bin\x64\xelatex.exe",
            ],
            "wkhtmltopdf": [
                r"C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe",
                r"C:\Program Files (x86)\wkhtmltopdf\bin\wkhtmltopdf.exe",
            ],
        }.get(exe.lower(), [])
        for path in common:
            if Path(path).exists():
                return path
        return None

    def _pandoc_common_args(self) -> List[str]:
        return [
            str(self.output_md),
            "--toc", "--toc-depth=3",
            "--metadata", "link-citations=true",
            "--resource-path", str(self.base_dir),
            "-V", "geometry:margin=1in",
            "-V", "fontsize=12pt",
            "-V", "colorlinks=true",
            "-V", "linkcolor=blue",
            "-V", "urlcolor=blue",
        ]

    def export_pdf(self, log_fn=None) -> Path:
        def _log(msg: str):
            if log_fn:
                try:
                    log_fn(msg)
                except Exception:
                    pass
            else:
                print(msg)

        pandoc = self._which("pandoc")
        if not pandoc:
            raise RuntimeError(
                "Pandoc is not installed or not on PATH. Install from https://pandoc.org/installing.html"
            )

        prefer = getattr(self, "_pdf_pref", "auto").lower()

        def try_xelatex() -> bool:
            xelatex = self._which("xelatex")
            if not xelatex:
                return False
            _log("🧾 Exporting PDF via Pandoc (XeLaTeX)…")
            args = [pandoc, *self._pandoc_common_args(),
                    "--pdf-engine=xelatex",
                    "-V", "mainfont=Segoe UI",
                    "-o", str(self.output_pdf)]
            try:
                subprocess.run(args, check=True)
                _log(f"✅ PDF generated: {self.output_pdf}")
                return True
            except subprocess.CalledProcessError as e:
                _log(f"[warn] XeLaTeX failed: {e}")
                return False

        def try_wkhtml() -> bool:
            wk = self._which("wkhtmltopdf")
            if not wk:
                return False
            _log("🧾 Exporting PDF via Pandoc (wkhtmltopdf)…")
            args = [pandoc, *self._pandoc_common_args(),
                    "--pdf-engine=wkhtmltopdf",
                    "-o", str(self.output_pdf)]
            try:
                subprocess.run(args, check=True)
                _log(f"✅ PDF generated: {self.output_pdf}")
                return True
            except subprocess.CalledProcessError as e:
                _log(f"[warn] wkhtmltopdf failed: {e}")
                return False

        ok = False
        if prefer == "xelatex":
            ok = try_xelatex() or try_wkhtml()
        elif prefer == "wkhtmltopdf":
            ok = try_wkhtml() or try_xelatex()
        else:
            ok = try_xelatex() or try_wkhtml()

        if not ok:
            raise RuntimeError(
                "No working PDF engine found. Install MiKTeX (XeLaTeX) or wkhtmltopdf and ensure it's on PATH."
            )
        return self.output_pdf
