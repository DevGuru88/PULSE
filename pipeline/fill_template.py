"""
fill_template.py
================
Takes the structured LLM+RAG response and fills the matching DOCX template.

USAGE:
  # Programmatic (from your RAG pipeline):
      from fill_template import fill_document
      result_path = fill_document("cpdd", llm_response_string)

  # CLI:
      py fill_template.py --doc cpdd    --response response.txt
      py fill_template.py --doc all     --response_dir ./llm_outputs/
      py fill_template.py --doc runbook --text "--- SECTION: Release Details ---\\n  Release Version: 2.1.0 ..."

  # Demo (auto-generate fake response and fill all 9):
      py fill_template.py --demo

OUTPUT:
  Project_Documents/<DOCNAME>_Filled_<YYYYMMDD>.docx
"""

import re
import sys
import shutil
import argparse
from pathlib import Path
from datetime import date
from copy import deepcopy

from docx import Document
from docx.shared import Pt, RGBColor
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

# ─────────────────────────────────────────────────────────────────────────────
TEMPLATE_DIR = Path(__file__).parent / "Project_Templates_Slim"
OUTPUT_DIR   = Path(__file__).parent / "Project_Documents"
OUTPUT_DIR.mkdir(exist_ok=True)

TODAY = date.today().strftime("%d %b %Y")

TEMPLATE_FILES = {
    "architecture":       "Architecture_and_Design_Template.docx",
    "codebase_kb":        "Codebase_KB_Change_Versioning_Template.docx",
    "cpdd":               "CPDD_Template.docx",
    "dod":               "Defination_Of_Done_Template.docx",
    "dor":               "DOR_Template.docx",
    "runbook":           "Release_and_deployment_runbook_Template.docx",
    "risk_register":     "Risk_Register_and_Mitigation_Template.docx",
    "sop":               "SOP_Template.docx",
    "sprint_log":        "Sprint_Retro_Log_Template.docx",
    "project_explanation": "Project_Explanation_Template.docx",
}

OUTPUT_NAMES = {
    "architecture":       "Architecture_and_Design",
    "codebase_kb":        "Codebase_KB_Change_Versioning",
    "cpdd":               "CPDD",
    "dod":               "Definition_of_Done",
    "dor":               "Definition_of_Ready",
    "runbook":           "Release_Runbook",
    "risk_register":     "Risk_Register",
    "sop":               "SOP",
    "sprint_log":        "Sprint_Log",
    "project_explanation": "Project_Explanation_Onboarding_Guide",
}


# ══════════════════════════════════════════════════════════════════════════════
#  PART 1 — LLM RESPONSE PARSER
#  Converts the structured LLM output (from rag_prompts.py) into a Python dict
# ══════════════════════════════════════════════════════════════════════════════

def parse_llm_response(text: str) -> dict:
    """
    Parse structured LLM response into:
    {
      "section name": {
          "type":   "kv" | "table" | "bullets" | "text",
          "fields": {"Field Name": "value", ...}   # for kv
          "rows":   [{"col": "val", ...}, ...]     # for table/bullets
          "text":   "raw text"                     # for text
      },
      ...
    }
    """
    sections = {}
    current_section = None
    current_lines   = []

    # Split on section headers
    section_pattern = re.compile(
        r"^---\s*(?:SECTION|CONDITIONAL SECTION):\s*(.+?)\s*---\s*$",
        re.IGNORECASE
    )

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        m = section_pattern.match(line.strip())
        if m:
            if current_section is not None:
                sections[current_section] = _classify_lines(current_lines)
            current_section = m.group(1).strip().upper()
            current_lines = []
        else:
            if current_section is not None and line.strip():
                current_lines.append(line)

    if current_section is not None:
        sections[current_section] = _classify_lines(current_lines)

    return sections


def _clean_value(v: str) -> str:
    """Strip confidence tags, brackets, and empty markers."""
    v = v.strip()
    # Remove confidence tags: [✓ found], [~ inferred], [NA], [⚠ conflict: ...]
    v = re.sub(r'\[✓[^\]]*\]', '', v)
    v = re.sub(r'\[~[^\]]*\]', '', v)
    v = re.sub(r'\[NA[^\]]*\]', '', v)
    v = re.sub(r'\[⚠[^\]]*\]', '', v)
    v = v.strip()
    # Replace "NA (Not Available)" with cleaner form
    v = re.sub(r'NA\s*\(Not Available\)', 'N/A', v, flags=re.IGNORECASE)
    # Replace lone __ placeholders
    if v in ('__', '___', '____', '', '—'):
        return ''
    return v


def _classify_lines(lines: list) -> dict:
    """Determine if section content is kv, bullet-table, or plain text."""
    if not lines:
        return {"type": "text", "text": ""}

    kv_lines   = []
    bullet_rows = []
    text_lines  = []

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith('[') or stripped.startswith('('):
            continue  # skip comments/instructions

        # Bullet with pipe-separated fields:  "• Field: val | Field2: val2"
        if stripped.startswith('•') and '|' in stripped:
            row = {}
            parts = stripped.lstrip('•').split('|')
            for part in parts:
                if ':' in part:
                    k, _, v = part.partition(':')
                    row[k.strip()] = _clean_value(v)
                else:
                    row['_extra'] = row.get('_extra', '') + part.strip()
            if row:
                bullet_rows.append(row)

        # Plain bullet without pipes:  "• some text"
        elif stripped.startswith('•'):
            bullet_rows.append({'value': _clean_value(stripped.lstrip('•').strip())})

        # Key-value line:  "  Field Name:   value"
        elif ':' in stripped and not stripped.startswith('Step') and '|' not in stripped:
            k, _, v = stripped.partition(':')
            k = k.strip()
            v = _clean_value(v)
            # Skip instruction lines (they contain words like 'extract', 'from', etc.)
            if not any(w in k.lower() for w in ['format', 'extract', 'look for', 'source']):
                kv_lines.append((k, v))

        # Step line:  "Step 1:  Action: __ | Command: __ | ..."
        elif re.match(r'^Step\s*\d+', stripped):
            row = {'_step': stripped}
            parts = stripped.split('|')
            for part in parts:
                if ':' in part:
                    k, _, v = part.partition(':')
                    row[k.strip()] = _clean_value(v)
            bullet_rows.append(row)

        else:
            text_lines.append(stripped)

    # Decision: what is the dominant type?
    if bullet_rows and not kv_lines:
        return {"type": "bullets", "rows": bullet_rows}
    elif kv_lines and not bullet_rows:
        fields = {}
        for k, v in kv_lines:
            fields[k] = v
        return {"type": "kv", "fields": fields}
    elif kv_lines and bullet_rows:
        # Mixed — store both
        fields = {k: v for k, v in kv_lines}
        return {"type": "mixed", "fields": fields, "rows": bullet_rows}
    else:
        return {"type": "text", "text": '\n'.join(text_lines)}


# ══════════════════════════════════════════════════════════════════════════════
#  PART 2 — DOCX MANIPULATION HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _set_cell_text(cell, text: str, preserve_format: bool = True):
    """Set cell text while keeping the existing font style of first run."""
    if not text:
        return
    # Grab first paragraph's formatting
    para = cell.paragraphs[0]
    # Get existing style from first run (if any)
    font_size = Pt(9)
    font_name = "Calibri"
    bold      = False
    color     = None
    if para.runs:
        r0 = para.runs[0]
        font_size = r0.font.size or Pt(9)
        font_name = r0.font.name or "Calibri"
        bold      = r0.font.bold or False
        color     = r0.font.color.rgb if r0.font.color and r0.font.color.type else None

    # Clear all paragraphs in cell
    for p in cell.paragraphs:
        for run in p.runs:
            run.text = ''

    # Set the text
    run = para.add_run(text)
    run.font.size = font_size
    run.font.name = font_name
    run.font.bold = bold
    if color:
        run.font.color.rgb = color


def _find_cells_with_label(table, label: str):
    """
    Find all cells whose text matches label (case-insensitive).
    Returns list of (row_idx, col_idx).
    """
    label_clean = label.strip().lower()
    found = []
    for ri, row in enumerate(table.rows):
        for ci, cell in enumerate(row.cells):
            if cell.text.strip().lower() == label_clean:
                found.append((ri, ci))
    return found


def _fill_kv_table(table, fields: dict, skip_header_rows: int = 0):
    """
    Fill a label→value table.
    Handles 2-col [label | value] and 4-col [label | value | label | value] layouts.
    Matches field names from LLM response to cell labels.
    """
    ncols = len(table.columns)
    filled = 0

    for ri, row in enumerate(table.rows):
        if ri < skip_header_rows:
            continue
        cells = row.cells

        if ncols == 2:
            # [label][value]
            label_text = cells[0].text.strip()
            if label_text:
                match = _fuzzy_match(label_text, fields)
                if match:
                    _set_cell_text(cells[1], match)
                    filled += 1

        elif ncols == 4:
            # [label][value][label][value]
            for pair in [(0, 1), (2, 3)]:
                label_text = cells[pair[0]].text.strip()
                if label_text:
                    match = _fuzzy_match(label_text, fields)
                    if match:
                        _set_cell_text(cells[pair[1]], match)
                        filled += 1

    return filled


