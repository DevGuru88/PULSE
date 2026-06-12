"""
generate_templates.py
=====================
Industry-standard minimal professional DOCX templates.
Research basis:
  Arc42       → Architecture & Design
  INVEST      → Definition of Ready
  DoD Levels  → Definition of Done (Scrum Guide)
  ISO 31000   → Risk Register
  ITIL v4     → Runbook / SOP
  Scrum Guide → Sprint Ceremony Log
  PMI PMBOK   → CPDD / Project Charter

Run:  py generate_templates.py
Out:  Project_Templates_Slim/  (10 files, ~38-55 KB each)
"""

from pathlib import Path
from docx import Document
from docx.shared import Pt, Cm, RGBColor, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from lxml import etree
import copy
from datetime import date

# ─────────────────────────── THEME ───────────────────────────
C_NAVY      = "1B3A5C"          # header rows, h1 underline
C_BLUE      = "2980B9"          # h2 text, accent line
C_STEEL     = "D6E4F0"          # alt table row
C_GREEN_H   = "196F3D"          # positive / in-scope
C_RED_H     = "922B21"          # negative / risk / rollback
C_ORANGE_H  = "B7770D"          # warning / debt
C_LIGHT     = "EBF5FB"          # note box fill
C_GREY_ROW  = "F2F3F4"         # zebra row 2

RGB_NAVY    = RGBColor(0x1B, 0x3A, 0x5C)
RGB_BLUE    = RGBColor(0x29, 0x80, 0xB9)
RGB_WHITE   = RGBColor(0xFF, 0xFF, 0xFF)
RGB_BLACK   = RGBColor(0x00, 0x00, 0x00)
RGB_GREEN   = RGBColor(0x19, 0x6F, 0x3D)
RGB_RED     = RGBColor(0x92, 0x2B, 0x21)
RGB_ORANGE  = RGBColor(0xB7, 0x77, 0x0D)

OUT_DIR = Path(__file__).parent / "Project_Templates_Slim"
OUT_DIR.mkdir(exist_ok=True)

TODAY = date.today().strftime("%d %b %Y")


# ═══════════════════════════ XML HELPERS ═══════════════════════════

def _shade(cell, hex_color: str):
    tc = cell._tc
    tcPr = tc.find(qn("w:tcPr"))
    if tcPr is None:
        tcPr = OxmlElement("w:tcPr")
        tc.insert(0, tcPr)
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_color)
    existing = tcPr.find(qn("w:shd"))
    if existing is not None:
        tcPr.remove(existing)
    tcPr.append(shd)


def _set_cell_border(cell, top=None, bottom=None, left=None, right=None):
    """Apply borders to a single cell. Each param: (hex_color, sz_eighths)."""
    tc = cell._tc
    tcPr = tc.find(qn("w:tcPr"))
    if tcPr is None:
        tcPr = OxmlElement("w:tcPr")
        tc.insert(0, tcPr)
    tcBorders = tcPr.find(qn("w:tcBorders"))
    if tcBorders is None:
        tcBorders = OxmlElement("w:tcBorders")
        tcPr.append(tcBorders)
    for side, val in [("top", top), ("bottom", bottom), ("left", left), ("right", right)]:
        if val:
            color, sz = val
            b = OxmlElement(f"w:{'start' if side=='left' else 'end' if side=='right' else side}")
            b.set(qn("w:val"), "single")
            b.set(qn("w:sz"), str(sz))
            b.set(qn("w:space"), "0")
            b.set(qn("w:color"), color)
            existing = tcBorders.find(qn(f"w:{'start' if side=='left' else 'end' if side=='right' else side}"))
            if existing is not None:
                tcBorders.remove(existing)
            tcBorders.append(b)


def _remove_cell_borders(cell):
    """Set all borders to none."""
    tc = cell._tc
    tcPr = tc.find(qn("w:tcPr"))
    if tcPr is None:
        tcPr = OxmlElement("w:tcPr")
        tc.insert(0, tcPr)
    tcBorders = OxmlElement("w:tcBorders")
    for side in ["top", "start", "bottom", "end", "insideH", "insideV"]:
        b = OxmlElement(f"w:{side}")
        b.set(qn("w:val"), "none")
        tcBorders.append(b)
    existing = tcPr.find(qn("w:tcBorders"))
    if existing is not None:
        tcPr.remove(existing)
    tcPr.append(tcBorders)


def _table_outer_border(table, hex_color: str, sz: int = 6):
    tbl = table._tbl
    tblPr = tbl.find(qn("w:tblPr"))
    if tblPr is None:
        tblPr = OxmlElement("w:tblPr")
        tbl.insert(0, tblPr)
    tblBorders = OxmlElement("w:tblBorders")
    for side in ["top", "start", "bottom", "end", "insideH", "insideV"]:
        b = OxmlElement(f"w:{side}")
        b.set(qn("w:val"), "single")
        b.set(qn("w:sz"), str(sz))
        b.set(qn("w:space"), "0")
        b.set(qn("w:color"), hex_color)
        tblBorders.append(b)
    existing = tblPr.find(qn("w:tblBorders"))
    if existing is not None:
        tblPr.remove(existing)
    tblPr.append(tblBorders)


def _no_space_before(para):
    pPr = para._p.find(qn("w:pPr"))
    if pPr is None:
        pPr = OxmlElement("w:pPr")
        para._p.insert(0, pPr)
    spacing = pPr.find(qn("w:spacing"))
    if spacing is None:
        spacing = OxmlElement("w:spacing")
        pPr.append(spacing)
    spacing.set(qn("w:before"), "0")
    spacing.set(qn("w:after"), "0")
    spacing.set(qn("w:line"), "240")
    spacing.set(qn("w:lineRule"), "auto")


def _para_border_bottom(para, hex_color: str, sz: int = 6):
    pPr = para._p.find(qn("w:pPr"))
    if pPr is None:
        pPr = OxmlElement("w:pPr")
        para._p.insert(0, pPr)
    pBdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), str(sz))
    bottom.set(qn("w:space"), "1")
    bottom.set(qn("w:color"), hex_color)
    pBdr.append(bottom)
    existing = pPr.find(qn("w:pBdr"))
    if existing is not None:
        pPr.remove(existing)
    pPr.append(pBdr)


def _set_row_height(row, height_cm: float):
    tr = row._tr
    trPr = tr.find(qn("w:trPr"))
    if trPr is None:
        trPr = OxmlElement("w:trPr")
        tr.insert(0, trPr)
    trHeight = OxmlElement("w:trHeight")
    trHeight.set(qn("w:val"), str(int(height_cm * 914.4)))  # EMU twips: 1cm ≈ 567 twips
    trHeight.set(qn("w:hRule"), "atLeast")
    existing = trPr.find(qn("w:trHeight"))
    if existing is not None:
        trPr.remove(existing)
    trPr.append(trHeight)


# ═══════════════════════════ DOCUMENT SETUP ═══════════════════════════

def _new_doc():
    doc = Document()
    sec = doc.sections[0]
    sec.top_margin    = Cm(1.8)
    sec.bottom_margin = Cm(1.8)
    sec.left_margin   = Cm(2.0)
    sec.right_margin  = Cm(2.0)
    # Default paragraph spacing
    doc.styles["Normal"].font.name = "Calibri"
    doc.styles["Normal"].font.size = Pt(10)
    style = doc.styles["Normal"]
    pPr = style.element.find(qn("w:pPr"))
    if pPr is None:
        pPr = OxmlElement("w:pPr")
        style.element.append(pPr)
    spacing = pPr.find(qn("w:spacing"))
    if spacing is None:
        spacing = OxmlElement("w:spacing")
        pPr.append(spacing)
    spacing.set(qn("w:before"), "40")
    spacing.set(qn("w:after"), "40")
    return doc


# ═══════════════════════════ SHARED COMPONENTS ═══════════════════════════

def _header_block(doc, title: str, subtitle: str, fields: list[tuple]):
    """
    Compact top-of-document header:
      [ TITLE           ]   [ field | val  ]
                            [ field | val  ]
    """
    # Two-column outer table: left = title, right = meta fields
    tbl = doc.add_table(rows=1, cols=2)
    tbl.alignment = WD_TABLE_ALIGNMENT.LEFT
    tbl.allow_autofit = False
    _table_outer_border(tbl, C_NAVY, 8)
    w = tbl.columns
    tbl.columns[0].width = Cm(9)
    tbl.columns[1].width = Cm(8.7)

    left_cell = tbl.rows[0].cells[0]
    right_cell = tbl.rows[0].cells[1]
    _shade(left_cell, C_NAVY)
    _shade(right_cell, "F8FBFE")

    # Title + subtitle in left
    p = left_cell.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    run = p.add_run(title)
    run.bold = True
    run.font.size = Pt(16)
    run.font.color.rgb = RGB_WHITE
    run.font.name = "Calibri"
    _no_space_before(p)
    if subtitle:
        p2 = left_cell.add_paragraph(subtitle)
        run2 = p2.runs[0] if p2.runs else p2.add_run(subtitle)
        # rebuild
        for r in p2.runs:
            r.font.size = Pt(9)
            r.font.color.rgb = RGBColor(0xAE, 0xD6, 0xF1)
            r.font.name = "Calibri"
            r.italic = True

    # Meta fields in right
    for i, (key, val) in enumerate(fields):
        cell = right_cell if i == 0 else None
        if i == 0:
            p_meta = right_cell.paragraphs[0]
        else:
            p_meta = right_cell.add_paragraph()
        p_meta.clear()
        run_k = p_meta.add_run(f"{key}: ")
        run_k.bold = True
        run_k.font.size = Pt(8.5)
        run_k.font.color.rgb = RGB_NAVY
        run_k.font.name = "Calibri"
        run_v = p_meta.add_run(str(val))
        run_v.font.size = Pt(8.5)
        run_v.font.name = "Calibri"
        _no_space_before(p_meta)

    left_cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
    right_cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
    _set_row_height(tbl.rows[0], 2.2)
    doc.add_paragraph()


