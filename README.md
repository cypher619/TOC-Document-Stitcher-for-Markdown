# TOC Document Stitcher for MD

A Python + PyQt6 desktop app that **stitches a Markdown project into a single, publication‑ready document**—using your **`Table_of_Contents.md` as the canonical source of truth**. It preserves your ordering, linkifies the TOC, aligns heading levels, and (optionally) exports a PDF via Pandoc.

> This README reflects the latest workflow and features we just added (TOC‑driven tree, per‑project settings, metadata per project, robust PDF export, etc.).

---

## ✨ Highlights (what’s new)

- 🔁 **TOC‑driven build (deterministic)** — We *read the TOC, build a hierarchy, then process it in preorder*. No directory sorting or guessing.
- 📖 **Original TOC, linkified in place** — The `Table_of_Contents.md` content is inserted **exactly where it appears** in the TOC and is **linkified** (H2 headings and H3 list items both clickable).
- 🧱 **Robust title→file matching** — Tolerates date prefixes (`YYYYMMDD-N_`), underscores, punctuation, and uses token overlap as a fallback.
- 🧩 **Heading alignment** — If a document’s top heading doesn’t match the TOC level, headings are promoted/demoted to keep structure consistent (capped to H1–H6).
- 💾 **Per‑project settings file** — `stitcher_settings.yaml` lives next to the TOC. Your **section selections** and **metadata** (title, author, date, etc.) **persist** per project.
- 🖱️ **Save Project Settings button** — Save your current selections & metadata without building.
- 🧭 **GUI improvements** — Preorder collection (no reverse surprises), optional “Open Output Folder” button, Ctrl+S to save settings.
- 🧾 **PDF Export (Windows‑friendly)** — Prefers **XeLaTeX** (MiKTeX) for best typography, falls back to **wkhtmltopdf** if LaTeX isn’t available. Clear guidance if tools are missing.
- 🧠 **Zero hard‑coding** — Adding/removing entries in the TOC is enough; the app adapts on the next run.

---

## 🗂️ Project layout (suggested)

```
toc-document-stitcher/
│
├── core.py                  # stitching engine (TOC parser, linkify, heading shift, PDF export)
├── gui.py                   # PyQt6 app (tree, buttons, progress output)
├── requirements.txt
├── .gitignore
└── README.md  (this file)
```

Your **working directory (picked in the GUI)** should contain:
- `Table_of_Contents.md` (your canonical structure)
- The `.md` files referenced by the TOC
- After first run (or save): `stitcher_settings.yaml` (project‑specific selections & metadata)

---

## ⚙️ Requirements

### Python (install once)
```bash
pip install -r requirements.txt
```

### External tools (for PDF export)
- **Pandoc** (required for any PDF route)  
- **XeLaTeX** via **MiKTeX** (preferred PDF engine), *or* **wkhtmltopdf** (fallback)

**Quick install (Windows, PowerShell):**
```powershell
winget install -e --id JohnMacFarlane.Pandoc
winget install -e --id MiKTeX.MiKTeX           # for XeLaTeX route
# Optional fallback:
winget install -e --id wkhtmltopdf.wkhtmltopdf
```

**Verify:**
```powershell
pandoc -v
xelatex --version        # if using MiKTeX
wkhtmltopdf --version    # if using fallback
```

> Tip: If you just installed these, **restart your terminal/app** so PATH changes apply.

---

## 🚀 Usage

### 1) Start the GUI
```bash
python gui.py
```

### 2) Pick your project directory
- This is the folder that contains `Table_of_Contents.md`.
- On first open, the app creates **`stitcher_settings.yaml`** from your TOC (all items included by default).
- On subsequent opens, it **reconciles** settings with the current TOC (preserves your previous selections by slug; adds new TOC items automatically).

### 3) Check/uncheck sections in the tree
- The tree mirrors your TOC (H2/H3…).
- Your choices persist per project.

### 4) Build
- Click **Build Selected Sections**.  
- Output files appear in the project directory:
  - **Markdown:** `my_doc.md` (by default; can be changed per project)
  - **PDF:** `my_doc.pdf` (if Pandoc + engine available)