def _add_table_row(table, copy_style_from_row=None):
    """Append a new row to a table, optionally copying cell shading from a template row."""
    from docx.oxml import OxmlElement
    new_tr = OxmlElement('w:tr')
    tbl_el = table._tbl
    tbl_el.append(new_tr)
    # Build cells equal to number of columns
    n_cols = len(table.columns)
    for i in range(n_cols):
        tc = OxmlElement('w:tc')
        p  = OxmlElement('w:p')
        tc.append(p)
        new_tr.append(tc)
    # Force python-docx row cache refresh
    from docx.table import _Row
    row = _Row(new_tr, table)
    # Copy background shading from template row if provided
    if copy_style_from_row and i < len(copy_style_from_row.cells):
        for ci, cell in enumerate(row.cells):
            if ci < len(copy_style_from_row.cells):
                src_tc = copy_style_from_row.cells[ci]._tc
                src_pr = src_tc.find(OxmlElement('w:tcPr').tag)
                if src_pr is not None:
                    import copy as _copy
                    dst_tc = cell._tc
                    dst_pr = dst_tc.find(src_pr.tag)
                    if dst_pr is not None:
                        dst_tc.remove(dst_pr)
                    dst_tc.insert(0, _copy.deepcopy(src_pr))
    return row


def _fill_data_table(table, rows_data: list, start_row: int = 1, col_keys: list = None):
    """
    Fill a columnar data table.
    rows_data: list of dicts {col_header: value}
    col_keys:  if None, detect from table header row
    Automatically adds new rows when data exceeds the template's pre-built rows.
    """
    if not rows_data:
        return

    # Detect column keys from header row
    if col_keys is None:
        col_keys = [c.text.strip() for c in table.rows[0].cells]

    # Template row to copy style from when adding new rows
    last_template_row = table.rows[-1] if len(table.rows) > start_row else None

    for i, row_data in enumerate(rows_data):
        # Add new rows dynamically if we've run out of template rows
        if start_row + i >= len(table.rows):
            _add_table_row(table, copy_style_from_row=last_template_row)
        row = table.rows[start_row + i]
        for ci, key in enumerate(col_keys):
            if ci >= len(row.cells):
                break
            # Try exact key, then fuzzy
            val = row_data.get(key, '')
            if not val:
                val = _dict_fuzzy_match(key, row_data)
            if val:
                _set_cell_text(row.cells[ci], val)


def _fill_bullet_list_in_table(table, bullet_rows: list, data_start_row: int = 1):
    """Fill a data table from bullet rows (list of dicts)."""
    col_headers = [c.text.strip() for c in table.rows[0].cells]
    _fill_data_table(table, bullet_rows, start_row=data_start_row, col_keys=col_headers)


def _fuzzy_match(label: str, fields: dict) -> str:
    """Find a value in fields dict whose key best matches the label."""
    label_norm = _norm(label)
    # Exact
    for k, v in fields.items():
        if _norm(k) == label_norm:
            return v
    # Starts-with
    for k, v in fields.items():
        if label_norm.startswith(_norm(k)) or _norm(k).startswith(label_norm):
            return v
    # Substring match (label words in key)
    label_words = set(label_norm.split())
    best_score = 0
    best_val   = ''
    for k, v in fields.items():
        key_words = set(_norm(k).split())
        score = len(label_words & key_words)
        if score > best_score and score >= min(2, len(label_words)):
            best_score = score
            best_val   = v
    return best_val


def _dict_fuzzy_match(key: str, d: dict) -> str:
    key_norm = _norm(key)
    for k, v in d.items():
        if _norm(k) == key_norm:
            return str(v)
    for k, v in d.items():
        if key_norm in _norm(k) or _norm(k) in key_norm:
            return str(v)
    return ''


def _norm(s: str) -> str:
    return re.sub(r'[^a-z0-9 ]', '', s.lower()).strip()


def _update_header_block(table, fields: dict):
    """
    Update the document header block (Table 0) — the colored title + meta block.
    Meta block is in right cell, each paragraph is "Key: Value".
    """
    if len(table.rows) == 0:
        return
    right_cell = table.rows[0].cells[-1]
    for para in right_cell.paragraphs:
        text = para.text.strip()
        if ':' in text:
            key_part, _, val_part = text.partition(':')
            key_norm = _norm(key_part)
            new_val = _fuzzy_match(key_part.strip(), fields)
            if not new_val:
                # Try common header field aliases
                aliases = {
                    'doc id': fields.get('Doc ID', fields.get('Project Code', '')),
                    'project': fields.get('Project Name', fields.get('project', '')),
                    'version': fields.get('Version', '1.0'),
                    'date': fields.get('Date', TODAY),
                    'status': fields.get('Status', 'Draft'),
                    'author': fields.get('Author', fields.get('Architect', fields.get('PM', ''))),
                    'owner': fields.get('Owner', fields.get('PM', '')),
                    'sprint': fields.get('Sprint Number', fields.get('Sprint #', '')),
                    'team': fields.get('Team', ''),
                    'release': fields.get('Release Version', fields.get('Release', '')),
                    'env': fields.get('Environment', fields.get('Env', '')),
                    'service': fields.get('Service Name', fields.get('Service', '')),
                    'repo': fields.get('Repo URL', ''),
                }
                new_val = aliases.get(key_norm, '')

            if new_val:
                for run in para.runs:
                    run.text = ''
                run = para.add_run(f"{key_part.strip()}: {new_val}")
                run.font.size = Pt(8.5)
                run.font.name = "Calibri"


def _get_section(sections: dict, *aliases) -> dict:
    """Get section from parsed dict by any matching alias (case-insensitive)."""
    for alias in aliases:
        alias_norm = alias.upper()
        if alias_norm in sections:
            return sections[alias_norm]
        # Partial match
        for k in sections:
            if alias_norm in k or k in alias_norm:
                return sections[k]
    return {}


def _get_bullets(section: dict) -> list:
    if not section:
        return []
    if section.get('type') in ('bullets', 'mixed'):
        return section.get('rows', [])
    if section.get('type') == 'kv':
        # Convert kv to single-item bullet
        return [section.get('fields', {})]
    return []


def _get_fields(section: dict) -> dict:
    if not section:
        return {}
    if section.get('type') in ('kv', 'mixed'):
        return section.get('fields', {})
    return {}


def _section_to_text(section: dict) -> str:
    if not section:
        return ''
    if section.get('type') == 'text':
        return section.get('text', '')
    if section.get('type') == 'kv':
        return '\n'.join(f"{k}: {v}" for k, v in section.get('fields', {}).items())
    if section.get('type') in ('bullets', 'mixed'):
        lines = []
        for row in section.get('rows', []):
            v = row.get('value', '')
            if v:
                lines.append(f"• {v}")
            else:
                lines.append('• ' + ' | '.join(f"{k}: {v}" for k, v in row.items() if k != '_extra' and v))
        return '\n'.join(lines)
    return ''


def _overwrite_note_box(table, text: str):
    """Replace placeholder text inside a 1-col note_box table with actual content.
    Each newline-separated line becomes its own paragraph."""
    if not table.rows:
        return
    from docx.oxml import OxmlElement
    cell = table.rows[0].cells[0]
    tc = cell._tc

    # Remove all existing paragraphs from the cell XML
    for p_el in tc.findall('.//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p'):
        tc.remove(p_el)

    lines = [ln for ln in text.splitlines() if ln.strip()]
    for line in lines:
        p_el = OxmlElement('w:p')
        r_el = OxmlElement('w:r')
        rpr  = OxmlElement('w:rPr')
        sz   = OxmlElement('w:sz');   sz.set('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val', '170')
        szCs = OxmlElement('w:szCs'); szCs.set('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val','170')
        itl  = OxmlElement('w:i')
        rFonts = OxmlElement('w:rFonts')
        rFonts.set('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}ascii','Calibri')
        rFonts.set('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}hAnsi','Calibri')
        rpr.append(rFonts); rpr.append(sz); rpr.append(szCs); rpr.append(itl)
        t_el = OxmlElement('w:t')
        t_el.text = line
        t_el.set('{http://www.w3.org/XML/1998/namespace}space', 'preserve')
        r_el.append(rpr); r_el.append(t_el)
        p_el.append(r_el)
        tc.append(p_el)