def _section(doc, text: str):
    """Section heading with blue bottom border."""
    p = doc.add_paragraph()
    _no_space_before(p)
    pPr = p._p.find(qn("w:pPr"))
    if pPr is None:
        pPr = OxmlElement("w:pPr")
        p._p.insert(0, pPr)
    spacing = pPr.find(qn("w:spacing"))
    if spacing is None:
        spacing = OxmlElement("w:spacing")
        pPr.append(spacing)
    spacing.set(qn("w:before"), "120")
    spacing.set(qn("w:after"), "40")
    run = p.add_run(text.upper())
    run.bold = True
    run.font.size = Pt(10)
    run.font.color.rgb = RGB_NAVY
    run.font.name = "Calibri"
    _para_border_bottom(p, C_BLUE, 6)
    return p


def _subsection(doc, text: str):
    p = doc.add_paragraph()
    run = p.add_run(text)
    run.bold = True
    run.font.size = Pt(9.5)
    run.font.color.rgb = RGB_BLUE
    run.font.name = "Calibri"
    _no_space_before(p)
    return p


def _note_box(doc, text: str, color=C_LIGHT, icon="ℹ"):
    tbl = doc.add_table(rows=1, cols=1)
    _shade(tbl.rows[0].cells[0], color)
    _set_cell_border(tbl.rows[0].cells[0],
                     left=(C_BLUE, 12))
    p = tbl.rows[0].cells[0].paragraphs[0]
    run = p.add_run(f"{icon}  {text}")
    run.font.size = Pt(8.5)
    run.font.color.rgb = RGB_NAVY
    run.font.name = "Calibri"
    run.italic = True
    _no_space_before(p)
    doc.add_paragraph()


def _diagram_box(doc, label: str = "INSERT DIAGRAM / FLOWCHART HERE", height_cm: float = 4.5):
    """Dashed-border placeholder box for diagrams/flowcharts."""
    tbl = doc.add_table(rows=1, cols=1)
    cell = tbl.rows[0].cells[0]
    _shade(cell, "F8FBFE")
    _set_row_height(tbl.rows[0], height_cm)

    # Dashed border via XML
    tc = cell._tc
    tcPr = tc.find(qn("w:tcPr"))
    if tcPr is None:
        tcPr = OxmlElement("w:tcPr")
        tc.insert(0, tcPr)
    tcBorders = OxmlElement("w:tcBorders")
    for side in ["top", "start", "bottom", "end"]:
        b = OxmlElement(f"w:{side}")
        b.set(qn("w:val"), "dashDot")
        b.set(qn("w:sz"), "8")
        b.set(qn("w:space"), "0")
        b.set(qn("w:color"), C_BLUE)
        tcBorders.append(b)
    existing = tcPr.find(qn("w:tcBorders"))
    if existing is not None:
        tcPr.remove(existing)
    tcPr.append(tcBorders)

    cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
    p = cell.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run(f"[ {label} ]")
    run.font.size = Pt(9)
    run.font.color.rgb = RGB_BLUE
    run.font.name = "Calibri"
    run.italic = True
    p2 = cell.add_paragraph("↳  Use draw.io / Lucidchart / Visio — embed or paste image")
    p2.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for r in p2.runs:
        r.font.size = Pt(7.5)
        r.font.color.rgb = RGBColor(0x7F, 0x8C, 0x8D)
        r.font.name = "Calibri"
    doc.add_paragraph()


def _make_table(doc, headers: list[str], rows: list[list[str]],
                hdr_hex: str = C_NAVY, col_widths: list[float] = None,
                alt: bool = True, font_pt: float = 9.0):
    """Compact styled table."""
    ncols = len(headers)
    tbl = doc.add_table(rows=1 + len(rows), cols=ncols)
    tbl.alignment = WD_TABLE_ALIGNMENT.LEFT
    _table_outer_border(tbl, C_NAVY, 6)

    # Total usable width ≈ 17.7 cm (A4 minus 4cm margins)
    if col_widths:
        for i, col in enumerate(tbl.columns):
            if i < len(col_widths):
                col.width = Cm(col_widths[i])
    else:
        w = Cm(17.7 / ncols)
        for col in tbl.columns:
            col.width = w

    # Header row
    hdr_row = tbl.rows[0]
    for i, h in enumerate(headers):
        cell = hdr_row.cells[i]
        _shade(cell, hdr_hex)
        p = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.LEFT
        run = p.add_run(h)
        run.bold = True
        run.font.size = Pt(font_pt)
        run.font.color.rgb = RGB_WHITE
        run.font.name = "Calibri"
        _no_space_before(p)

    # Data rows
    for r_idx, row_data in enumerate(rows):
        row = tbl.rows[r_idx + 1]
        fill = C_GREY_ROW if (alt and r_idx % 2 == 1) else "FFFFFF"
        for c_idx, val in enumerate(row_data):
            cell = row.cells[c_idx]
            _shade(cell, fill)
            p = cell.paragraphs[0]
            run = p.add_run(str(val))
            run.font.size = Pt(font_pt)
            run.font.name = "Calibri"
            _no_space_before(p)

    doc.add_paragraph()
    return tbl


def _checklist(doc, items: list[tuple], hdr_hex: str = C_NAVY):
    """
    Checklist table: # | Criteria | Priority | Owner | ☐
    items: list of (criteria, priority)
    """
    headers = ["#", "Criteria", "Priority", "Owner", "☐ Done"]
    rows = [[str(i+1), c, p, "", "☐"] for i, (c, p) in enumerate(items)]
    _make_table(doc, headers, rows, hdr_hex=hdr_hex,
                col_widths=[0.7, 9.0, 2.2, 2.8, 1.5], font_pt=9.0)


def _field_table(doc, fields: list[tuple], cols: int = 2, hdr_hex: str = C_NAVY):
    """
    Key-value info block displayed as a compact 2-col or 4-col table.
    fields: [(label, placeholder), ...]
    """
    if cols == 4:
        # Pair up
        paired = []
        for i in range(0, len(fields), 2):
            left = fields[i]
            right = fields[i+1] if i+1 < len(fields) else ("", "")
            paired.append([left[0], left[1], right[0], right[1]])
        tbl = doc.add_table(rows=len(paired), cols=4)
        _table_outer_border(tbl, C_NAVY, 6)
        col_widths = [3.5, 5.0, 3.5, 5.2]
        for i, col in enumerate(tbl.columns):
            col.width = Cm(col_widths[i])
        for r_idx, row_data in enumerate(paired):
            row = tbl.rows[r_idx]
            fill = C_GREY_ROW if r_idx % 2 == 1 else "FFFFFF"
            for c_idx, val in enumerate(row_data):
                cell = row.cells[c_idx]
                is_label = (c_idx % 2 == 0)
                _shade(cell, hdr_hex if is_label else fill)
                p = cell.paragraphs[0]
                run = p.add_run(str(val))
                run.bold = is_label
                run.font.size = Pt(9.0)
                run.font.color.rgb = RGB_WHITE if is_label else RGB_BLACK
                run.font.name = "Calibri"
                _no_space_before(p)
    else:
        tbl = doc.add_table(rows=len(fields), cols=2)
        _table_outer_border(tbl, C_NAVY, 6)
        tbl.columns[0].width = Cm(4.5)
        tbl.columns[1].width = Cm(13.2)
        for r_idx, (label, val) in enumerate(fields):
            row = tbl.rows[r_idx]
            fill = C_GREY_ROW if r_idx % 2 == 1 else "FFFFFF"
            _shade(row.cells[0], hdr_hex)
            _shade(row.cells[1], fill)
            for c_idx, txt in enumerate([label, val]):
                cell = row.cells[c_idx]
                p = cell.paragraphs[0]
                run = p.add_run(str(txt))
                run.bold = (c_idx == 0)
                run.font.size = Pt(9.0)
                run.font.color.rgb = RGB_WHITE if c_idx == 0 else RGB_BLACK
                run.font.name = "Calibri"
                _no_space_before(p)
    doc.add_paragraph()
    return tbl


def _revision_table(doc):
    _section(doc, "Document Control")
    _make_table(doc,
        headers=["Version", "Date", "Author", "Summary of Changes", "Approved By"],
        rows=[["1.0", TODAY, "<Author>", "Initial draft", "<Approver>"]],
        col_widths=[1.8, 2.8, 3.0, 6.5, 3.3], font_pt=9.0)


def _save(doc, filename: str):
    path = OUT_DIR / filename
    doc.save(str(path))
    kb = path.stat().st_size / 1024
    print(f"  ✓  {filename:<55} {kb:.1f} KB")


# ═══════════════════════════════════════════════════════════════════
#  1. ARCHITECTURE & DESIGN  (arc42-inspired)
# ═══════════════════════════════════════════════════════════════════