### 5) Save settings at any time
- Click **Save Project Settings** (or press **Ctrl+S**).  
- Updates `stitcher_settings.yaml` with your current selections and metadata.

---

## 🧩 How it works (short)

1. **Parse the TOC** ➜ produce ordered `TOCEntry(level, title)` list.  
2. **Build a tree** ➜ `TOCNode(level, title, children)` by nesting items (H3 under H2, etc.).  
3. **Walk the tree (preorder)** ➜ when a node is **“Table of Contents”**, insert the original `Table_of_Contents.md`, **linkified in place**; otherwise **match** the node to a file and **align headings**.  
4. **Anchors** are inserted for each node so the TOC links resolve in both MD and PDF.  
5. **PDF export** via Pandoc (XeLaTeX preferred, wkhtmltopdf fallback).

---

## 🧾 `stitcher_settings.yaml` (per‑project)

This file lives **next to your `Table_of_Contents.md`** and is created/updated automatically.

```yaml
version: 1

selections:
  - slug: executive-summary
    title: Executive Summary
    level: 2
    include: true
  # … one entry per TOC line (slugs keep matches stable if punctuation changes)

metadata:
  title: "My Doc"
  subtitle: "Stitched together from multiple MD Files"
  author: "Cypher"
  date: "October 2025"
  license: "CC BY-SA 4.0"
  geometry: "margin=1in"
  fontsize: "12pt"
  toc: true
  toc-depth: 3

output:
  filename: "my_doc.md"
  mode: "overwrite"            # overwrite | timestamped | append (append supported now; others easy to add)
  pdf_engine_preference: "auto"   # auto | xelatex | wkhtmltopdf
```

- **Selections** are stored by **slug** (derived from title) so small punctuation/case tweaks won’t break persistence.  
- **Metadata** becomes the **YAML front matter** at the top of the final Markdown.  
- **Output** lets you choose filename and engine preference globally for the project.

---

## 🖥️ GUI Overview

- **Pick Working Directory** — select the folder with your TOC.
- **Build Selected Sections** — stitches MD (and PDF if available). Overwrites the MD by default (configurable).
- **Save Project Settings** — writes selections + metadata to `stitcher_settings.yaml` now (also saved automatically after successful build).
- *(Optional)* **Open Output Folder** — opens the project folder in Explorer.

Keyboard shortcuts:
- **Ctrl+S** — Save Project Settings.

---

## 🧾 PDF export details

- Prefers **XeLaTeX (MiKTeX)** for high‑quality output with clickable TOC/bookmarks.
- Falls back to **wkhtmltopdf** if XeLaTeX isn’t available.
- If neither is available, you’ll get a clear error explaining what to install.

Common fixes on Windows:
- Make sure `pandoc`, `xelatex` (MiKTeX), or `wkhtmltopdf` are on **PATH** (`where pandoc`, etc.).
- After installing, **restart terminal/app** so PATH changes apply.

---

## 🧪 Troubleshooting

- **“expected string or bytes-like object, got 'builtin_function_or_method'”**  
  Make sure the GUI collects titles with `item.text(0)` (not `item.text`).

- **Order looks reversed**  
  Ensure the GUI builds the selection list with a **preorder traversal** (no `reversed()`, no LIFO stack).

- **TOC is on page 1 or out of place**  
  The TOC is inserted **exactly where your “Table of Contents” entry appears** in `Table_of_Contents.md`.

- **“Can’t find Pandoc” but I installed PandaDoc**  
  That’s a different product. You need **Pandoc** (converter), not **PandaDoc** (e‑signature).

---

## 📦 Development

- Python 3.10+ recommended
- PyQt6 based GUI
- Local file processing only (no network required)

Run:
```bash
python gui.py
```

---

## 🪪 License

**CC BY‑SA 4.0** — Share and adapt with attribution and the same license.

---

**Author:** Cypher  
**Version:** 1.1  
**Date:** October 2025