def _overwrite_diagram_box(table, text: str):
    """Replace the placeholder inside a diagram_box 1-col table with text content.
    Each newline-separated line becomes its own paragraph so all lines are visible."""
    if not table.rows:
        return
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    cell = table.rows[0].cells[0]

    # Remove all existing paragraphs from the cell XML
    tc = cell._tc
    for p_el in tc.findall('.//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p'):
        tc.remove(p_el)

    # Add one paragraph per non-empty line
    lines = [ln for ln in text.splitlines() if ln.strip()]
    first = True
    for line in lines:
        p_el = OxmlElement('w:p')
        r_el = OxmlElement('w:r')
        rpr  = OxmlElement('w:rPr')
        # font size 8pt = 160 half-points
        sz = OxmlElement('w:sz');  sz.set('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val', '160')
        szCs=OxmlElement('w:szCs'); szCs.set('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val','160')
        rFonts=OxmlElement('w:rFonts')
        rFonts.set('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}ascii','Calibri')
        rFonts.set('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}hAnsi','Calibri')
        rpr.append(rFonts); rpr.append(sz); rpr.append(szCs)
        t_el = OxmlElement('w:t')
        t_el.text = line
        t_el.set('{http://www.w3.org/XML/1998/namespace}space', 'preserve')
        r_el.append(rpr); r_el.append(t_el)
        p_el.append(r_el)
        tc.append(p_el)


# ══════════════════════════════════════════════════════════════════════════════
#  PART 3 — DOCUMENT-SPECIFIC FILL FUNCTIONS
#  Each function knows its template's table layout and fills accordingly
# ══════════════════════════════════════════════════════════════════════════════

def _fill_architecture(doc: Document, sections: dict, stats: dict):
    tables = doc.tables
    # Template table order (generate_templates.py build_architecture):
    # T0:  header_block (2-col)
    # T1:  note_box  — Purpose & Scope                (1-col)
    # T2:  note_box  — System Context actors          (1-col)
    # T3:  diagram_box — SYSTEM CONTEXT DIAGRAM       (1-col placeholder)
    # T4:  make_table — Tech Stack                    [Layer | Technology / Framework | Version | Justification]
    # T5:  diagram_box — COMPONENT / CONTAINER DIAGRAM(1-col placeholder)
    # T6:  make_table — Component Architecture        [Component | Responsibility | Technology | Exposes / Consumes]
    # T7:  diagram_box — SEQUENCE / FLOW DIAGRAM      (1-col — filled with text flow)
    # T8:  note_box  — Error / Edge Cases             (1-col — filled with scenarios)
    # T9:  make_table — ADRs                          [ADR # | Decision | Alternatives | Rationale | Status]
    # T10: make_table — NFRs                          [Category | Requirement | Target / SLA | Measure | Priority]
    # T11: revision_table

    # Header block
    ctx = _get_fields(_get_section(sections, "PROJECT CONTEXT (DETECTED)"))
    if ctx:
        _update_header_block(tables[0], ctx)

    # T1: Purpose & Scope note_box — overwrite placeholder with actual scope text
    purpose_sec = _get_section(sections, "PURPOSE & SCOPE")
    if purpose_sec and len(tables) > 1:
        purpose_text = _section_to_text(purpose_sec)
        if purpose_text:
            _overwrite_note_box(tables[1], purpose_text)

    # T2: System Context note_box — list external actors
    actor_sec = _get_section(sections, "EXTERNAL ACTORS & INTEGRATIONS", "ACTORS & INTEGRATIONS")
    if actor_sec and len(tables) > 2:
        actor_text = _section_to_text(actor_sec)
        if actor_text:
            _overwrite_note_box(tables[2], actor_text)

    # T4: Technology stack  [Layer | Technology / Framework | Version | Justification]
    tech_sec = _get_section(sections, "TECHNOLOGY STACK")
    if tech_sec and len(tables) > 4:
        bullets = _get_bullets(tech_sec)
        if bullets:
            _fill_data_table(tables[4], bullets, start_row=1,
                             col_keys=["Layer", "Technology / Framework", "Version", "Justification"])
        stats['tech_stack'] = 'filled' if bullets else 'skipped'

    # T6: Components  [Component | Responsibility | Technology | Exposes / Consumes]
    comp_sec = _get_section(sections, "COMPONENT ARCHITECTURE", "COMPONENTS")
    if comp_sec and len(tables) > 6:
        bullets = _get_bullets(comp_sec)
        _fill_data_table(tables[6], bullets, start_row=1,
                         col_keys=["Component", "Responsibility", "Technology", "Exposes / Consumes"])
        stats['components'] = f'{len(bullets)} components'

    # T7: Flow diagram box — fill with the step-by-step interaction flows as text
    flow_sec = _get_section(sections, "KEY INTERACTION FLOWS", "INTERACTION FLOWS", "KEY FLOWS")
    if flow_sec and len(tables) > 7:
        flow_text = _section_to_text(flow_sec)
        if flow_text:
            _overwrite_diagram_box(tables[7], flow_text)
            stats['flow'] = 'filled'

    # T8: Error / Edge Cases note_box
    err_sec = _get_section(sections, "ERROR & EDGE CASES", "ERROR CASES", "EDGE CASES")
    if err_sec and len(tables) > 8:
        err_text = _section_to_text(err_sec)
        if err_text:
            _overwrite_note_box(tables[8], err_text)
            stats['errors'] = 'filled'

    # T9: ADRs  [ADR # | Decision | Alternatives Considered | Rationale | Status]
    adr_sec = _get_section(sections, "ARCHITECTURE DECISION RECORDS")
    if adr_sec and len(tables) > 9:
        bullets = _get_bullets(adr_sec)
        _fill_data_table(tables[9], bullets, start_row=1,
                         col_keys=["ADR #", "Decision", "Alternatives Considered", "Rationale", "Status"])
        stats['adrs'] = f'{len(bullets)} ADRs'

    # T10: NFRs  [Category | Requirement | Target / SLA | Measure | Priority]
    nfr_sec = _get_section(sections, "NON-FUNCTIONAL REQUIREMENTS", "NFRS")
    if nfr_sec and len(tables) > 10:
        bullets = _get_bullets(nfr_sec)
        _fill_data_table(tables[10], bullets, start_row=1,
                         col_keys=["Category", "Requirement", "Target / SLA", "Measure", "Priority"])
        stats['nfrs'] = f'{len(bullets)} NFRs'

    # Revision table (last table in doc)
    rev_fields = {"Author": ctx.get("Author", ctx.get("Architect", "")), "Date": TODAY}
    rev_table = tables[-1]
    _fill_kv_table(rev_table, rev_fields, skip_header_rows=1)


def _fill_codebase_kb(doc: Document, sections: dict, stats: dict):
    tables = doc.tables

    # Header
    repo_fields = _get_fields(_get_section(sections, "REPOSITORY DETAILS"))
    _update_header_block(tables[0], repo_fields)

    # T1: Repo details (4-col kv)
    if repo_fields:
        _fill_kv_table(tables[1], repo_fields, skip_header_rows=0)
        stats['repo_details'] = 'filled'

    # T2: Branching strategy
    branch_sec = _get_section(sections, "BRANCHING STRATEGY")
    if branch_sec:
        bullets = _get_bullets(branch_sec)
        _fill_data_table(tables[2], bullets, start_row=1,
                         col_keys=["Branch", "Purpose", "Naming Convention", "Merge Policy"])

    # T3: Change log
    changelog = _get_section(sections, "CHANGE LOG", "CHANGELOG")
    if changelog:
        bullets = _get_bullets(changelog)
        _fill_data_table(tables[3], bullets, start_row=1,
                         col_keys=["Date", "Version", "PR / Commit", "Author", "Type", "Summary", "Breaking?"])

    # T4: ADRs
    adr_sec = _get_section(sections, "ARCHITECTURE DECISION RECORDS", "ADRS")
    if adr_sec:
        bullets = _get_bullets(adr_sec)
        _fill_data_table(tables[4], bullets, start_row=1,
                         col_keys=["ADR #", "Date", "Title", "Status", "Supersedes"])

    # T5: Dependency registry
    dep_sec = _get_section(sections, "DEPENDENCY REGISTRY", "DEPENDENCIES")
    if dep_sec:
        bullets = _get_bullets(dep_sec)
        _fill_data_table(tables[5], bullets, start_row=1,
                         col_keys=["Package", "Version", "License", "Direct / Transitive", "Risk", "Last Reviewed"])

    # T6: Tech debt
    debt_sec = _get_section(sections, "TECHNICAL DEBT", "TECH DEBT REGISTER")
    if debt_sec:
        bullets = _get_bullets(debt_sec)
        _fill_data_table(tables[6], bullets, start_row=1,
                         col_keys=["ID", "Description", "Component", "Severity", "Effort", "Target Sprint", "Owner"])