def build_architecture():
    doc = _new_doc()
    _header_block(doc, "Architecture & Design Document",
                  "arc42 lightweight — System Design Reference",
                  [("Doc ID", "ARCH-001"), ("Project", "<Project Name>"),
                   ("Version", "1.0"), ("Date", TODAY),
                   ("Architect", "<Name>"), ("Status", "Draft")])

    # 1. Purpose
    _section(doc, "1. Purpose & Scope")
    _note_box(doc, "What problem does this system solve? What are the boundaries? (2–3 sentences max)", icon="🎯")

    # 2. System Context
    _section(doc, "2. System Context")
    _note_box(doc, "Who uses the system? What external systems does it integrate with?", icon="📌")
    _diagram_box(doc, "SYSTEM CONTEXT DIAGRAM  —  Actors · System Boundary · External Integrations", 5.0)

    # 3. Tech Stack
    _section(doc, "3. Technology Stack")
    _make_table(doc,
        headers=["Layer", "Technology / Framework", "Version", "Justification"],
        rows=[
            ["Frontend", "", "", ""],
            ["Backend / API", "", "", ""],
            ["Database", "", "", ""],
            ["Auth / IAM", "", "", ""],
            ["Infra / Cloud", "", "", ""],
            ["CI/CD", "", "", ""],
        ],
        col_widths=[3.0, 4.5, 2.2, 7.5])

    # 4. Component Overview
    _section(doc, "4. Component Architecture")
    _diagram_box(doc, "COMPONENT / CONTAINER DIAGRAM  —  Services · DBs · Queues · External APIs", 5.0)
    _make_table(doc,
        headers=["Component", "Responsibility", "Technology", "Exposes / Consumes"],
        rows=[["", "", "", ""], ["", "", "", ""], ["", "", "", ""]],
        col_widths=[3.5, 5.5, 3.5, 4.7])

    # 5. Key Flows
    _section(doc, "5. Key Interaction Flows")
    _subsection(doc, "5.1  Primary Flow")
    _diagram_box(doc, "SEQUENCE / FLOW DIAGRAM  —  Happy Path (e.g., User Login · Core Transaction)", 4.5)
    _subsection(doc, "5.2  Error / Edge Cases")
    _note_box(doc, "List the 2–3 most critical error paths and how the system handles them.", icon="⚠")

    # 6. ADRs
    _section(doc, "6. Architecture Decision Records (ADRs)")
    _make_table(doc,
        headers=["ADR #", "Decision", "Alternatives Considered", "Rationale", "Status"],
        rows=[["ADR-001", "", "", "", "Accepted"],
              ["ADR-002", "", "", "", "Proposed"]],
        col_widths=[1.5, 4.0, 4.0, 5.5, 2.2])

    # 7. NFRs
    _section(doc, "7. Non-Functional Requirements")
    _make_table(doc,
        headers=["Category", "Requirement", "Target / SLA", "Measure", "Priority"],
        rows=[
            ["Performance", "API response time", "< 200 ms p95", "APM", "High"],
            ["Availability", "Uptime", "99.9%", "Monitoring", "High"],
            ["Scalability", "Concurrent users", "10,000", "Load test", "Med"],
            ["Security", "Auth mechanism", "OAuth 2.0 / OIDC", "Pen test", "High"],
            ["Data Retention", "Logs & data", "7 years", "Audit", "Med"],
        ],
        col_widths=[3.0, 4.5, 3.0, 2.8, 2.0])

    _revision_table(doc)
    _save(doc, "Architecture_and_Design_Template.docx")


# ═══════════════════════════════════════════════════════════════════
#  2. CODEBASE KB / CHANGE VERSIONING
# ═══════════════════════════════════════════════════════════════════

def build_codebase_kb():
    doc = _new_doc()
    _header_block(doc, "Codebase KB & Change Versioning",
                  "Knowledge Base · Version Control · ADR Log",
                  [("Doc ID", "KB-001"), ("Repo", "<repo-url>"),
                   ("Version", "1.0"), ("Date", TODAY),
                   ("Owner", "<Tech Lead>"), ("Status", "Active")])

    _section(doc, "1. Repository Overview")
    _field_table(doc, [
        ("Repo URL", ""),      ("Primary Branch", "main"),
        ("Language(s)", ""),   ("Framework(s)", ""),
        ("CI/CD Pipeline", ""), ("Artifact Registry", ""),
    ], cols=4)

    _section(doc, "2. Branching Strategy")
    _diagram_box(doc, "GIT FLOW / TRUNK-BASED DIAGRAM  —  feature → develop → release → main", 4.0)
    _make_table(doc,
        headers=["Branch", "Purpose", "Naming Convention", "Merge Policy"],
        rows=[["main", "Production-ready code", "main", "PR + 2 approvals"],
              ["develop", "Integration branch", "develop", "PR + 1 approval"],
              ["feature/*", "New features", "feature/<ticket-id>-desc", "Squash merge"],
              ["hotfix/*", "Production fixes", "hotfix/<ticket-id>-desc", "Fast-forward"]],
        col_widths=[2.5, 4.5, 4.5, 5.7])

    _section(doc, "3. Change Log")
    _make_table(doc,
        headers=["Date", "Version", "PR / Commit", "Author", "Type", "Summary", "Breaking?"],
        rows=[["", "1.0.0", "", "", "Feature", "", "No"],
              ["", "", "", "", "", "", ""]],
        col_widths=[2.2, 1.8, 2.5, 2.5, 2.2, 5.0, 1.5])

    _section(doc, "4. Architecture Decision Records (ADRs)")
    _make_table(doc,
        headers=["ADR #", "Date", "Title", "Status", "Supersedes"],
        rows=[["ADR-001", "", "", "Accepted", "—"],
              ["ADR-002", "", "", "Proposed", "—"]],
        col_widths=[2.0, 2.5, 7.5, 2.7, 2.5])

    _section(doc, "5. Dependency Registry")
    _make_table(doc,
        headers=["Package", "Version", "License", "Direct / Transitive", "Risk", "Last Reviewed"],
        rows=[["", "", "", "Direct", "Low", ""],
              ["", "", "", "", "", ""]],
        col_widths=[3.5, 2.0, 2.5, 3.0, 2.0, 3.2],
        hdr_hex=C_BLUE)

    _section(doc, "6. Technical Debt Register")
    _make_table(doc,
        headers=["ID", "Description", "Component", "Severity", "Effort", "Target Sprint", "Owner"],
        rows=[["TD-001", "", "", "High", "", "", ""],
              ["TD-002", "", "", "Med", "", "", ""]],
        col_widths=[1.5, 4.5, 2.5, 1.8, 1.8, 2.8, 2.3],
        hdr_hex=C_ORANGE_H)

    _revision_table(doc)
    _save(doc, "Codebase_KB_Change_Versioning_Template.docx")


# ═══════════════════════════════════════════════════════════════════
#  3. CPDD — COMPREHENSIVE PROJECT DEFINITION DOCUMENT
# ═══════════════════════════════════════════════════════════════════

def build_cpdd():
    doc = _new_doc()
    _header_block(doc, "Comprehensive Project Definition Doc",
                  "CPDD · Project Charter · Scope Statement  (PMI PMBOK aligned)",
                  [("Doc ID", "CPDD-001"), ("Project", "<Project Name>"),
                   ("Version", "1.0"), ("Date", TODAY),
                   ("PM", "<Name>"), ("Status", "Draft")])

    _section(doc, "1. Project Identity")
    _field_table(doc, [
        ("Project Name", ""),        ("Project Code", ""),
        ("Business Unit", ""),       ("Sponsor", ""),
        ("Start Date", ""),          ("Target Go-Live", ""),
        ("Budget", ""),              ("Priority", "High / Med / Low"),
    ], cols=4)

    _section(doc, "2. Problem Statement & Objective")
    _make_table(doc,
        headers=["Business Problem", "Desired Outcome", "Success Metric"],
        rows=[["", "", ""], ["", "", ""]],
        col_widths=[5.9, 5.9, 5.9])

    _section(doc, "3. Stakeholders")
    _make_table(doc,
        headers=["Name", "Role", "Department", "Responsibility", "Decision Authority"],
        rows=[["", "Sponsor", "", "Sign-off & funding", "✓"],
              ["", "Product Owner", "", "Requirements & priority", "✓"],
              ["", "Tech Lead", "", "Technical delivery", "—"],
              ["", "End User Rep", "", "UAT & feedback", "—"]],
        col_widths=[3.0, 3.5, 3.0, 5.2, 2.5])

    _section(doc, "4. Scope")
    tbl = doc.add_table(rows=1, cols=2)
    _table_outer_border(tbl, C_NAVY, 6)
    tbl.columns[0].width = Cm(8.85)
    tbl.columns[1].width = Cm(8.85)
    hdr_in = tbl.rows[0].cells[0]
    hdr_out = tbl.rows[0].cells[1]
    _shade(hdr_in, C_GREEN_H)
    _shade(hdr_out, C_RED_H)
    for cell, text in [(hdr_in, "✅  IN SCOPE"), (hdr_out, "❌  OUT OF SCOPE")]:
        p = cell.paragraphs[0]
        run = p.add_run(text)
        run.bold = True; run.font.size = Pt(9.5); run.font.color.rgb = RGB_WHITE
        run.font.name = "Calibri"
        _no_space_before(p)
    # Content rows
    for _ in range(4):
        row = tbl.add_row()
        for ci in range(2):
            p = row.cells[ci].paragraphs[0]
            run = p.add_run("▪  ")
            run.font.size = Pt(9); run.font.name = "Calibri"
            _no_space_before(p)
    doc.add_paragraph()

    _section(doc, "5. Deliverables & Milestones")
    _make_table(doc,
        headers=["Milestone", "Deliverable", "Owner", "Target Date", "Status"],
        rows=[["Kick-off", "", "", "", ""],
              ["Requirements Frozen", "", "", "", ""],
              ["Design Approved", "", "", "", ""],
              ["Dev Complete", "", "", "", ""],
              ["UAT Sign-off", "", "", "", ""],
              ["Go-Live", "", "", "", ""]],
        col_widths=[4.5, 5.0, 2.8, 2.8, 2.1])

    _section(doc, "6. Assumptions & Constraints")
    _make_table(doc,
        headers=["Type", "Description", "Impact if Wrong / Violated"],
        rows=[["Assumption", "", ""],
              ["Assumption", "", ""],
              ["Constraint", "", ""],
              ["Constraint", "", ""],
              ["Dependency", "", ""]],
        col_widths=[2.8, 7.5, 6.9])

    _section(doc, "7. Top Risks (Summary — see Risk Register for detail)")
    _make_table(doc,
        headers=["Risk", "Probability", "Impact", "Score", "Owner", "Mitigation"],
        rows=[["", "H/M/L", "H/M/L", "", "", ""],
              ["", "", "", "", "", ""],
              ["", "", "", "", "", ""]],
        col_widths=[4.5, 2.2, 2.0, 1.8, 2.5, 4.7],
        hdr_hex=C_RED_H)

    _section(doc, "8. Approvals")
    _make_table(doc,
        headers=["Role", "Name", "Signature", "Date"],
        rows=[["Project Sponsor", "", "", ""],
              ["Product Owner", "", "", ""],
              ["Project Manager", "", "", ""]],
        col_widths=[4.5, 4.5, 4.5, 3.7])

    _revision_table(doc)
    _save(doc, "CPDD_Template.docx")


# ═══════════════════════════════════════════════════════════════════
#  4. DEFINITION OF DONE (DoD)
# ═══════════════════════════════════════════════════════════════════

def build_dod():
    doc = _new_doc()
    _header_block(doc, "Definition of Done (DoD)",
                  "Scrum Guide aligned — 3-Level Quality Gate",
                  [("Doc ID", "DOD-001"), ("Project", "<Project Name>"),
                   ("Version", "1.0"), ("Date", TODAY),
                   ("Owner", "Scrum Master"), ("Status", "Active")])

    _note_box(doc,
              "DoD is a shared commitment by the team. ALL criteria at the applicable level must be met "
              "before an increment is considered Done. DoD overrides individual interpretation.", icon="📋")

    _section(doc, "DoD Levels Overview")
    _diagram_box(doc, "DOD PYRAMID  —  Story ▶ Sprint ▶ Release  (each level inherits the one below)", 3.5)

    _section(doc, "Level 1 — Story Done  (per User Story)")
    _checklist(doc, [
        ("Code written and peer-reviewed (PR approved by ≥1 reviewer)", "Mandatory"),
        ("Unit tests written — coverage ≥ 80% on changed lines", "Mandatory"),
        ("All acceptance criteria verified by developer", "Mandatory"),
        ("No new SonarQube / linter errors introduced", "Mandatory"),
        ("API contracts / interface updated in docs", "Mandatory"),
        ("Feature flag / toggle configured (if applicable)", "Conditional"),
        ("Ticket moved to 'Done' with test evidence attached", "Mandatory"),
    ], hdr_hex=C_GREEN_H)

    _section(doc, "Level 2 — Sprint Done  (end of sprint)")
    _checklist(doc, [
        ("All Level 1 DoD met for every story in sprint", "Mandatory"),
        ("Integration tests pass on dev/staging environment", "Mandatory"),
        ("Sprint Review demo delivered & recorded", "Mandatory"),
        ("Regression suite green (no P1/P2 regressions)", "Mandatory"),
        ("Documentation updated (WikiSpace / Confluence)", "Mandatory"),
        ("Tech debt items logged in backlog", "Recommended"),
        ("Sprint metrics captured (velocity, burndown)", "Mandatory"),
    ], hdr_hex=C_BLUE)

    _section(doc, "Level 3 — Release Done  (deployment gate)")
    _checklist(doc, [
        ("All Level 1 & 2 DoD met", "Mandatory"),
        ("Security scan (SAST/DAST) passed — no Critical/High open", "Mandatory"),
        ("Performance / load test passed against SLA targets", "Mandatory"),
        ("UAT sign-off obtained from Product Owner / stakeholder", "Mandatory"),
        ("Release notes drafted and approved", "Mandatory"),
        ("Runbook updated and dry-run completed", "Mandatory"),
        ("Rollback plan documented and tested", "Mandatory"),
        ("Go/No-Go decision recorded", "Mandatory"),
        ("Production deployment approved by Change Advisory Board", "Mandatory"),
    ], hdr_hex=C_NAVY)

    _section(doc, "Sign-Off")
    _make_table(doc,
        headers=["Role", "Name", "Sign-off", "Date"],
        rows=[["Scrum Master", "", "☐ Agreed", ""],
              ["Product Owner", "", "☐ Agreed", ""],
              ["Tech Lead", "", "☐ Agreed", ""]],
        col_widths=[4.5, 4.5, 4.5, 3.7])

    _revision_table(doc)
    _save(doc, "Defination_Of_Done_Template.docx")


# ═══════════════════════════════════════════════════════════════════
#  5. DEFINITION OF READY (DoR)
# ═══════════════════════════════════════════════════════════════════

def build_dor():
    doc = _new_doc()
    _header_block(doc, "Definition of Ready (DoR)",
                  "INVEST model — Sprint Entry Gate for User Stories",
                  [("Doc ID", "DOR-001"), ("Project", "<Project Name>"),
                   ("Version", "1.0"), ("Date", TODAY),
                   ("Owner", "Product Owner"), ("Status", "Active")])

    _note_box(doc,
              "A story is Ready when ALL mandatory criteria are met AND optional score ≥ 70 %. "
              "Stories not meeting DoR must be refined before sprint planning.", icon="🔍")

    _section(doc, "INVEST Principles (Reference)")
    _make_table(doc,
        headers=["Letter", "Principle", "What it means for this story"],
        rows=[["I", "Independent", "Can be delivered without dependency on another unfinished story"],
              ["N", "Negotiable", "Details can be adjusted; it's a conversation starter, not a contract"],
              ["V", "Valuable", "Delivers clear business or user value"],
              ["E", "Estimable", "Team can size it confidently"],
              ["S", "Small", "Completable within one sprint"],
              ["T", "Testable", "Acceptance criteria are clear and verifiable"]],
        col_widths=[1.2, 3.0, 13.0])

    _section(doc, "DoR Criteria Checklist")
    _checklist(doc, [
        ("User story written in format: 'As a [role], I want [goal], so that [benefit]'", "Mandatory"),
        ("Acceptance criteria defined (Given / When / Then or equivalent)", "Mandatory"),
        ("Story sized / estimated by the team (story points or T-shirt size)", "Mandatory"),
        ("No unresolved external dependencies blocking this story", "Mandatory"),
        ("UI mockup / wireframe available (if UI change)", "Conditional"),
        ("API contract / data schema agreed (if API change)", "Conditional"),
        ("Non-functional requirements stated (performance, security)", "Recommended"),
        ("Edge cases and error scenarios listed in AC", "Mandatory"),
        ("Story fits within one sprint (≤ agreed point threshold)", "Mandatory"),
        ("Test data / environment available for story validation", "Recommended"),
    ], hdr_hex=C_NAVY)

    _section(doc, "Story Readiness Scorecard")
    _make_table(doc,
        headers=["Criterion", "0 — Not Met", "1 — Partial", "2 — Fully Met", "Score"],
        rows=[["Story format", "Missing", "Partial info", "Complete", ""],
              ["Acceptance criteria", "None", "Vague", "Testable AC", ""],
              ["Estimate", "Not done", "Unsure", "Team agreed", ""],
              ["Dependencies clear", "Blocked", "Known risk", "Resolved", ""],
              ["Mockup / Schema", "N/A or missing", "Draft", "Approved", ""],
              ["", "", "", "TOTAL  (max 10)", ""]],
        col_widths=[4.5, 3.0, 3.0, 3.5, 2.2],
        hdr_hex=C_BLUE)
    _note_box(doc, "Threshold: Score ≥ 7 / 10 required for sprint entry.  Mandatory items must all be ≥ 1.", icon="📊")

    _section(doc, "Ready vs. Not Ready — Quick Reference")
    _make_table(doc,
        headers=["✅  Story is READY when...", "❌  Story is NOT READY when..."],
        rows=[["All mandatory AC are testable", "AC says 'as per discussion'"],
              ["Team sized it in planning/refinement", "Story was never estimated"],
              ["Known dependencies are resolved", "Waiting on another team / ticket"],
              ["Mockup signed off (if needed)", "Design still in progress"]],
        col_widths=[8.85, 8.85],
        hdr_hex=C_NAVY)

    _section(doc, "Sign-Off")
    _make_table(doc,
        headers=["Role", "Name", "Sign-off", "Date"],
        rows=[["Product Owner", "", "☐ Agreed", ""],
              ["Scrum Master", "", "☐ Agreed", ""],
              ["Tech Lead", "", "☐ Agreed", ""]],
        col_widths=[4.5, 4.5, 4.5, 3.7])

    _revision_table(doc)
    _save(doc, "DOR_Template.docx")


# ═══════════════════════════════════════════════════════════════════
#  6. RELEASE & DEPLOYMENT RUNBOOK  (ITIL v4 aligned)
# ═══════════════════════════════════════════════════════════════════