def _fill_cpdd(doc: Document, sections: dict, stats: dict):
    tables = doc.tables

    # Header
    identity = _get_fields(_get_section(sections, "PROJECT IDENTITY"))
    _update_header_block(tables[0], identity)

    # T1: Project identity (4-col kv)
    if identity:
        _fill_kv_table(tables[1], identity)
        stats['identity'] = 'filled'

    # T2: Problem & objectives
    prob_sec = _get_section(sections, "BUSINESS PROBLEM", "PROBLEM STATEMENT", "OBJECTIVES")
    if prob_sec:
        bullets = _get_bullets(prob_sec)
        _fill_data_table(tables[2], bullets, start_row=1,
                         col_keys=["Business Problem", "Desired Outcome", "Success Metric"])

    # T3: Stakeholders
    stake_sec = _get_section(sections, "STAKEHOLDERS")
    if stake_sec:
        bullets = _get_bullets(stake_sec)
        _fill_data_table(tables[3], bullets, start_row=1,
                         col_keys=["Name", "Role", "Department", "Responsibility", "Decision Authority"])

    # T4: Scope — dual column table
    scope_in  = _get_section(sections, "SCOPE -- IN", "IN SCOPE", "SCOPE - IN")
    scope_out = _get_section(sections, "SCOPE -- OUT OF SCOPE", "OUT OF SCOPE", "SCOPE - OUT")
    if (scope_in or scope_out) and len(tables) > 4:
        t = tables[4]
        in_bullets  = _get_bullets(scope_in)
        out_bullets = _get_bullets(scope_out)
        max_rows = min(len(t.rows) - 1, max(len(in_bullets), len(out_bullets), 1))
        for i in range(max_rows):
            row = t.rows[i + 1]
            if i < len(in_bullets):
                v = in_bullets[i].get('value', '') or _section_to_text({'type': 'kv', 'fields': in_bullets[i]})
                _set_cell_text(row.cells[0], f"▪  {v}")
            if i < len(out_bullets):
                v = out_bullets[i].get('value', '') or _section_to_text({'type': 'kv', 'fields': out_bullets[i]})
                _set_cell_text(row.cells[1], f"▪  {v}")

    # T5: Milestones
    mile_sec = _get_section(sections, "DELIVERABLES", "MILESTONES", "DELIVERABLES & MILESTONES")
    if mile_sec and len(tables) > 5:
        bullets = _get_bullets(mile_sec)
        _fill_data_table(tables[5], bullets, start_row=1,
                         col_keys=["Milestone", "Deliverable", "Owner", "Target Date", "Status"])

    # T6: Assumptions & Constraints — merge both sections into one table
    assume_sec = _get_section(sections, "ASSUMPTIONS", "ASSUMPTIONS & CONSTRAINTS")
    const_sec  = _get_section(sections, "CONSTRAINTS")
    assume_bullets = _get_bullets(assume_sec)
    const_bullets  = _get_bullets(const_sec)
    # Tag type if not already present
    for b in assume_bullets:
        if not b.get('Type') and not b.get('type'):
            b['Type'] = 'Assumption'
    for b in const_bullets:
        if not b.get('Type') and not b.get('type'):
            b['Type'] = 'Constraint'
    merged = assume_bullets + const_bullets
    if merged and len(tables) > 6:
        _fill_data_table(tables[6], merged, start_row=1,
                         col_keys=["Type", "Description", "Impact if Wrong / Violated"])

    # T7: Risks
    risk_sec = _get_section(sections, "TOP RISKS", "RISKS SUMMARY")
    if risk_sec and len(tables) > 7:
        bullets = _get_bullets(risk_sec)
        _fill_data_table(tables[7], bullets, start_row=1,
                         col_keys=["Risk", "Probability", "Impact", "Score", "Owner", "Mitigation"])

    # T8: Approvals
    approval_sec = _get_section(sections, "APPROVALS", "SIGN-OFF", "APPROVAL & SIGN-OFF", "APPROVER ROLES")
    if approval_sec and len(tables) > 8:
        bullets = _get_bullets(approval_sec)
        _fill_data_table(tables[8], bullets, start_row=1,
                         col_keys=["Role", "Name", "Signature", "Date"])


def _fill_dod(doc: Document, sections: dict, stats: dict):
    tables = doc.tables
    # T0 = header, T1 = DoD levels overview (diagram placeholder)
    # T2 = Story checklist, T3 = Sprint checklist, T4 = Release checklist, T5 = Sign-off

    # Header
    ctx = _get_fields(_get_section(sections, "PROJECT CONTEXT (DETECTED)"))
    _update_header_block(tables[0], ctx)

    # Validation section — update checklist items where project values differ
    validation = _get_fields(_get_section(sections, "DEFAULT CRITERIA VALIDATION", "VALIDATION"))
    additions  = _get_bullets(_get_section(sections, "STORY-LEVEL DOD", "PROJECT-SPECIFIC STORY"))
    ci_gates   = _get_bullets(_get_section(sections, "CI/CD QUALITY GATES", "CI/CD GATES"))
    sprint_add = _get_bullets(_get_section(sections, "SPRINT-LEVEL DOD", "SPRINT DOD ADDITIONS"))
    release_add= _get_bullets(_get_section(sections, "RELEASE-LEVEL DOD", "RELEASE DOD ADDITIONS"))
    sign_off   = _get_fields(_get_section(sections, "SIGN-OFF REQUIREMENTS", "SIGN-OFF ROLES"))
    gaps       = _get_bullets(_get_section(sections, "DOD COMPLIANCE GAPS", "DOD GAPS"))

    # Fill Sign-off table (last meaningful table before revision)
    if sign_off and len(tables) > 5:
        for ti in range(len(tables)-1, 0, -1):
            t = tables[ti]
            if t.rows[0].cells[0].text.strip().lower() == 'role':
                bullets = [
                    {"Role": "Scrum Master",  "Name": sign_off.get("Story sign-off by", ""), "Date": TODAY},
                    {"Role": "Product Owner", "Name": sign_off.get("Release sign-off by", ""), "Date": TODAY},
                ]
                _fill_data_table(t, bullets, start_row=1,
                                 col_keys=["Role", "Name", "Sign-off", "Date"])
                break

    stats['dod_validation'] = 'filled' if validation else 'NA'
    stats['dod_gaps'] = f"{len(gaps)} gaps found" if gaps else 'none'


def _fill_dor(doc: Document, sections: dict, stats: dict):
    tables = doc.tables

    ctx = _get_fields(_get_section(sections, "PROJECT CONTEXT (DETECTED)"))
    _update_header_block(tables[0], ctx)

    # T1: INVEST table  — fill the "What it means" column
    invest_sec = _get_section(sections, "INVEST COMPLIANCE CHECK", "INVEST")
    invest_fields = _get_fields(invest_sec) if invest_sec else {}

    if invest_fields and len(tables) > 1:
        t = tables[1]
        invest_map = {'I': 'Independent', 'N': 'Negotiable', 'V': 'Valuable',
                      'E': 'Estimable',   'S': 'Small',      'T': 'Testable'}
        for ri in range(1, len(t.rows)):
            letter_cell = t.rows[ri].cells[0].text.strip()
            if letter_cell in invest_map:
                val = invest_fields.get(invest_map[letter_cell], '')
                if val:
                    _set_cell_text(t.rows[ri].cells[2], val)

    # T2: DoR Criteria checklist (fill "Category" and "Verified By")
    dor_items = _get_bullets(_get_section(sections, "WORK ITEM FORMAT", "MANDATORY JIRA FIELDS",
                                          "PROJECT-SPECIFIC DOR ADDITIONS"))
    if dor_items and len(tables) > 2:
        _fill_data_table(tables[2], dor_items, start_row=1,
                         col_keys=["#", "Criteria", "Priority", "Owner", "☐ Done"])

    # T3: Readiness scorecard – fill "Score" column values
    score_sec = _get_fields(_get_section(sections, "READINESS GATE", "READINESS SCORECARD THRESHOLD"))
    if score_sec and len(tables) > 3:
        _fill_kv_table(tables[3], score_sec)

    # T5: Sign-off
    sign_sec = _get_fields(_get_section(sections, "SIGN-OFF REQUIREMENTS", "SIGN-OFF"))
    if sign_sec and len(tables) > 4:
        for ti in range(len(tables)-1, 0, -1):
            t = tables[ti]
            if t.rows[0].cells[0].text.strip().lower() == 'role':
                _fill_kv_table(t, sign_sec)
                break

    stats['dor_items'] = f"{len(dor_items)} items"