def build_runbook():
    doc = _new_doc()
    _header_block(doc, "Release & Deployment Runbook",
                  "ITIL v4 Release Management — Production Change Record",
                  [("Doc ID", "RUN-001"), ("Release", "<v1.x.x>"),
                   ("Env", "Production"), ("Date", TODAY),
                   ("Release Mgr", "<Name>"), ("Status", "Draft")])

    _section(doc, "1. Release Details")
    _field_table(doc, [
        ("Release Version", ""),       ("Release Type", "Major / Minor / Patch / Hotfix"),
        ("Planned Window", ""),        ("Rollback Deadline", ""),
        ("Change Ticket", ""),         ("Approver (CAB)", ""),
        ("Deployment Team", ""),       ("War Room Bridge", ""),
    ], cols=4)

    _section(doc, "2. Changes Included")
    _make_table(doc,
        headers=["Ticket", "Type", "Summary", "Risk", "Test Evidence"],
        rows=[["", "Feature", "", "Low", ""],
              ["", "Bug Fix", "", "Low", ""],
              ["", "Config", "", "Med", ""]],
        col_widths=[2.5, 2.5, 6.5, 2.0, 3.7])

    _section(doc, "3. Deployment Flow")
    _diagram_box(doc, "DEPLOYMENT PIPELINE DIAGRAM  —  Build ▶ Test ▶ Stage ▶ Approval ▶ Prod ▶ Verify", 4.5)

    _section(doc, "4. Pre-Release Checklist  (must be complete before deployment window opens)")
    _checklist(doc, [
        ("Change ticket approved by CAB / Change Manager", "Mandatory"),
        ("Release branch frozen — no further commits allowed", "Mandatory"),
        ("Full regression suite green on staging", "Mandatory"),
        ("Performance / load test passed", "Mandatory"),
        ("DB migration scripts tested and backed up", "Mandatory"),
        ("Feature flags configured for gradual rollout", "Conditional"),
        ("Monitoring dashboards & alert thresholds set", "Mandatory"),
        ("Rollback scripts prepared and tested in staging", "Mandatory"),
    ], hdr_hex=C_GREEN_H)

    _section(doc, "5. Deployment Steps")
    _make_table(doc,
        headers=["#", "Step", "Command / Action", "Expected Result", "Owner", "Time", "☐"],
        rows=[["1", "Notify stakeholders", "Send deployment start email", "Notification sent", "", "5 min", "☐"],
              ["2", "Enable maintenance mode", "", "", "", "2 min", "☐"],
              ["3", "Run DB migrations", "", "Exit code 0", "", "10 min", "☐"],
              ["4", "Deploy backend services", "", "Health ✓ 200 OK", "", "15 min", "☐"],
              ["5", "Deploy frontend bundle", "", "Assets served", "", "5 min", "☐"],
              ["6", "Smoke test (automated)", "", "All green", "", "10 min", "☐"],
              ["7", "Disable maintenance mode", "", "Site live", "", "1 min", "☐"],
              ["8", "Monitor for 30 min", "Watch dashboards", "No P1 alerts", "", "30 min", "☐"]],
        col_widths=[0.8, 3.5, 4.0, 3.0, 2.2, 1.8, 0.8])

    _section(doc, "6. Post-Deploy Verification")
    _checklist(doc, [
        ("Smoke tests (critical user journeys) pass", "Mandatory"),
        ("Error rate within normal baseline (≤ 0.1%)", "Mandatory"),
        ("Response times within SLA (p95 < 200 ms)", "Mandatory"),
        ("No new alerts triggered in first 30 minutes", "Mandatory"),
        ("Release notes published", "Mandatory"),
    ], hdr_hex=C_BLUE)

    _section(doc, "7. Go / No-Go Decision")
    _make_table(doc,
        headers=["Stakeholder", "Role", "Decision", "Notes"],
        rows=[["", "Release Manager", "☐ Go  ☐ No-Go", ""],
              ["", "Tech Lead", "☐ Go  ☐ No-Go", ""],
              ["", "Product Owner", "☐ Go  ☐ No-Go", ""]],
        col_widths=[4.0, 3.5, 3.5, 6.7])

    _section(doc, "8. Rollback Plan")
    _note_box(doc, "Trigger rollback if: P1 incident raised · Error rate > 1% · Core journey broken · Go-Live owner decision", icon="⚠")
    _make_table(doc,
        headers=["#", "Rollback Step", "Command / Action", "Owner", "☐"],
        rows=[["1", "Trigger rollback decision", "Declare rollback, notify stakeholders", "", "☐"],
              ["2", "Re-deploy previous artefact", "", "", "☐"],
              ["3", "Revert DB migrations (if any)", "", "", "☐"],
              ["4", "Verify system health post-rollback", "", "", "☐"],
              ["5", "Post-incident review scheduled", "Within 48 hours", "", "☐"]],
        col_widths=[0.8, 5.0, 5.5, 3.0, 0.8],
        hdr_hex=C_RED_H)

    _section(doc, "9. Key Contacts")
    _make_table(doc,
        headers=["Role", "Name", "Phone / Slack", "Escalation Level"],
        rows=[["Release Manager", "", "", "L1"],
              ["On-call Engineer", "", "", "L1"],
              ["Infrastructure Lead", "", "", "L2"],
              ["Product Owner", "", "", "L2"],
              ["Executive Sponsor", "", "", "L3"]],
        col_widths=[4.5, 4.0, 5.5, 3.2])

    _revision_table(doc)
    _save(doc, "Release_and_deployment_runbook_Template.docx")


# ═══════════════════════════════════════════════════════════════════
#  7. RISK REGISTER  (ISO 31000 aligned)
# ═══════════════════════════════════════════════════════════════════

def build_risk_register():
    doc = _new_doc()
    _header_block(doc, "Risk Register & Mitigation Plan",
                  "ISO 31000 Risk Management — Living Document",
                  [("Doc ID", "RISK-001"), ("Project", "<Project Name>"),
                   ("Version", "1.0"), ("Date", TODAY),
                   ("Risk Owner", "<Name>"), ("Status", "Active")])

    _section(doc, "1. Scoring Model")
    _note_box(doc,
              "Risk Score = Probability (1–5) × Impact (1–5).  "
              "Score 1–4 = Low (green) · 5–9 = Medium (amber) · 10–19 = High (red) · 20–25 = Critical (dark red)", icon="📊")

    # 5×5 Heat map as a table
    _subsection(doc, "Probability × Impact Matrix")
    impact_labels = ["1 Negligible", "2 Minor", "3 Moderate", "4 Major", "5 Critical"]
    prob_labels    = ["5 Almost Certain", "4 Likely", "3 Possible", "2 Unlikely", "1 Rare"]
    scores = [
        [5, 10, 15, 20, 25],
        [4, 8,  12, 16, 20],
        [3, 6,  9,  12, 15],
        [2, 4,  6,  8,  10],
        [1, 2,  3,  4,  5],
    ]
    color_map = {
        range(1, 5):   "27AE60",  # green
        range(5, 10):  "F39C12",  # amber
        range(10, 20): "E74C3C",  # red
        range(20, 26): "7B241C",  # dark red
    }
    def _risk_color(s):
        for r, c in color_map.items():
            if s in r: return c
        return "FFFFFF"

    tbl = doc.add_table(rows=6, cols=6)
    _table_outer_border(tbl, C_NAVY, 6)
    col_widths = [3.2, 2.9, 2.9, 2.9, 2.9, 2.9]
    for i, col in enumerate(tbl.columns):
        col.width = Cm(col_widths[i])

    # Corner cell
    _shade(tbl.rows[0].cells[0], C_NAVY)
    p = tbl.rows[0].cells[0].paragraphs[0]
    r = p.add_run("P ↓  |  I →")
    r.bold = True; r.font.size = Pt(8); r.font.color.rgb = RGB_WHITE; r.font.name = "Calibri"
    _no_space_before(p)

    for ci, lbl in enumerate(impact_labels):
        cell = tbl.rows[0].cells[ci+1]
        _shade(cell, C_NAVY)
        p = cell.paragraphs[0]
        run = p.add_run(lbl)
        run.bold = True; run.font.size = Pt(8); run.font.color.rgb = RGB_WHITE
        run.font.name = "Calibri"; _no_space_before(p)

    for ri, (prob_lbl, row_scores) in enumerate(zip(prob_labels, scores)):
        row = tbl.rows[ri+1]
        _shade(row.cells[0], C_NAVY)
        p = row.cells[0].paragraphs[0]
        run = p.add_run(prob_lbl)
        run.bold = True; run.font.size = Pt(8); run.font.color.rgb = RGB_WHITE
        run.font.name = "Calibri"; _no_space_before(p)
        for ci, score in enumerate(row_scores):
            cell = row.cells[ci+1]
            _shade(cell, _risk_color(score))
            p = cell.paragraphs[0]
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            run = p.add_run(str(score))
            run.bold = True; run.font.size = Pt(9)
            run.font.color.rgb = RGB_WHITE
            run.font.name = "Calibri"; _no_space_before(p)
    doc.add_paragraph()

    _section(doc, "2. Risk Register")
    _make_table(doc,
        headers=["ID", "Category", "Risk Description", "P", "I", "Score", "Rating",
                 "Owner", "Mitigation / Response", "Contingency", "Status"],
        rows=[["R-001", "Technical", "", "3", "4", "12", "High", "", "", "", "Open"],
              ["R-002", "Schedule", "", "4", "3", "12", "High", "", "", "", "Mitigating"],
              ["R-003", "Resource", "", "2", "3", "6",  "Med",  "", "", "", "Open"],
              ["R-004", "External", "", "2", "5", "10", "High", "", "", "", "Open"],
              ["R-005", "Compliance", "", "1", "5", "5", "Med", "", "", "", "Open"]],
        col_widths=[1.3, 2.2, 3.8, 0.6, 0.6, 1.0, 1.3, 2.0, 3.3, 0.0, 1.6],
        hdr_hex=C_RED_H)

    # override last col width (Status)
    _section(doc, "3. Risk Summary Dashboard")
    _make_table(doc,
        headers=["Rating", "Count", "Top Risk", "Trend"],
        rows=[["🔴 Critical", "0", "—", "→"],
              ["🔴 High", "", "", "↑"],
              ["🟡 Medium", "", "", "→"],
              ["🟢 Low", "", "", "↓"]],
        col_widths=[3.0, 2.0, 9.0, 3.2])

    _section(doc, "4. Risk Review Log")
    _make_table(doc,
        headers=["Review Date", "Reviewer", "Changes Made", "Next Review"],
        rows=[["", "", "Initial register created", ""],
              ["", "", "", ""]],
        col_widths=[3.0, 3.5, 7.5, 3.2])

    _revision_table(doc)
    _save(doc, "Risk_Register_and_Mitigation_Template.docx")