def _fill_runbook(doc: Document, sections: dict, stats: dict):
    tables = doc.tables

    release_fields = _get_fields(_get_section(sections, "RELEASE IDENTITY", "RELEASE DETAILS"))
    _update_header_block(tables[0], release_fields)

    # T1: Release Identity (4-col kv)
    if release_fields and len(tables) > 1:
        _fill_kv_table(tables[1], release_fields)
        stats['release_fields'] = 'filled'

    # T2: Changes included
    changes = _get_bullets(_get_section(sections, "CHANGES INCLUDED", "INCLUDED CHANGES"))
    if changes and len(tables) > 2:
        _fill_data_table(tables[2], changes, start_row=1,
                         col_keys=["Ticket", "Type", "Summary", "Risk", "Test Evidence"])

    # T3: Pre-release checklist
    pre = _get_bullets(_get_section(sections, "PRE-RELEASE CHECKLIST", "PRE RELEASE"))
    if pre and len(tables) > 4:
        _fill_data_table(tables[4], pre, start_row=1,
                         col_keys=["#", "Criterion", "Category", "Verified By", "☐ Done"])

    # T4: Deployment steps
    steps = _get_bullets(_get_section(sections, "DEPLOYMENT PIPELINE", "DEPLOYMENT STEPS"))
    if steps and len(tables) > 3:
        _fill_data_table(tables[3], steps, start_row=1,
                         col_keys=["#", "Step", "Command / Action", "Expected Result", "Owner", "Time", "☐"])

    # Rollback table
    rollback = _get_bullets(_get_section(sections, "ROLLBACK PLAN", "ROLLBACK PROCEDURE"))
    # Find rollback table by header
    for t in tables:
        if t.rows and 'rollback' in t.rows[0].cells[0].text.lower():
            _fill_data_table(t, rollback, start_row=1,
                             col_keys=["#", "Rollback Step", "Command / Action", "Owner", "☐"])
            break

    # Contacts
    contacts = _get_bullets(_get_section(sections, "KEY CONTACTS", "CONTACTS"))
    for t in tables:
        if t.rows and 'role' in t.rows[0].cells[0].text.lower() and 'contact' in ' '.join(
                c.text.lower() for c in t.rows[0].cells):
            _fill_data_table(t, contacts, start_row=1,
                             col_keys=["Role", "Name", "Phone / Slack", "Escalation Level"])
            break

    stats['steps'] = f"{len(steps)} deployment steps"
    stats['rollback'] = f"{len(rollback)} rollback steps"


def _fill_risk_register(doc: Document, sections: dict, stats: dict):
    tables = doc.tables

    summary_fields = _get_fields(_get_section(sections, "RISK SUMMARY DASHBOARD", "RISK SUMMARY"))
    _update_header_block(tables[0], {"Version": "1.0", "Date": TODAY})

    # Find the main risk register table — header row has "ID" in cell[0]
    # and "Category" in cell[1]; has 8+ columns.  (The heatmap has 6, dashboard 4.)
    risk_table = None
    for t in tables:
        if len(t.columns) >= 8 and t.rows:
            h0 = t.rows[0].cells[0].text.strip().lower()
            h1 = t.rows[0].cells[1].text.strip().lower() if len(t.rows[0].cells) > 1 else ''
            if h0 == 'id' and 'cat' in h1:
                risk_table = t
                break

    if risk_table:
        risks = _get_bullets(_get_section(sections, "RISK REGISTER"))
        if risks:
            # Map LLM field names to template columns
            col_map = {
                0: ["ID", "Risk ID"],
                1: ["Category"],
                2: ["Risk Description", "Description"],
                3: ["P", "Probability"],
                4: ["I", "Impact"],
                5: ["Score"],
                6: ["Rating"],
                7: ["Owner"],
                8: ["Mitigation", "Mitigation / Response"],
                9: ["Contingency"],
                10:["Status"],
            }
            col_headers = [c.text.strip() for c in risk_table.rows[0].cells]
            for ri, risk_data in enumerate(risks[:len(risk_table.rows) - 1]):
                row = risk_table.rows[ri + 1]
                for ci, cell in enumerate(row.cells):
                    if ci < len(col_headers):
                        keys_to_try = col_map.get(ci, [col_headers[ci]])
                        for key in keys_to_try:
                            val = _dict_fuzzy_match(key, risk_data)
                            if val:
                                _set_cell_text(cell, val)
                                break
            stats['risks'] = f"{len(risks)} risks"

    # Dashboard table
    if summary_fields:
        for t in tables:
            if t.rows and 'rating' in t.rows[0].cells[0].text.lower():
                _fill_kv_table(t, summary_fields)
                break


def _fill_sop(doc: Document, sections: dict, stats: dict):
    tables = doc.tables

    service_fields = _get_fields(_get_section(sections, "SERVICE IDENTITY", "SERVICE OVERVIEW"))
    _update_header_block(tables[0], service_fields)

    # T1: Environments
    envs = _get_bullets(_get_section(sections, "ENVIRONMENTS"))
    if envs and len(tables) > 1:
        _fill_data_table(tables[1], envs, start_row=1,
                         col_keys=["Environment", "URL / Endpoint", "Region", "Access Level", "Owner", "Notes"])

    # T2: Escalation matrix
    contacts = _get_bullets(_get_section(sections, "TEAM CONTACTS", "ESCALATION MATRIX", "ESCALATION"))
    if contacts and len(tables) > 2:
        _fill_data_table(tables[2], contacts, start_row=1,
                         col_keys=["Level", "Role", "Name", "Contact", "Escalate When"])

    # T3: Access & credentials
    access = _get_bullets(_get_section(sections, "ACCESS & CREDENTIALS", "ACCESS"))
    if access and len(tables) > 3:
        _fill_data_table(tables[3], access, start_row=1,
                         col_keys=["System / Service", "Access Method", "Secret Location", "MFA Required", "Owner"])

    # T4: Deployment steps
    steps = _get_bullets(_get_section(sections, "DEPLOYMENT PROCEDURE", "OPERATIONAL STEPS"))
    if steps and len(tables) > 4:
        _fill_data_table(tables[4], steps, start_row=1,
                         col_keys=["Step", "Action", "Command / Tool", "Expected Output", "If Fails"])

    # T5: Incident severity
    incidents = _get_bullets(_get_section(sections, "INCIDENT SEVERITY MODEL", "INCIDENT RESPONSE"))
    if incidents and len(tables) > 5:
        _fill_data_table(tables[5], incidents, start_row=1,
                         col_keys=["Severity", "Definition", "Response SLA", "Notification", "Owner"])

    # T6: Monitoring
    monitors = _get_bullets(_get_section(sections, "MONITORING & OBSERVABILITY", "MONITORING & ALERTS"))
    if monitors and len(tables) > 6:
        _fill_data_table(tables[6], monitors, start_row=1,
                         col_keys=["Metric", "Tool", "Normal Range", "Alert Threshold", "Dashboard Link"])

    stats['envs'] = len(envs)
    stats['monitors'] = len(monitors)


def _fill_sprint_log(doc: Document, sections: dict, stats: dict):
    tables = doc.tables

    summary_fields = _get_fields(_get_section(sections, "ITERATION SUMMARY", "SPRINT SUMMARY"))
    _update_header_block(tables[0], summary_fields)

    # T1: Sprint summary (4-col kv)
    if summary_fields and len(tables) > 1:
        _fill_kv_table(tables[1], summary_fields)

    # T2: Committed backlog
    backlog = _get_bullets(_get_section(sections, "COMMITTED WORK ITEMS", "COMMITTED BACKLOG"))
    if backlog and len(tables) > 2:
        _fill_data_table(tables[2], backlog, start_row=1,
                         col_keys=["Ticket", "User Story / Task", "Type", "Points", "Assignee", "Status"])

    # T3: Carry-over
    carryover = _get_bullets(_get_section(sections, "CARRY-OVER", "CARRY OVER"))
    if carryover and len(tables) > 3:
        _fill_data_table(tables[3], carryover, start_row=1,
                         col_keys=["Ticket", "Summary", "Reason Not Done", "Points", "Action"])

    # T4: Demo summary
    demo = _get_bullets(_get_section(sections, "SPRINT REVIEW", "DEMO"))
    if demo and len(tables) > 4:
        _fill_data_table(tables[4], demo, start_row=1,
                         col_keys=["Feature / Story", "Demo'd By", "Stakeholder Feedback", "Accepted?"])

    # T5: Bugs
    bugs = _get_bullets(_get_section(sections, "BUGS RAISED", "BUGS"))
    if bugs and len(tables) > 5:
        _fill_data_table(tables[5], bugs, start_row=1,
                         col_keys=["Bug ID", "Description", "Severity", "Sprint", "Owner"])

    # T6: Action items
    actions = _get_bullets(_get_section(sections, "ACTION ITEMS", "RETROSPECTIVE"))
    if actions and len(tables) > 6:
        _fill_data_table(tables[6], actions, start_row=1,
                         col_keys=["#", "Action", "Owner", "Due By", "Status"])

    # T7: Metrics
    metrics = _get_fields(_get_section(sections, "SPRINT METRICS", "ITERATION METRICS"))
    if metrics and len(tables) > 7:
        _fill_kv_table(tables[7], metrics)

    # T8: Decisions
    decisions = _get_bullets(_get_section(sections, "DECISIONS", "DECISIONS & AGREEMENTS"))
    if decisions and len(tables) > 8:
        _fill_data_table(tables[8], decisions, start_row=1,
                         col_keys=["#", "Decision / Agreement", "Made By", "Date"])

    stats['backlog_items'] = len(backlog)
    stats['action_items'] = len(actions)


def _fill_project_explanation(doc: Document, sections: dict, stats: dict):
    """
    Fill Project Explanation & Onboarding Guide template.

    Template table index (by creation order in build_project_explanation):
      [0]  header_block (2-col)
      [1]  PURPOSE note_box (1-col)
      [2]  Project at a Glance (4-col field_table)
      [3]  Why This Project Exists note_box (1-col)
      [4]  Business Problem/Solution/Metric (3-col make_table)
      [5]  Architecture Overview note_box (1-col)
      [6]  Architecture diagram_box (1-col placeholder)
      [7]  System Mode/Description/Entry Point/Output (4-col make_table)
      [8]  Frontend Data Processing Flow (5-col make_table)
      [9]  Batch Processing Flow (6-col make_table)
      [10] Codebase Structure note_box (1-col)
      [11] Codebase Structure (4-col make_table)
      [12] Key Concepts (4-col make_table)
      [13] API Endpoints (5-col make_table)
      [14] BigQuery Data Model (5-col make_table)
      [15] How To Run Locally (5-col make_table)
      [16] Env & Config Reference (5-col make_table)
      [17] Infrastructure & IAM (4-col make_table)
      [18] Contacts & Escalation (4-col make_table)
      [19] Revision table
    """
    tables = doc.tables

    # Header block — use project identity fields
    glance = _get_fields(_get_section(sections, "PROJECT AT A GLANCE", "PROJECT IDENTITY"))
    _update_header_block(tables[0], glance)

    # table[2]: Project at a Glance (4-col kv)
    if glance and len(tables) > 2:
        _fill_kv_table(tables[2], glance)
        stats['glance'] = 'filled'

    # table[4]: Why This Project Exists (Business Problem | Approach | Success Metric)
    prob_sec = _get_section(sections, "WHY THIS PROJECT EXISTS", "PROBLEM STATEMENT", "BUSINESS PROBLEM")
    if prob_sec and len(tables) > 4:
        bullets = _get_bullets(prob_sec)
        _fill_data_table(tables[4], bullets, start_row=1,
                         col_keys=["Business Problem", "Approach / Solution", "Success Metric / KPI"])
        stats['problem'] = 'filled'

    # table[7]: System Architecture Overview — modes table
    arch_sec = _get_section(sections, "SYSTEM ARCHITECTURE OVERVIEW", "ARCHITECTURE OVERVIEW")
    if arch_sec and len(tables) > 7:
        bullets = _get_bullets(arch_sec)
        _fill_data_table(tables[7], bullets, start_row=1,
                         col_keys=["System Mode", "Description", "Entry Point", "Output"])

    # table[8]: Frontend Data Processing Flow
    flow_sec = _get_section(sections, "DATA PROCESSING FLOW (FRONTEND)", "DATA PROCESSING FLOW",
                            "FRONTEND FLOW", "PROCESSING FLOW")
    if flow_sec and len(tables) > 8:
        bullets = _get_bullets(flow_sec)
        _fill_data_table(tables[8], bullets, start_row=1,
                         col_keys=["Step #", "What Happens", "Key Module / File", "Input", "Output"])
        stats['flow_steps'] = len(bullets)

    # table[9]: Batch Processing Flow
    batch_sec = _get_section(sections, "BATCH PROCESSING FLOW", "BATCH FLOW")
    if batch_sec and len(tables) > 9:
        bullets = _get_bullets(batch_sec)
        _fill_data_table(tables[9], bullets, start_row=1,
                         col_keys=["Step #", "Component", "What It Does", "Input", "Output", "Script / Entry"])

    # table[11]: Codebase Structure
    code_sec = _get_section(sections, "CODEBASE STRUCTURE", "CODE STRUCTURE", "PROJECT STRUCTURE")
    if code_sec and len(tables) > 11:
        bullets = _get_bullets(code_sec)
        _fill_data_table(tables[11], bullets, start_row=1,
                         col_keys=["Folder / File", "What It Does", "Key Classes / Functions", "When To Touch It"])
        stats['code_items'] = len(bullets)

    # table[12]: Key Concepts
    concepts_sec = _get_section(sections, "KEY CONCEPTS", "GLOSSARY", "CONCEPTS")
    if concepts_sec and len(tables) > 12:
        bullets = _get_bullets(concepts_sec)
        _fill_data_table(tables[12], bullets, start_row=1,
                         col_keys=["Concept", "What It Is", "Why It Matters Here", "Where To Find Code / Docs"])
        stats['concepts'] = len(bullets)

    # table[13]: API Endpoints
    api_sec = _get_section(sections, "API ENDPOINTS", "API REFERENCE", "ENDPOINTS")
    if api_sec and len(tables) > 13:
        bullets = _get_bullets(api_sec)
        _fill_data_table(tables[13], bullets, start_row=1,
                         col_keys=["Method", "Endpoint", "Purpose", "Request Payload", "Response"])
        stats['endpoints'] = len(bullets)

    # table[14]: BigQuery Data Model
    bq_sec = _get_section(sections, "BIGQUERY DATA MODEL", "DATA MODEL", "BIGQUERY TABLES")
    if bq_sec and len(tables) > 14:
        bullets = _get_bullets(bq_sec)
        _fill_data_table(tables[14], bullets, start_row=1,
                         col_keys=["Table", "Primary Key(s)", "Key Columns", "Populated By", "Notes"])

    # table[15]: How To Run Locally
    run_sec = _get_section(sections, "HOW TO RUN LOCALLY", "LOCAL SETUP", "DEVELOPER SETUP")
    if run_sec and len(tables) > 15:
        bullets = _get_bullets(run_sec)
        _fill_data_table(tables[15], bullets, start_row=1,
                         col_keys=["Step", "Action", "Command / Tool", "Expected Output", "Notes"])
        stats['run_steps'] = len(bullets)

    # table[16]: Env & Config Reference
    env_sec = _get_section(sections, "ENVIRONMENT & CONFIG REFERENCE",
                           "ENVIRONMENT REFERENCE", "CONFIG REFERENCE", "CONFIGURATION")
    if env_sec and len(tables) > 16:
        bullets = _get_bullets(env_sec)
        _fill_data_table(tables[16], bullets, start_row=1,
                         col_keys=["Variable / Config Key", "Description", "Example Value", "Required", "Source"])
        stats['env_vars'] = len(bullets)

    # table[17]: Infrastructure & IAM
    infra_sec = _get_section(sections, "INFRASTRUCTURE & IAM", "INFRASTRUCTURE", "IAM")
    if infra_sec and len(tables) > 17:
        bullets = _get_bullets(infra_sec)
        _fill_data_table(tables[17], bullets, start_row=1,
                         col_keys=["GCP Resource", "Name / ID", "Purpose", "Managed By"])

    # table[18]: Contacts & Escalation
    contacts_sec = _get_section(sections, "CONTACTS & ESCALATION", "CONTACTS", "ESCALATION")
    if contacts_sec and len(tables) > 18:
        bullets = _get_bullets(contacts_sec)
        _fill_data_table(tables[18], bullets, start_row=1,
                         col_keys=["Role", "Name", "Slack / Email", "Escalate When"])


# ══════════════════════════════════════════════════════════════════════════════
#  PART 4 — MAIN FILL DISPATCHER
# ══════════════════════════════════════════════════════════════════════════════

FILL_FUNCTIONS = {
    "architecture":       _fill_architecture,
    "codebase_kb":        _fill_codebase_kb,
    "cpdd":               _fill_cpdd,
    "dod":                _fill_dod,
    "dor":                _fill_dor,
    "runbook":            _fill_runbook,
    "risk_register":      _fill_risk_register,
    "sop":                _fill_sop,
    "sprint_log":         _fill_sprint_log,
    "project_explanation": _fill_project_explanation,
}


def fill_document(doc_key: str, llm_response: str, project_name: str = "") -> Path:
    """
    Main entry point for your RAG pipeline.

    Args:
        doc_key      : One of the 9 keys in TEMPLATE_FILES
        llm_response : Raw LLM response string (structured per rag_prompts.py format)
        project_name : Optional project name suffix for filename

    Returns:
        Path to the generated filled DOCX file
    """
    if doc_key not in TEMPLATE_FILES:
        raise ValueError(f"Unknown doc key '{doc_key}'. Valid: {list(TEMPLATE_FILES)}")

    template_path = TEMPLATE_DIR / TEMPLATE_FILES[doc_key]
    if not template_path.exists():
        raise FileNotFoundError(f"Template not found: {template_path}")

    # Parse LLM response
    sections = parse_llm_response(llm_response)

    # Open a fresh copy of the template
    doc = Document(str(template_path))

    # Fill
    stats = {}
    fill_fn = FILL_FUNCTIONS[doc_key]
    fill_fn(doc, sections, stats)

    # Save
    suffix = f"_{project_name}" if project_name else ""
    out_name = f"{OUTPUT_NAMES[doc_key]}{suffix}_{date.today().strftime('%Y%m%d')}.docx"
    out_path = OUTPUT_DIR / out_name
    doc.save(str(out_path))

    kb = out_path.stat().st_size / 1024
    print(f"  ✓  {out_name}  ({kb:.1f} KB)")
    print(f"     Sections parsed: {len(sections)}")
    print(f"     Fill stats: {stats}")
    return out_path