# ═══════════════════════════════════════════════════════════════════
#  8. SOP — STANDARD OPERATING PROCEDURE  (ITIL v4)
# ═══════════════════════════════════════════════════════════════════

def build_sop():
    doc = _new_doc()
    _header_block(doc, "Standard Operating Procedure (SOP)",
                  "ITIL v4 — Service Operations Reference",
                  [("Doc ID", "SOP-001"), ("Service", "<Service Name>"),
                   ("Version", "1.0"), ("Date", TODAY),
                   ("Owner", "<Service Owner>"), ("Status", "Active")])

    _section(doc, "1. Purpose & Scope")
    _field_table(doc, [
        ("Purpose", ""),
        ("In Scope", ""),
        ("Out of Scope", ""),
        ("Trigger / When to use", ""),
    ], cols=2)

    _section(doc, "2. Environments")
    _make_table(doc,
        headers=["Environment", "URL / Endpoint", "Region", "Access Level", "Owner", "Notes"],
        rows=[["Development", "", "", "Dev team", "", ""],
              ["Staging / UAT", "", "", "Dev + QA", "", ""],
              ["Production", "", "", "Ops + Release", "", ""]],
        col_widths=[2.5, 4.0, 2.0, 3.0, 2.5, 3.2])

    _section(doc, "3. Team Contacts & Escalation")
    _make_table(doc,
        headers=["Level", "Role", "Name", "Contact", "Escalate When"],
        rows=[["L1", "On-call Engineer", "", "", "Any P1/P2 alert"],
              ["L2", "Service Lead", "", "", "Unresolved after 30 min"],
              ["L3", "Engineering Manager", "", "", "Service-wide outage"],
              ["Vendor", "3rd Party Support", "", "", "External system failure"]],
        col_widths=[1.3, 3.5, 3.0, 4.0, 5.4])

    _section(doc, "4. Access & Credentials")
    _note_box(doc, "NEVER store passwords here. Reference the secrets vault / password manager.", icon="🔐")
    _make_table(doc,
        headers=["System / Service", "Access Method", "Secret Location", "MFA Required", "Owner"],
        rows=[["", "SSH Key", "Vault: <path>", "Yes", ""],
              ["", "API Key", "Vault: <path>", "No", ""],
              ["", "DB Connection", "Vault: <path>", "Yes", ""]],
        col_widths=[3.5, 3.0, 4.2, 2.5, 3.5],
        hdr_hex=C_ORANGE_H)

    _section(doc, "5. Deployment / Operation Procedure")
    _diagram_box(doc, "PROCESS FLOW DIAGRAM  —  Step-by-step operational flow with decision points", 4.5)
    _make_table(doc,
        headers=["Step", "Action", "Command / Tool", "Expected Output", "If Fails"],
        rows=[["1", "", "", "Success / Exit 0", ""],
              ["2", "", "", "", ""],
              ["3", "", "", "", ""],
              ["4", "", "", "", ""],
              ["5", "", "", "", ""],
              ["6", "Verify health", "GET /health", "HTTP 200 OK", "Escalate to L2"]],
        col_widths=[1.0, 3.5, 4.5, 3.7, 4.0])

    _section(doc, "6. Incident Response")
    _make_table(doc,
        headers=["Severity", "Definition", "Response SLA", "Notification", "Owner"],
        rows=[["P1 Critical", "Full service outage / data loss", "15 min", "Page all", "L3"],
              ["P2 High", "Major feature broken", "1 hr", "Slack + email", "L2"],
              ["P3 Medium", "Degraded performance", "4 hrs", "Slack", "L1"],
              ["P4 Low", "Minor cosmetic / single user", "Next sprint", "Ticket", "L1"]],
        col_widths=[2.2, 5.0, 2.5, 3.0, 2.0],
        hdr_hex=C_RED_H)

    _subsection(doc, "Incident Response Steps")
    _make_table(doc,
        headers=["#", "Step", "Action", "Owner", "☐"],
        rows=[["1", "Detect & Alert", "Alert fired / user report received", "On-call", "☐"],
              ["2", "Acknowledge", "Claim ticket, start incident channel", "L1 Eng", "☐"],
              ["3", "Diagnose", "Check logs, dashboards, recent deploys", "L1 Eng", "☐"],
              ["4", "Escalate", "If unresolved in SLA, escalate to L2", "L1 Eng", "☐"],
              ["5", "Mitigate", "Apply fix / rollback / workaround", "L2 Lead", "☐"],
              ["6", "Resolve", "Verify service restored, close incident", "Lead", "☐"],
              ["7", "Post-mortem", "Schedule PIR within 48 hrs (P1/P2 only)", "Manager", "☐"]],
        col_widths=[0.8, 3.0, 5.5, 3.0, 0.8])

    _section(doc, "7. Monitoring & Alerts")
    _make_table(doc,
        headers=["Metric", "Tool", "Normal Range", "Alert Threshold", "Dashboard Link"],
        rows=[["Error Rate", "", "< 0.1%", "> 1%", ""],
              ["Latency p95", "", "< 200 ms", "> 500 ms", ""],
              ["CPU Usage", "", "< 60%", "> 85%", ""],
              ["Memory", "", "< 70%", "> 90%", ""],
              ["Queue Depth", "", "< 100", "> 1000", ""]],
        col_widths=[3.0, 2.5, 3.0, 3.0, 5.2])

    _revision_table(doc)
    _save(doc, "SOP_Template.docx")


# ═══════════════════════════════════════════════════════════════════
#  9. SPRINT CEREMONY & RETROSPECTIVE LOG  (Scrum Guide)
# ═══════════════════════════════════════════════════════════════════

def build_sprint_log():
    doc = _new_doc()
    _header_block(doc, "Sprint Ceremony & Retrospective Log",
                  "Scrum Guide aligned — Sprint Record & Continuous Improvement",
                  [("Doc ID", "SPR-001"), ("Sprint #", "<N>"),
                   ("Team", "<Team Name>"), ("Date", TODAY),
                   ("Scrum Master", "<Name>"), ("Status", "Active")])

    _section(doc, "Sprint Summary")
    _field_table(doc, [
        ("Sprint Goal", ""),              ("Sprint #", ""),
        ("Start Date", ""),               ("End Date", ""),
        ("Team Capacity (pts)", ""),      ("Committed Points", ""),
        ("Velocity (prev avg)", ""),      ("Status at Close", "On Track / At Risk / Failed"),
    ], cols=4)

    _section(doc, "Sprint Planning")
    _subsection(doc, "Committed Backlog")
    _make_table(doc,
        headers=["Ticket", "User Story / Task", "Type", "Points", "Assignee", "Status"],
        rows=[["", "", "Story", "", "", "Done / Carried"],
              ["", "", "Story", "", "", ""],
              ["", "", "Bug", "", "", ""],
              ["", "", "Task", "", "", ""],
              ["", "", "", "", "TOTAL →", ""]],
        col_widths=[2.2, 6.0, 2.0, 1.8, 3.0, 2.7])

    _subsection(doc, "Carry-Over Items (from previous sprint)")
    _make_table(doc,
        headers=["Ticket", "Summary", "Reason Not Done", "Points", "Action"],
        rows=[["", "", "", "", "Re-commit / Deprioritise"],
              ["", "", "", "", ""]],
        col_widths=[2.2, 5.5, 4.5, 2.0, 3.5])

    _section(doc, "Sprint Review")
    _subsection(doc, "Demo Summary")
    _make_table(doc,
        headers=["Feature / Story", "Demo'd By", "Stakeholder Feedback", "Accepted?"],
        rows=[["", "", "", "☐ Yes  ☐ No"],
              ["", "", "", "☐ Yes  ☐ No"],
              ["", "", "", "☐ Yes  ☐ No"]],
        col_widths=[5.5, 3.0, 6.0, 2.7])

    _subsection(doc, "Bugs Found in Review")
    _make_table(doc,
        headers=["Bug ID", "Description", "Severity", "Sprint", "Owner"],
        rows=[["", "", "P2", "", ""],
              ["", "", "", "", ""]],
        col_widths=[2.0, 7.0, 2.0, 2.5, 3.7])

    _section(doc, "Retrospective")
    _note_box(doc, "Facilitator: keep to 60 min. Use anonymous input (e.g., Miro / Retrium) before grouping.", icon="🔁")
    tbl = doc.add_table(rows=2, cols=3)
    _table_outer_border(tbl, C_NAVY, 6)
    headers_retro = ["✅  Went Well", "⚠  To Improve", "🔧  Action Items"]
    colors_retro  = [C_GREEN_H, C_ORANGE_H, C_NAVY]
    for ci, (h, c) in enumerate(zip(headers_retro, colors_retro)):
        tbl.columns[ci].width = Cm(5.9)
        cell = tbl.rows[0].cells[ci]
        _shade(cell, c)
        p = cell.paragraphs[0]
        run = p.add_run(h)
        run.bold = True; run.font.size = Pt(9); run.font.color.rgb = RGB_WHITE
        run.font.name = "Calibri"; _no_space_before(p)
        content_cell = tbl.rows[1].cells[ci]
        _set_row_height(tbl.rows[1], 3.5)
        p2 = content_cell.paragraphs[0]
        run2 = p2.add_run("\n".join([f"▪  " for _ in range(5)]))
        run2.font.size = Pt(9); run2.font.name = "Calibri"; _no_space_before(p2)
    doc.add_paragraph()

    _subsection(doc, "Action Items (committed improvements)")
    _make_table(doc,
        headers=["#", "Action", "Owner", "Due By", "Status"],
        rows=[["1", "", "", "", "Open"],
              ["2", "", "", "", "Open"],
              ["3", "", "", "", "Open"]],
        col_widths=[0.8, 8.0, 3.0, 2.5, 2.9])

    _section(doc, "Sprint Metrics")
    _make_table(doc,
        headers=["Metric", "Planned", "Actual", "Notes"],
        rows=[["Story Points Committed", "", "", ""],
              ["Story Points Completed", "", "", ""],
              ["Carry-Over Points", "", "", ""],
              ["Bugs Found", "", "", ""],
              ["Bugs Fixed", "", "", ""],
              ["Team Capacity (days)", "", "", ""],
              ["Velocity Trend (3-sprint avg)", "", "", ""],
              ["Sprint Goal Met?", "", "Yes / No / Partial", ""]],
        col_widths=[6.0, 3.0, 3.0, 5.2])

    _section(doc, "Decisions & Agreements")
    _make_table(doc,
        headers=["#", "Decision / Agreement", "Made By", "Date"],
        rows=[["1", "", "", ""],
              ["2", "", "", ""]],
        col_widths=[0.8, 10.5, 3.7, 2.2])

    _revision_table(doc)
    _save(doc, "Sprint_Retro_Log_Template.docx")