def fill_all(llm_responses: dict, project_name: str = "") -> dict:
    """
    Fill all 9 documents.

    Args:
        llm_responses: {doc_key: llm_response_string}
        project_name : Optional project name suffix

    Returns:
        {doc_key: Path}
    """
    results = {}
    print("=" * 64)
    print(f"  FILLING TEMPLATES  —  {len(llm_responses)} documents")
    print("=" * 64)
    for key, response in llm_responses.items():
        if key not in TEMPLATE_FILES:
            print(f"  ✗  Unknown key: {key} — skipped")
            continue
        try:
            path = fill_document(key, response, project_name)
            results[key] = path
        except Exception as e:
            print(f"  ✗  FAILED {key}: {e}")
    print("-" * 64)
    print(f"  Done — {len(results)}/{len(llm_responses)} filled → {OUTPUT_DIR.name}/")
    return results


# ══════════════════════════════════════════════════════════════════════════════
#  PART 5 — DEMO MODE (auto-generate realistic fake response for all 9 docs)
# ══════════════════════════════════════════════════════════════════════════════

DEMO_RESPONSES = {
"architecture": """
--- SECTION: Project Context (Detected) ---
  SDLC Methodology:   Scrum [✓ found]
  Project Type:       Microservices Web App [✓ found]
  Ticket Tool:        Jira [✓ found]
  Repo Host:          GitHub [✓ found]
  CI/CD Platform:     GitHub Actions [✓ found]
  Doc System:         Confluence [~ inferred]

--- SECTION: Purpose & Scope ---
  The ShopNow platform enables online retail customers to browse, purchase,
  and track orders in real time. The system boundary covers web frontend,
  order management, inventory, payments, and notification services.

--- SECTION: External Actors & Integrations ---
  • Actor/System: End Customer | Type: Human User | Interaction: Browse and purchase | Protocol: REST
  • Actor/System: Stripe | Type: 3rd Party | Interaction: Payment processing | Protocol: REST
  • Actor/System: Sendgrid | Type: 3rd Party | Interaction: Email notifications | Protocol: REST
  • Actor/System: Admin Portal | Type: Human User | Interaction: Order management | Protocol: REST

--- SECTION: Technology Stack ---
  • Layer: Frontend | Technology: React 18 | Version: 18.2.0 | Justification: Team expertise, component reuse
  • Layer: Backend/API | Technology: Node.js + Express | Version: 20.x | Justification: Existing codebase
  • Layer: Database | Technology: PostgreSQL | Version: 15 | Justification: ACID compliance required
  • Layer: Cache | Technology: Redis | Version: 7.2 | Justification: Session and cart caching
  • Layer: Auth/IAM | Technology: Auth0 | Version: Latest | Justification: OAuth2/OIDC managed service
  • Layer: Infra/Cloud | Technology: AWS EKS | Version: 1.29 | Justification: Container orchestration
  • Layer: CI/CD | Technology: GitHub Actions | Version: N/A | Justification: Native GitHub integration

--- SECTION: Component Architecture ---
  • Component: API Gateway | Responsibility: Route and authenticate requests | Technology: Kong | Exposes: REST | Consumes: All services
  • Component: Order Service | Responsibility: Order lifecycle management | Technology: Node.js | Exposes: REST /orders | Consumes: Inventory DB
  • Component: Inventory Service | Responsibility: Stock tracking | Technology: Go | Exposes: gRPC | Consumes: PostgreSQL
  • Component: Payment Service | Responsibility: Payment processing | Technology: Node.js | Exposes: REST | Consumes: Stripe API

--- SECTION: Architecture Decision Records (ADRs) ---
  • ADR-001 | Decision: Use microservices over monolith | Alternatives Considered: Modular monolith | Rationale: Independent scaling needed | Status: Accepted
  • ADR-002 | Decision: PostgreSQL for OLTP | Alternatives Considered: MongoDB, MySQL | Rationale: Strong consistency for orders | Status: Accepted
  • ADR-003 | Decision: Redis for session cache | Alternatives Considered: Memcached | Rationale: Pub/Sub support needed | Status: Accepted

--- SECTION: Non-Functional Requirements ---
  • Category: Performance | Requirement: API response time | Target/SLA: < 200ms p95 | How Measured: Datadog APM | Priority: High
  • Category: Availability | Requirement: Uptime | Target/SLA: 99.9% | How Measured: Synthetic monitors | Priority: High
  • Category: Security | Requirement: Auth mechanism | Target/SLA: OAuth 2.0 PKCE | How Measured: Pen test quarterly | Priority: High
  • Category: Scalability | Requirement: Concurrent users | Target/SLA: 50,000 | How Measured: Load test | Priority: Medium

--- SECTION: Security & Compliance ---
  Auth mechanism: OAuth 2.0 / OIDC via Auth0 [✓ found]
  Data encryption at rest: Yes — AES-256 [✓ found]
  Data encryption transit: TLS 1.3 [✓ found]
  Compliance requirements: GDPR, PCI-DSS [✓ found]
  Secret management: AWS Secrets Manager [✓ found]

--- SECTION: Error & Edge Cases ---
  • Scenario: Payment timeout | Trigger: Stripe API > 30s | System Response: Return 408, retry queue | Recovery: Idempotent retry with same payment ID
  • Scenario: Inventory race condition | Trigger: Concurrent buy same item | System Response: Optimistic lock, 409 conflict | Recovery: Re-fetch and prompt user
  • Scenario: Auth token expired | Trigger: JWT exp exceeded | System Response: 401 Unauthorized | Recovery: Refresh token flow

--- SECTION: Confidence Summary ---
  Total fields: 24 | Found: 21 | Inferred: 2 | NA: 1 | Completeness: 96%
""",

"cpdd": """
--- SECTION: Project Context (Detected) ---
  SDLC Methodology:   Scrum [✓ found]
  Project Type:       Web App [✓ found]
  Ticket Tool:        Jira [✓ found]
  Repo Host:          GitHub [✓ found]

--- SECTION: Project Identity ---
  Project Name:         ShopNow E-Commerce Platform [✓ found]
  Project Code:         SNP-2025 [✓ found]
  Business Unit:        Digital Commerce [✓ found]
  Sponsor:              Jane Smith (VP Product) [✓ found]
  Product Owner / PM:   Rahul Verma [✓ found]
  Tech Lead / Architect:Alex Chen [✓ found]
  Start Date:           01 Jan 2025 [✓ found]
  Target Go-Live:       30 Jun 2025 [✓ found]
  Budget:               $420,000 [~ inferred]
  Priority:             High [✓ found]
  Project Phase:        Development [✓ found]

--- SECTION: Business Problem & Objectives ---
  • Business Problem: Legacy system cannot handle > 2,000 concurrent users | Desired Outcome: New platform supports 50,000 concurrent users | Success Metric: p95 latency < 200ms at peak | Baseline: Current p95 = 4.2s

--- SECTION: Stakeholders ---
  • Name: Jane Smith | Role: Executive Sponsor | Organisation / Dept: Product | Responsibility: Budget and strategic direction | Engagement Level: Accountable | Decision Authority: Yes
  • Name: Rahul Verma | Role: Product Owner | Organisation / Dept: Digital Commerce | Responsibility: Backlog and priorities | Engagement Level: Responsible | Decision Authority: Yes
  • Name: Alex Chen | Role: Tech Lead | Organisation / Dept: Engineering | Responsibility: Architecture and delivery | Engagement Level: Responsible | Decision Authority: No

--- SECTION: Scope -- IN ---
  • Web and mobile-responsive storefront
  • Order management and tracking
  • Payment processing via Stripe
  • Inventory management
  • Customer notifications (email + push)

--- SECTION: Scope -- OUT OF SCOPE ---
  • Native mobile apps (iOS/Android) — deferred to Phase 2
  • Marketplace / third-party seller features
  • Loyalty and rewards programme
  • ERP integration

--- SECTION: Deliverables & Milestones ---
  • Milestone: Kick-off | Deliverable: Project charter signed | Owner: Jane Smith | Target Date: 15 Jan 2025 | Status: Done
  • Milestone: Architecture Approved | Deliverable: ADR sign-off | Owner: Alex Chen | Target Date: 01 Feb 2025 | Status: Done
  • Milestone: Dev Complete | Deliverable: All features code-complete | Owner: Rahul Verma | Target Date: 15 May 2025 | Status: In Progress
  • Milestone: UAT Sign-off | Deliverable: UAT report | Owner: Jane Smith | Target Date: 10 Jun 2025 | Status: Not Started
  • Milestone: Go-Live | Deliverable: Production deployment | Owner: Alex Chen | Target Date: 30 Jun 2025 | Status: Not Started

--- SECTION: Assumptions ---
  • AWS infrastructure is already provisioned and accessible
  • Stripe API credentials will be provided before Sprint 3

--- SECTION: Constraints ---
  • Type: Time | Constraint: Go-live cannot slip beyond Q3 2025 for contractual reasons | Impact if Violated: Penalty clause of $50k/month
  • Type: Technology | Constraint: Must use existing Auth0 tenant — no migration | Impact if Violated: Delays and re-architecture

--- SECTION: Top Risks Summary ---
  • Risk: Stripe integration delay | P: M | I: H | Score: 6 | Owner: Alex Chen | Mitigation headline: Early POC in Sprint 2
  • Risk: Team capacity — 2 engineers on leave Q2 | P: H | I: M | Score: 6 | Owner: Rahul Verma | Mitigation headline: Cross-train 1 backend engineer

--- SECTION: Approval & Sign-Off ---
  • Role: Executive Sponsor | Name: Jane Smith | Sign-off Required: Yes
  • Role: Product Owner | Name: Rahul Verma | Sign-off Required: Yes
  • Role: Project Manager | Name: Priya Nair | Sign-off Required: Yes

--- SECTION: Confidence Summary ---
  Total fields: 32 | Found: 29 | Inferred: 2 | NA: 1 | Completeness: 97%
""",

"risk_register": """
--- SECTION: Project Context (Detected) ---
  SDLC Methodology: Scrum [✓ found]
  Project Type: Microservices Web App [✓ found]

--- SECTION: Risk Register ---
  • ID: R-001 | Category: Technical | Description: Risk that Stripe API SLA degrades causing payment failures | Probability: 2 | Impact: 5 | Score: 10 | Rating: High | Owner: Alex Chen | Mitigation: Weekly Stripe status check, implement retry with exponential backoff | Contingency: Switch to PayPal as backup | Status: Mitigating
  • ID: R-002 | Category: Schedule | Description: Risk that UAT finds critical bugs delaying go-live | Probability: 3 | Impact: 4 | Score: 12 | Rating: High | Owner: Rahul Verma | Mitigation: Continuous QA in each sprint, automated regression | Contingency: 2-week buffer built into plan | Status: Open
  • ID: R-003 | Category: Resource | Description: Risk that 2 senior engineers on leave reduces velocity by 40% | Probability: 4 | Impact: 3 | Score: 12 | Rating: High | Owner: Rahul Verma | Mitigation: Cross-training started Sprint 4, contractor identified | Contingency: Scope reduction of non-critical features | Status: Mitigating
  • ID: R-004 | Category: Security | Description: Risk that PCI-DSS audit identifies compliance gaps | Probability: 2 | Impact: 5 | Score: 10 | Rating: High | Owner: Alex Chen | Mitigation: Pre-audit internal scan, SAST in CI | Contingency: Engage PCI QSA early | Status: Open
  • ID: R-005 | Category: External | Description: Risk that AWS region outage causes service unavailability | Probability: 1 | Impact: 5 | Score: 5 | Rating: Medium | Owner: DevOps Lead | Mitigation: Multi-AZ deployment | Contingency: Route 53 failover to secondary region | Status: Accepted

--- SECTION: Risk Summary Dashboard ---
  Total identified: 5
  Critical: 0
  High: 4
  Medium: 1
  Low: 0
  Top Risk (highest score): R-002 / R-003 — Score 12

--- SECTION: Confidence Summary ---
  Total fields: 18 | Found: 16 | Inferred: 1 | NA: 1 | Completeness: 94%
""",

"sprint_log": """
--- SECTION: Project Context (Detected) ---
  SDLC Methodology: Scrum [✓ found]
  Ticket Tool: Jira [✓ found]

--- SECTION: Iteration Summary ---
  Sprint / Iteration name: Sprint 12 — Checkout & Payments [✓ found]
  Sprint / Iteration number: 12 [✓ found]
  Goal / Objective: Complete checkout flow and Stripe payment integration end-to-end [✓ found]
  Start date: 03 Mar 2026 [✓ found]
  End date: 14 Mar 2026 [✓ found]
  Team name: Phoenix Team [✓ found]
  Team size: 7 [✓ found]
  Committed points: 42 [✓ found]
  Rolling average velocity: 38 [✓ found]
  Outcome: Goal Met [✓ found]

--- SECTION: Committed Work Items ---
  • ID: SNP-301 | Title: Checkout page UI — credit card form | Type: Story | Points: 8 | Assignee: Dev A | Status at close: Done
  • ID: SNP-302 | Title: Stripe payment intent API integration | Type: Story | Points: 13 | Assignee: Dev B | Status at close: Done
  • ID: SNP-303 | Title: Order confirmation email via Sendgrid | Type: Story | Points: 5 | Assignee: Dev C | Status at close: Done
  • ID: SNP-304 | Title: Payment failure handling and retry logic | Type: Story | Points: 8 | Assignee: Dev B | Status at close: Done
  • ID: SNP-305 | Title: Fix cart total rounding bug | Type: Bug | Points: 3 | Assignee: Dev A | Status at close: Done
  • ID: SNP-306 | Title: Performance test checkout API — p95 target | Type: Spike | Points: 5 | Assignee: Dev D | Status at close: Carried Over

--- SECTION: Carry-Over Items ---
  • ID: SNP-306 | Title: Performance test checkout API | Points: 5 | Root cause: Load testing env not ready | Action: Re-commit to next sprint

--- SECTION: Sprint Review / Demo ---
  • Item: Checkout flow end-to-end | Demo'd by: Dev B | Stakeholder attending: Jane Smith (Sponsor) | Feedback: Approved | Accepted: Yes
  • Item: Email confirmation | Demo'd by: Dev C | Stakeholder attending: Rahul Verma | Feedback: Add order summary to email | Accepted: Conditional — condition: Add line items to email template

--- SECTION: Retrospective ---
  Facilitation format: Start / Stop / Continue [✓ found]

  Went Well:
  • Stripe integration completed in one sprint — no blockers
  • Daily standups were sharp and focused
  • PR review turnaround was < 24 hrs

  Needs Improvement:
  • Load test environment should be provisioned before sprint starts
  • Story SNP-306 was blocked Day 1 — should have been flagged in planning

  Action Items:
  • Action: Provision dedicated load test environment | Owner: DevOps Lead | Due: 17 Mar 2026 | Status: Open
  • Action: Add environment availability check to DoR | Owner: Scrum Master | Due: Next retro | Status: Open

--- SECTION: Sprint Metrics ---
  Points committed: 42 [✓ found]
  Points completed: 37 [✓ found]
  Points carried over: 5 [✓ found]
  Bugs found this sprint: 1 [✓ found]
  Bugs closed this sprint: 1 [✓ found]
  Team availability: 95% [~ inferred]
  Velocity vs 3-sprint average: Above (37 vs avg 38 — within range) [~ inferred]
  Sprint goal met: Yes — all core stories done, spike deferred [✓ found]

--- SECTION: Confidence Summary ---
  Total fields: 28 | Found: 24 | Inferred: 3 | NA: 1 | Completeness: 96%
""",
}