# ═══════════════════════════════════════════════════════════════════
# 10. PROJECT EXPLANATION DOCUMENT  (New-Joiner / Onboarding Guide)
# ═══════════════════════════════════════════════════════════════════

def build_project_explanation():
    doc = _new_doc()
    _header_block(doc, "Project Explanation & Onboarding Guide",
                  "New-Joiner Reference · Codebase Walkthrough · Architecture · Run Guide",
                  [("Doc ID", "PROJ-EXP-001"), ("Project", "<Project Name>"),
                   ("Version", "1.0"), ("Date", TODAY),
                   ("Author", "<Name>"), ("Audience", "New Engineers / Stakeholders")])

    _note_box(doc,
        "PURPOSE: This document helps any new team member understand the project from Day 1 "
        "— what it does, how the code is organised, how to run it locally, and who to contact. "
        "Fill every section from the project's README, ARCHITECTURE docs, and codebase.",
        icon="📘")

    # ── 1. Project at a Glance ──────────────────────────────────────────
    _section(doc, "1. Project at a Glance")
    _field_table(doc, [
        ("Project Name",          ""),      ("Project Code / Repo",  ""),
        ("Business Purpose",      ""),      ("Primary Users",        ""),
        ("Tech Stack (summary)",  ""),      ("Deployment Target",    ""),
        ("GCP / Cloud Project",   ""),      ("Python / Runtime Ver", ""),
        ("Current Status",        ""),      ("License",              ""),
    ], cols=4)

    # ── 2. Why This Project Exists ──────────────────────────────────────
    _section(doc, "2. Why This Project Exists (Problem → Solution)")
    _note_box(doc, "Explain the business problem this project solves, the approach chosen, "
              "and what success looks like in 3–5 sentences.", icon="🎯")
    _make_table(doc,
        headers=["Business Problem", "Approach / Solution", "Success Metric / KPI"],
        rows=[["", "", ""], ["", "", ""]],
        col_widths=[5.9, 5.9, 5.9])

    # ── 3. System Architecture Overview ────────────────────────────────
    _section(doc, "3. System Architecture Overview")
    _note_box(doc, "High-level view of system modes (e.g. Frontend vs Batch), external integrations, "
              "and data flow. Replace diagram box with an actual architecture diagram.", icon="🏗")
    _diagram_box(doc, "HIGH-LEVEL SYSTEM ARCHITECTURE DIAGRAM  —  Modes · Components · External Services", 6.0)
    _make_table(doc,
        headers=["System Mode", "Description", "Entry Point", "Output"],
        rows=[["Frontend / API", "", "", ""],
              ["Batch Processing", "", "", ""],
              ["Admin / Config", "", "", ""]],
        col_widths=[3.5, 6.5, 4.0, 3.2])

    # ── 4. Data Processing Flow ─────────────────────────────────────────
    _section(doc, "4. End-to-End Data Processing Flow")
    _subsection(doc, "4.1  Frontend / Single-Document Flow")
    _make_table(doc,
        headers=["Step #", "What Happens", "Key Module / File", "Input", "Output"],
        rows=[
            ["1", "Document upload & validation", "", "PDF / Image", "Validated bytes"],
            ["2", "PDF compression (if needed)",  "", "Raw PDF", "Compressed PDF"],
            ["3", "OCR / receipt field extraction",    "", "PDF / Image", "merchant_id string list"],
            ["4", "AI model invocation",          "", "Doc + merchant_id context", "Raw JSON"],
            ["5", "Post-process & normalise",     "", "Raw JSON", "Clean dict"],
            ["6", "Write to data warehouse",      "", "Clean dict", "Table rows"],
            ["7", "Archive original to storage",  "", "Raw file", "GCS URI"],
            ["8", "Return API response",          "", "Clean dict", "JSON response"],
        ],
        col_widths=[1.5, 4.8, 4.2, 3.0, 3.7])

    _subsection(doc, "4.2  Batch Processing Flow")
    _make_table(doc,
        headers=["Step #", "Component", "What It Does", "Input", "Output", "Script / Entry"],
        rows=[
            ["1", "Download Files",    "", "GCS queue folder", "Local manifest", ""],
            ["2", "Generate JSONL",    "", "Raw files", "batch.jsonl", ""],
            ["3", "Call AI Model",     "", "batch.jsonl", "predictions.jsonl", ""],
            ["4", "Post-process",      "", "predictions.jsonl", "processed_data.csv", ""],
            ["5", "Generate Tables",  "", "processed_data.csv", "6 BQ tables", ""],
        ],
        col_widths=[1.5, 3.5, 4.0, 3.2, 3.2, 2.3])

    # ── 5. Codebase Structure ───────────────────────────────────────────
    _section(doc, "5. Codebase Structure — What Lives Where")
    _note_box(doc, "List the most important folders and files. "
              "'When to touch it' guides new engineers on where to make changes.", icon="📁")
    _make_table(doc,
        headers=["Folder / File", "What It Does", "Key Classes / Functions", "When To Touch It"],
        rows=[
            ["app.py",              "API gateway — routes, config, file validation",   "", "Add new endpoints"],
            ["src/ReceiptProcessor/",  "Core processing logic (single-doc mode)",          "", "Change extraction pipeline"],
            ["src/batchPrediction/","Batch processing orchestrator",                    "", "Modify batch behaviour"],
            ["shared/",             "Reusable modules (AI, DB, storage, config, merchant_id)", "", "Add/fix shared utilities"],
            ["pipeline/",          "Vertex AI pipeline YAML + compilation scripts",    "", "Update batch pipeline steps"],
            ["config/",            "YAML configuration (GCP IDs, prompts, logging)",   "", "Change env settings"],
            ["scripts/",           "One-off admin scripts (e.g. field comparison)",     "", "Add maintenance tasks"],
            ["docs/",              "All architecture & module-level documentation",    "", "Update architecture docs"],
            ["Dockerfile",         "Frontend container image definition",              "", "Change runtime/deps"],
            ["Dockerfile_batch",   "Batch container image definition",                 "", "Change batch runtime"],
            ["requirements.txt",   "Python package dependencies",                      "", "Add/remove packages"],
            ["AcmeReceipt-Infra/",  "Terraform IaC — GCP project, IAM, buckets, Cloud Run", "", "Infra changes"],
        ],
        col_widths=[4.2, 5.0, 4.2, 4.1])

    # ── 6. Key Concepts ─────────────────────────────────────────────────
    _section(doc, "6. Key Concepts Every New Joiner Must Know")
    _make_table(doc,
        headers=["Concept", "What It Is", "Why It Matters Here", "Where To Find Code / Docs"],
        rows=[
            ["merchant_id",              "Global Trade Item Number — numeric OCR scan on products",
             "Primary key linking all extracted data", "shared/field_extractor.py"],
            ["tesseract",            "Python OCR scan decoding library using zbar",
             "High-accuracy receipt field extraction from images/PDFs", "shared/field_extractor.py"],
            ["Gemini AI",         "Google's multimodal large language model",
             "Extracts structured fields from label images", "shared/gemini_caller.py"],
            ["BigQuery",          "Google's serverless cloud data warehouse",
             "Stores all normalised extracted data (6 tables)", "shared/db_bq_connector.py"],
            ["Cloud Storage",     "Google's object storage service (GCS)",
             "Archives raw label documents; staging for batch", "shared/gcs_connector.py"],
            ["Cloud Run",         "Serverless container execution platform (GCP)",
             "Hosts the FastAPI application in production", "AcmeReceipt-Infra/prod/main.tf"],
            ["Vertex AI",         "GCP's ML platform with managed pipeline execution",
             "Orchestrates 5-step batch prediction pipeline", "pipeline/"],
            ["Workload Identity",  "Keyless GCP auth via identity federation",
             "No service account keys stored anywhere", "GitHub Actions YAML"],
            ["Kubeflow Pipelines","Python SDK (kfp) for ML pipeline compilation + execution",
             "Defines and compiles the batch pipeline YAML", "pipeline/vertex_batch_prediction.py"],
            ["AppConfig",         "Pydantic BaseModel holding all runtime settings",
             "Single source of truth for env vars and app settings", "app.py"],
        ],
        col_widths=[3.0, 4.8, 4.5, 5.0])

    # ── 7. API Reference ─────────────────────────────────────────────────
    _section(doc, "7. API Endpoints Reference")
    _make_table(doc,
        headers=["Method", "Endpoint", "Purpose", "Request Payload", "Response"],
        rows=[
            ["POST", "/receipt",              "Main label extraction endpoint", "multipart/form-data: file", "JSON extracted fields"],
            ["POST", "/upload-pdf/",            "Web UI file upload",             "multipart/form-data: file", "task_id"],
            ["GET",  "/progress/{task_id}",     "Server-Sent Events progress stream", "—", "SSE stream"],
            ["GET",  "/results/{task_id}",      "Retrieve extraction results",    "—", "JSON results"],
            ["GET",  "/download-excel/{task_id}","Export results as Excel file",  "—", "XLSX file download"],
            ["GET",  "/health",                 "Health check",                   "—", "{status: ok}"],
            ["GET",  "/config",                 "Get current app configuration",  "—", "AppConfig JSON"],
            ["POST", "/config/reload",          "Reload config from env vars",    "—", "New AppConfig JSON"],
            ["GET",  "/docs",                   "Swagger UI (auto-generated)",    "—", "HTML"],
            ["GET",  "/redoc",                  "ReDoc API docs (auto-generated)","—", "HTML"],
        ],
        col_widths=[1.5, 4.2, 4.0, 4.0, 3.5])

    # ── 8. BigQuery Schema Overview ──────────────────────────────────────
    _section(doc, "8. Data Model — BigQuery Tables")
    _make_table(doc,
        headers=["Table", "Primary Key(s)", "Key Columns", "Populated By", "Notes"],
        rows=[
            ["product_table",         "article_id",    "brand_name, product_name, article_id",    "LabelProcessor", "One row per unique product"],
            ["merchant_id_table",            "merchant_id_number",   "merchant_id_number, net_content, article_id",    "LabelProcessor", "Links merchant_id → product"],
            ["label_fact",            "document_id",   "doc_id → product → merchant_id → country → detail", "LabelProcessor", "Central fact table"],
            ["product_details_table", "id_detail",     "All extracted label attributes",           "LabelProcessor", "Detailed attribute store"],
            ["country_table",         "country_id",    "country_name, country_code",              "LabelProcessor", "Dimension table"],
            ["document_table",        "document_id",   "gcs_uri, processing_status, load_date, file_size", "LabelProcessor", "Document audit trail"],
        ],
        col_widths=[3.8, 3.0, 4.5, 3.0, 2.9])

    # ── 9. How To Run Locally ─────────────────────────────────────────────
    _section(doc, "9. How To Run Locally (Developer Setup)")
    _make_table(doc,
        headers=["Step", "Action", "Command / Tool", "Expected Output", "Notes"],
        rows=[
            ["1", "Clone the repository",          "git clone <repo-url> && cd <project>", "Local copy", ""],
            ["2", "Create Python virtual env",     "python -m venv .venv && .venv/Scripts/activate", ".venv/ created", "Python 3.9 required"],
            ["3", "Install system dependencies",   "apt-get install libzbar0 poppler-utils (Linux)", "Packages installed", "Windows: install binaries manually"],
            ["4", "Install Python packages",       "pip install -r requirements.txt", "All packages installed", ""],
            ["5", "Set environment variables",     "cp .env.example .env  → edit values", ".env file ready", "See Section 10 for all vars"],
            ["6", "Authenticate with GCP",         "gcloud auth application-default login", "credentials.json", "Or use Workload Identity in CI"],
            ["7", "Start the FastAPI server",      "uvicorn app:app --host 0.0.0.0 --port 8080 --reload", "Server on :8080", ""],
            ["8", "Test the API",                  "curl http://localhost:8080/health", '{"status": "ok"}', ""],
            ["9", "Open Swagger UI",               "http://localhost:8080/docs", "API playground", ""],
        ],
        col_widths=[1.2, 3.5, 5.0, 3.5, 3.8])

    # ── 10. Env & Config Reference ───────────────────────────────────────
    _section(doc, "10. Environment & Configuration Reference")
    _make_table(doc,
        headers=["Variable / Config Key", "Description", "Example Value", "Required", "Source"],
        rows=[
            ["GCP_PROJECT_ID",          "GCP project identifier",              "acmereceipt-prod-01",        "Yes", ".env / Cloud Run env"],
            ["GCS_BUCKET_NAME",         "Google Cloud Storage bucket",         "acmereceipt-prod-bucket",                "Yes", ".env / Cloud Run env"],
            ["BIGQUERY_DATASET",        "BigQuery dataset name",               "acmereceipt_prod",                       "Yes", "config/configurations.yml"],
            ["GEMINI_MODEL",            "Gemini model ID",                     "gemini-1.5-flash-002",                  "Yes", "config/configurations.yml"],
            ["GOOGLE_APPLICATION_CREDENTIALS", "GCP service account key path (dev only)", "/path/to/key.json",         "Dev only", ".env (never commit)"],
            ["MAX_FILE_SIZE_MB",        "Max upload file size in MB",          "20",                                    "No", "AppConfig default"],
            ["ALLOWED_EXTENSIONS",      "Accepted file types",                 ".pdf,.png,.jpg,.jpeg,.tiff,.bmp",       "No", "AppConfig default"],
            ["PORT",                    "Server port",                         "8080",                                  "No", "AppConfig default"],
            ["config/prompts.yml",      "Gemini extraction prompts",           "— see file —",                          "Yes", "YAML config"],
            ["config/configurations.yml","GCP resource IDs per environment",  "— see file —",                          "Yes", "YAML config"],
        ],
        col_widths=[4.5, 4.0, 3.8, 2.0, 2.8])

    # ── 11. Infrastructure & IAM Overview ────────────────────────────────
    _section(doc, "11. Infrastructure & IAM Overview")
    _make_table(doc,
        headers=["GCP Resource", "Name / ID", "Purpose", "Managed By"],
        rows=[
            ["Cloud Run Service",        "",           "Hosts FastAPI application (prod + test)", "Terraform"],
            ["GCS Bucket (prod)",        "acmereceipt-prod-bucket",  "Label document archive + batch staging", "Terraform"],
            ["GCS Bucket (tf-state)",    "tf-state-acmereceipt-prod-01", "Terraform remote state", "Terraform"],
            ["BigQuery Dataset",         "",           "Stores all extracted label data (6 tables)", "Terraform"],
            ["Artifact Registry",        "",           "Docker image registry", "Terraform"],
            ["Vertex AI Pipeline",       "",           "Kubeflow batch prediction orchestration", "pipeline/ code"],
            ["App Service Account",      "acmereceipt-sa-prod@...iam.gserviceaccount.com", "Runtime GCP auth identity", "Terraform"],
            ["IAC Service Account",      "terraform-iac-pipeline@...iam.gserviceaccount.com", "CI/CD Terraform apply identity", "Terraform"],
            ["IAM Manager Group",        "platform.acmereceipt-prod-manager@example.com", "GCP governance & sign-off", "Platform Foundation"],
            ["IAM Developer Group",      "platform.acmereceipt-prod-developer@example.com", "Feature development access", "Platform Foundation"],
        ],
        col_widths=[4.0, 5.5, 5.0, 2.7])

    # ── 12. Contacts & Escalation ─────────────────────────────────────────
    _section(doc, "12. Contacts & Escalation")
    _make_table(doc,
        headers=["Role", "Name", "Slack / Email", "Escalate When"],
        rows=[
            ["Tech Lead / Architect",    "", "", "Architecture decisions, design questions"],
            ["Platform / Infra Engineer","", "", "GCP issues, Terraform, Cloud Run"],
            ["AI / ML Engineer",         "", "", "Gemini model issues, merchant_id accuracy problems"],
            ["Product Owner",            "", "", "Scope, priority, requirement questions"],
            ["Scrum Master / Lead",      "", "", "Process, sprint, team impediments"],
            ["GCP IAM Manager",          "Manager Group", "platform.acmereceipt-prod-manager@...", "IAM access, project governance"],
        ],
        col_widths=[4.0, 3.5, 5.5, 4.2])

    _revision_table(doc)
    _save(doc, "Project_Explanation_Template.docx")


# ═══════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════

def main():
    print("=" * 68)
    print("  PROFESSIONAL DOCUMENT TEMPLATE GENERATOR")
    print("  Research basis: arc42 · INVEST · Scrum Guide · ISO 31000 · ITIL v4")
    print("=" * 68)
    OUT_DIR.mkdir(exist_ok=True)

    builders = [
        ("Architecture & Design",                build_architecture),
        ("Codebase KB & Change Versioning",       build_codebase_kb),
        ("CPDD — Project Definition",             build_cpdd),
        ("Definition of Done (DoD)",              build_dod),
        ("Definition of Ready (DoR)",             build_dor),
        ("Release & Deployment Runbook",          build_runbook),
        ("Risk Register & Mitigation",            build_risk_register),
        ("SOP — Standard Operating Procedure",    build_sop),
        ("Sprint Ceremony & Retrospective Log",   build_sprint_log),
        ("Project Explanation — Onboarding Guide",build_project_explanation),
    ]

    ok = 0
    for name, fn in builders:
        try:
            fn()
            ok += 1
        except Exception as e:
            print(f"  ✗  FAILED: {name}  [{e}]")

    print("-" * 68)
    print(f"  Done — {ok}/{len(builders)} templates generated → {OUT_DIR.name}/")
    print("=" * 68)


if __name__ == "__main__":
    main()