# Fill in remaining demo responses with minimal stubs
for _key in TEMPLATE_FILES:
    if _key not in DEMO_RESPONSES:
        DEMO_RESPONSES[_key] = f"""
--- SECTION: Project Context (Detected) ---
  SDLC Methodology: Scrum [~ inferred]
  Project Type: Web App [~ inferred]
  Ticket Tool: Jira [~ inferred]

--- SECTION: Confidence Summary ---
  Total fields: 5 | Found: 0 | Inferred: 3 | NA: 2 | Completeness: 60%
"""


# ══════════════════════════════════════════════════════════════════════════════
#  PART 6 — CLI
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Fill DOCX templates with LLM+RAG extracted data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  py fill_template.py --demo
  py fill_template.py --doc cpdd --response my_response.txt --project ShopNow
  py fill_template.py --doc all  --response_dir ./llm_outputs/ --project ShopNow
        """
    )
    parser.add_argument("--doc", choices=list(TEMPLATE_FILES) + ["all"],
                        default="all", help="Which document to fill (default: all)")
    parser.add_argument("--response", help="Path to .txt file containing LLM response")
    parser.add_argument("--text",     help="LLM response as inline string")
    parser.add_argument("--response_dir", help="Directory with <doc_key>.txt files (for --doc all)")
    parser.add_argument("--project",  default="", help="Project name suffix for output filename")
    parser.add_argument("--demo",     action="store_true", help="Run with built-in demo data")
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(exist_ok=True)

    print("=" * 64)
    print("  TEMPLATE FILLER  —  LLM+RAG → DOCX")
    print("=" * 64)

    if args.demo:
        print("  Mode: DEMO (using built-in sample data)")
        print()
        fill_all(DEMO_RESPONSES, project_name="Demo")
        return

    if args.doc == "all":
        if not args.response_dir:
            print("ERROR: --response_dir required when --doc all")
            sys.exit(1)
        rd = Path(args.response_dir)
        responses = {}
        for key in TEMPLATE_FILES:
            f = rd / f"{key}.txt"
            if f.exists():
                responses[key] = f.read_text(encoding="utf-8")
            else:
                print(f"  ⚠  Missing: {f.name} — skipping {key}")
        fill_all(responses, project_name=args.project)
    else:
        # Single document
        if args.text:
            response = args.text
        elif args.response:
            response = Path(args.response).read_text(encoding="utf-8")
        else:
            print("ERROR: Provide --response <file> or --text <string> or --demo")
            sys.exit(1)
        fill_document(args.doc, response, project_name=args.project)

    print("=" * 64)


if __name__ == "__main__":
    main()
