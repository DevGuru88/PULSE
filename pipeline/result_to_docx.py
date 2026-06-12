#!/usr/bin/env python3
"""
LLM Output to Professional DOCX Converter
==========================================

Dynamically parses Markdown-formatted LLM output and converts it into a
professionally formatted Word document with:
- Styled headings, paragraphs, and lists
- Formatted tables with header coloring and alternating row shading
- Info/warning/success boxes
- Checklists with checkbox rendering
- Code blocks with monospace formatting
- Bold, italic, inline code, and link handling
- Cover page generation from document metadata
- Headers and footers with page numbers
- Dynamic color theming
"""

import re
import os
import sys
from dataclasses import dataclass, field
from typing import List, Optional, Tuple
from enum import Enum, auto
from pathlib import Path

from docx import Document
from docx.shared import Inches, Pt, Cm, RGBColor, Emu
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL
from docx.oxml.ns import qn, nsdecls
from docx.oxml import parse_xml


# ═══════════════════════════════════════════════════════════════════════════════
# THEME CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class DocumentTheme:
    """Color theme for the document."""
    primary: str = "1B4F72"          # Deep blue
    primary_rgb: tuple = (27, 79, 114)
    secondary: str = "2E86C1"        # Medium blue
    accent: str = "27AE60"           # Green
    warning: str = "E74C3C"          # Red
    info: str = "F39C12"             # Orange/amber
    text_dark: str = "333333"
    text_light: str = "666666"
    text_muted: str = "999999"
    bg_light: str = "EBF5FB"         # Light blue background
    bg_alt_row: str = "F5F8FA"       # Alternating row background
    bg_header: str = "1B4F72"        # Table header background
    white: str = "FFFFFF"
    border: str = "BDC3C7"


DEFAULT_THEME = DocumentTheme()


# ═══════════════════════════════════════════════════════════════════════════════
# MARKDOWN PARSER — TOKEN TYPES
# ═══════════════════════════════════════════════════════════════════════════════

class TokenType(Enum):
    HEADING = auto()
    PARAGRAPH = auto()
    TABLE = auto()
    ORDERED_LIST = auto()
    UNORDERED_LIST = auto()
    CHECKLIST = auto()
    CODE_BLOCK = auto()
    HORIZONTAL_RULE = auto()
    BLOCKQUOTE = auto()
    BLANK_LINE = auto()


@dataclass
class Token:
    type: TokenType
    content: str = ""
    level: int = 0  # For headings (1-6), list nesting
    children: list = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


@dataclass
class TableData:
    headers: List[str]
    rows: List[List[str]]
    alignments: List[str] = field(default_factory=list)  # 'left', 'center', 'right'


# ═══════════════════════════════════════════════════════════════════════════════
# MARKDOWN PARSER
# ═══════════════════════════════════════════════════════════════════════════════

class MarkdownParser:
    """Parses markdown text into structured tokens."""

    def __init__(self, text: str):
        self.lines = text.split('\n')
        self.pos = 0
        self.tokens: List[Token] = []

    def parse(self) -> List[Token]:
        """Parse all lines into tokens."""
        while self.pos < len(self.lines):
            line = self.lines[self.pos]

            if self._is_blank(line):
                self.pos += 1
                continue

            # Fenced code blocks first (highest priority)
            if self._try_parse_code_block(line):
                continue
            # ASCII box-drawing / flow diagrams → monospace block
            if self._try_parse_ascii_diagram(line):
                continue
            # Banner-style headings: ====\nTITLE\n==== (also handles lone ==== as HR)
            if self._try_parse_banner_heading(line):
                continue
            # Standard # heading
            if self._try_parse_heading(line):
                continue
            # Setext headings: TITLE on current line, === or --- on next line
            if self._try_parse_setext_heading(line):
                continue
            # Standard horizontal rules --- / *** / ___
            if self._try_parse_horizontal_rule(line):
                continue
            if self._try_parse_table(line):
                continue
            if self._try_parse_checklist(line):
                continue
            if self._try_parse_ordered_list(line):
                continue
            if self._try_parse_unordered_list(line):
                continue
            if self._try_parse_blockquote(line):
                continue

            # Default: paragraph (collect consecutive non-blank, non-special lines)
            # Safety guard: if _parse_paragraph() did not advance pos (e.g. the
            # first line triggers an internal break condition that no other parser
            # handles), force-advance to prevent an infinite loop.
            pos_before = self.pos
            self._parse_paragraph()
            if self.pos == pos_before:          # no progress made
                self.tokens.append(Token(TokenType.PARAGRAPH,
                                         content=line.strip()))
                self.pos += 1

        return self.tokens

    def _is_blank(self, line: str) -> bool:
        return line.strip() == ''

    def _try_parse_heading(self, line: str) -> bool:
        m = re.match(r'^(#{1,6})\s+(.+)$', line.strip())
        if m:
            level = len(m.group(1))
            content = m.group(2).strip()
            self.tokens.append(Token(TokenType.HEADING, content=content, level=level))
            self.pos += 1
            return True
        return False

    # ─── New: Banner Heading  (====\nTEXT\n====) ──────────────────────────

    def _try_parse_banner_heading(self, line: str) -> bool:
        """Handle ====...====\n  TITLE  \n====...==== banner-style section headers.
        A lone ==== line that is NOT part of a banner is emitted as HORIZONTAL_RULE.
        """
        stripped = line.strip()
        if not re.match(r'^={4,}$', stripped):
            return False
        # Peek ahead (skip blanks) for a title then another ==== line
        peek = self.pos + 1
        while peek < len(self.lines) and not self.lines[peek].strip():
            peek += 1
        if peek < len(self.lines):
            title_candidate = self.lines[peek].strip()
            peek2 = peek + 1
            while peek2 < len(self.lines) and not self.lines[peek2].strip():
                peek2 += 1
            if (title_candidate
                    and not re.match(r'^[=\-]{4,}$', title_candidate)
                    and peek2 < len(self.lines)
                    and re.match(r'^={4,}$', self.lines[peek2].strip())):
                # Genuine banner heading
                self.tokens.append(Token(TokenType.HEADING,
                                         content=title_candidate.strip(), level=1))
                self.pos = peek2 + 1
                return True
        # Lone ==== → horizontal rule
        self.tokens.append(Token(TokenType.HORIZONTAL_RULE))
        self.pos += 1
        return True

    # ─── New: Setext Heading  (TEXT\n====) ──────────────────────────────────

    def _try_parse_setext_heading(self, line: str) -> bool:
        """Handle setext-style headings: non-blank text followed by ==== (H1) or ---- (H2)."""
        stripped = line.strip()
        if not stripped:
            return False
        # The current line must not itself be a separator-only line
        if re.match(r'^[=#\-\*_]{3,}$', stripped):
            return False
        # Don't steal table rows or list items
        if stripped.startswith('|') or re.match(r'^[-*+]\s', stripped) or re.match(r'^\d+[.)]\s', stripped):
            return False
        if self.pos + 1 >= len(self.lines):
            return False
        next_stripped = self.lines[self.pos + 1].strip()
        if re.match(r'^={3,}$', next_stripped):
            self.tokens.append(Token(TokenType.HEADING, content=stripped, level=1))
            self.pos += 2
            return True
        if re.match(r'^-{3,}$', next_stripped) and len(stripped) < 120:
            self.tokens.append(Token(TokenType.HEADING, content=stripped, level=2))
            self.pos += 2
            return True
        return False

    # ─── New: ASCII Diagram / Box-Drawing Detector ───────────────────────────

    _BOX_CHARS = frozenset('\u2502\u250c\u2514\u2510\u2518\u2500\u252c\u2534\u251c\u2524\u253c'
                           '\u25bc\u25b2\u25ba\u25c4\u2192\u2190\u2191\u2193\u25c6\u25cf\u25cb')
    # │  ┌  └  ┐  ┘  ─  ┬  ┴  ├  ┤  ┼  ▼  ▲  ►  ◄  →  ←  ↑  ↓  ◆  ●  ○

    def _try_parse_ascii_diagram(self, line: str) -> bool:
        """Collect consecutive ASCII box-drawing / activity-diagram lines → CODE_BLOCK."""
        if not any(c in line for c in self._BOX_CHARS):
            return False
        diagram_lines = []
        while self.pos < len(self.lines):
            l = self.lines[self.pos]
            ls = l.strip()
            if not ls:
                # Allow one blank line inside diagram block if next line still has box chars
                if (self.pos + 1 < len(self.lines)
                        and any(c in self.lines[self.pos + 1] for c in self._BOX_CHARS)):
                    diagram_lines.append('')
                    self.pos += 1
                    continue
                break
            if any(c in l for c in self._BOX_CHARS):
                diagram_lines.append(l.rstrip())
                self.pos += 1
            else:
                break
        if diagram_lines:
            self.tokens.append(Token(
                TokenType.CODE_BLOCK,
                content='\n'.join(diagram_lines),
                metadata={'language': '', 'is_diagram': True}
            ))
            return True
        return False

    # ─── Standard Horizontal Rule  --- / *** / ___ ───────────────────────────

    def _try_parse_horizontal_rule(self, line: str) -> bool:
        stripped = line.strip()
        if re.match(r'^(-{3,}|\*{3,}|_{3,})$', stripped):
            self.tokens.append(Token(TokenType.HORIZONTAL_RULE))
            self.pos += 1
            return True
        return False

    def _try_parse_code_block(self, line: str) -> bool:
        stripped = line.strip()
        if stripped.startswith('```'):
            lang = stripped[3:].strip()
            self.pos += 1
            code_lines = []
            while self.pos < len(self.lines):
                if self.lines[self.pos].strip().startswith('```'):
                    self.pos += 1
                    break
                code_lines.append(self.lines[self.pos])
                self.pos += 1
            self.tokens.append(Token(
                TokenType.CODE_BLOCK,
                content='\n'.join(code_lines),
                metadata={'language': lang}
            ))
            return True
        return False

    def _try_parse_table(self, line: str) -> bool:
        """Detect and parse a markdown table."""
        stripped = line.strip()
        if '|' not in stripped:
            return False

        # Check if this looks like a table header row
        if not self._is_table_row(stripped):
            return False

        # Look ahead for separator row
        if self.pos + 1 >= len(self.lines):
            return False

        next_line = self.lines[self.pos + 1].strip()
        if not self._is_table_separator(next_line):
            return False

        # Parse the full table
        headers = self._parse_table_row(stripped)
        alignments = self._parse_table_alignments(next_line)

        self.pos += 2  # Skip header and separator

        rows = []
        while self.pos < len(self.lines):
            row_line = self.lines[self.pos].strip()
            if not self._is_table_row(row_line):
                break
            rows.append(self._parse_table_row(row_line))
            self.pos += 1

        table_data = TableData(headers=headers, rows=rows, alignments=alignments)
        self.tokens.append(Token(
            TokenType.TABLE,
            metadata={'table_data': table_data}
        ))
        return True

    def _is_table_row(self, line: str) -> bool:
        stripped = line.strip()
        # Accept rows that start with | and have 2+ | chars (even without trailing |)
        return stripped.startswith('|') and stripped.count('|') >= 2

    def _is_table_separator(self, line: str) -> bool:
        stripped = line.strip()
        if not stripped.startswith('|') or stripped.count('|') < 2:
            return False
        cells = [c.strip() for c in stripped.strip('|').split('|')]
        return all(re.match(r'^:?-+:?$', c) for c in cells if c)

    def _parse_table_row(self, line: str) -> List[str]:
        cells = line.strip('|').split('|')
        return [c.strip() for c in cells]

    def _parse_table_alignments(self, line: str) -> List[str]:
        cells = line.strip('|').split('|')
        alignments = []
        for c in cells:
            c = c.strip()
            if c.startswith(':') and c.endswith(':'):
                alignments.append('center')
            elif c.endswith(':'):
                alignments.append('right')
            else:
                alignments.append('left')
        return alignments

    def _try_parse_checklist(self, line: str) -> bool:
        stripped = line.strip()
        m = re.match(r'^[-*]\s+\[([ xX✅✓☐☑])\]\s+(.+)$', stripped)
        if m:
            items = []
            while self.pos < len(self.lines):
                l = self.lines[self.pos].strip()
                m2 = re.match(r'^[-*]\s+\[([ xX✅✓☐☑])\]\s+(.+)$', l)
                if m2:
                    checked = m2.group(1) not in (' ', '☐')
                    items.append({'text': m2.group(2), 'checked': checked})
                    self.pos += 1
                else:
                    break
            self.tokens.append(Token(
                TokenType.CHECKLIST,
                children=items
            ))
            return True
        return False

    def _try_parse_unordered_list(self, line: str) -> bool:
        stripped = line.strip()
        m = re.match(r'^[-*+]\s+(.+)$', stripped)
        if m:
            items = []
            cont = 0   # consecutive continuation lines — capped at 3
            while self.pos < len(self.lines):
                l = self.lines[self.pos].strip()
                m2 = re.match(r'^[-*+]\s+(.+)$', l)
                if m2:
                    items.append(m2.group(1))
                    cont = 0
                    self.pos += 1
                elif l and not self._is_blank(l) and not l.startswith('#') and '|' not in l and cont < 3:
                    # Allow up to 3 consecutive wrapped-text continuation lines
                    if items:
                        items[-1] += ' ' + l
                    cont += 1
                    self.pos += 1
                else:
                    break
            self.tokens.append(Token(
                TokenType.UNORDERED_LIST,
                children=items
            ))
            return True
        return False

    def _try_parse_ordered_list(self, line: str) -> bool:
        stripped = line.strip()
        m = re.match(r'^(\d+)[.)]\s+(.+)$', stripped)
        if m:
            items = []
            cont = 0   # consecutive continuation lines — capped at 3
            while self.pos < len(self.lines):
                l = self.lines[self.pos].strip()
                m2 = re.match(r'^(\d+)[.)]\s+(.+)$', l)
                if m2:
                    items.append(m2.group(2))
                    cont = 0
                    self.pos += 1
                elif l and not self._is_blank(l) and not l.startswith('#') and '|' not in l and cont < 3:
                    # Allow up to 3 consecutive wrapped-text continuation lines
                    if items:
                        items[-1] += ' ' + l
                    cont += 1
                    self.pos += 1
                else:
                    break
            self.tokens.append(Token(
                TokenType.ORDERED_LIST,
                children=items
            ))
            return True
        return False

    def _try_parse_blockquote(self, line: str) -> bool:
        stripped = line.strip()
        if stripped.startswith('>'):
            lines_collected = []
            while self.pos < len(self.lines):
                l = self.lines[self.pos].strip()
                if l.startswith('>'):
                    lines_collected.append(l.lstrip('>').strip())
                    self.pos += 1
                else:
                    break
            self.tokens.append(Token(
                TokenType.BLOCKQUOTE,
                content='\n'.join(lines_collected)
            ))
            return True
        return False

    def _parse_paragraph(self):
        """Collect consecutive paragraph lines."""
        lines_collected = []
        while self.pos < len(self.lines):
            line = self.lines[self.pos]
            stripped = line.strip()

            if self._is_blank(stripped):
                break
            if stripped.startswith('#'):
                break
            # Standard HR patterns
            if re.match(r'^(-{3,}|\*{3,}|_{3,})$', stripped):
                break
            # ==== separator / banner heading
            if re.match(r'^={4,}$', stripped):
                break
            if stripped.startswith('```'):
                break
            # ASCII box-drawing diagram chars
            if any(c in line for c in self._BOX_CHARS):
                break
            if self._is_table_row(stripped) and self.pos + 1 < len(self.lines) and \
                    self._is_table_separator(self.lines[self.pos + 1].strip()):
                break
            if re.match(r'^[-*+]\s+', stripped):
                break
            if re.match(r'^\d+[.)]\s+', stripped):
                break
            if stripped.startswith('>'):
                break
            # Setext heading underline (stop BEFORE collecting the title into paragraph)
            if self.pos + 1 < len(self.lines):
                nxt = self.lines[self.pos + 1].strip()
                if re.match(r'^={3,}$', nxt) or (re.match(r'^-{3,}$', nxt) and len(stripped) < 120):
                    # Flush what we have, then stop so setext parser gets the title
                    break

            lines_collected.append(stripped)
            self.pos += 1

        if lines_collected:
            self.tokens.append(Token(
                TokenType.PARAGRAPH,
                content=' '.join(lines_collected)
            ))


# ═══════════════════════════════════════════════════════════════════════════════
# DOCX RENDERER
# ═══════════════════════════════════════════════════════════════════════════════

class DocxRenderer:
    """Renders parsed tokens into a professionally formatted DOCX document."""

    def __init__(self, theme: DocumentTheme = None):
        self.theme = theme or DEFAULT_THEME
        self.doc = Document()
        self._document_title = ""
        self._document_subtitle = ""
        self._document_metadata = {}
        self._setup_styles()
        self._set_margins()

    def _setup_styles(self):
        """Configure document styles."""
        style = self.doc.styles['Normal']
        font = style.font
        font.name = 'Calibri'
        font.size = Pt(10)
        font.color.rgb = RGBColor.from_string(self.theme.text_dark)

        for level, (size, space_before, space_after) in enumerate([
            (20, 28, 14),   # Heading 1
            (16, 22, 10),   # Heading 2
            (13, 18, 8),    # Heading 3
            (11, 14, 6),    # Heading 4 (if exists)
        ], start=1):
            try:
                h = self.doc.styles[f'Heading {level}']
                h.font.name = 'Calibri'
                h.font.size = Pt(size)
                h.font.bold = True
                h.font.color.rgb = RGBColor(*self.theme.primary_rgb)
                h.paragraph_format.space_before = Pt(space_before)
                h.paragraph_format.space_after = Pt(space_after)
            except KeyError:
                pass

    def _set_margins(self):
        for section in self.doc.sections:
            section.top_margin = Cm(2.0)
            section.bottom_margin = Cm(2.0)
            section.left_margin = Cm(2.5)
            section.right_margin = Cm(2.5)

    # ─── Cell/Table Helpers ───────────────────────────────────────────────

    def _set_cell_shading(self, cell, color_hex):
        shading = parse_xml(
            f'<w:shd {nsdecls("w")} w:fill="{color_hex}" w:val="clear"/>'
        )
        cell._tc.get_or_add_tcPr().append(shading)

    def _set_cell_border(self, cell, **kwargs):
        tc = cell._tc
        tcPr = tc.get_or_add_tcPr()
        tcBorders = parse_xml(f'<w:tcBorders {nsdecls("w")}></w:tcBorders>')
        for edge, val in kwargs.items():
            element = parse_xml(
                f'<w:{edge} {nsdecls("w")} w:val="{val.get("val", "single")}" '
                f'w:sz="{val.get("sz", "4")}" w:space="0" '
                f'w:color="{val.get("color", "000000")}"/>'
            )
            tcBorders.append(element)
        tcPr.append(tcBorders)

    def _set_table_borders(self, table, color=None, size="6"):
        color = color or self.theme.primary
        tbl = table._tbl
        tblPr = tbl.tblPr if tbl.tblPr is not None else parse_xml(
            f'<w:tblPr {nsdecls("w")}/>') 
        borders = parse_xml(
            f'<w:tblBorders {nsdecls("w")}>'
            f'  <w:top w:val="single" w:sz="{size}" w:space="0" w:color="{color}"/>'
            f'  <w:left w:val="single" w:sz="{size}" w:space="0" w:color="{color}"/>'
            f'  <w:bottom w:val="single" w:sz="{size}" w:space="0" w:color="{color}"/>'
            f'  <w:right w:val="single" w:sz="{size}" w:space="0" w:color="{color}"/>'
            f'  <w:insideH w:val="single" w:sz="4" w:space="0" w:color="{color}"/>'
            f'  <w:insideV w:val="single" w:sz="4" w:space="0" w:color="{color}"/>'
            f'</w:tblBorders>'
        )
        tblPr.append(borders)

    # ─── Inline Formatting ────────────────────────────────────────────────

    def _add_formatted_text(self, paragraph, text: str):
        """Parse inline markdown formatting and add runs to paragraph.

        Handles: **bold**, *italic*, `inline code`, [links](url),
                 ~~strikethrough~~, and emoji-like symbols.
        """
        if not text:
            return

        # Pattern to match inline formatting elements
        pattern = re.compile(
            r'(\*\*\*(.+?)\*\*\*)'     # bold+italic ***text***
            r'|(\*\*(.+?)\*\*)'         # bold **text**
            r'|(\*(.+?)\*)'             # italic *text*
            r'|(`([^`]+)`)'             # inline code `text`
            r'|(\[([^\]]+)\]\(([^)]+)\))'  # link [text](url)
            r'|(~~(.+?)~~)'             # strikethrough ~~text~~
        )

        last_end = 0
        for match in pattern.finditer(text):
            start = match.start()
            # Add plain text before this match
            if start > last_end:
                plain = text[last_end:start]
                if plain:
                    run = paragraph.add_run(plain)
                    run.font.size = Pt(10)
                    run.font.name = 'Calibri'

            if match.group(2):  # bold+italic
                run = paragraph.add_run(match.group(2))
                run.font.bold = True
                run.font.italic = True
                run.font.size = Pt(10)
                run.font.name = 'Calibri'
            elif match.group(4):  # bold
                run = paragraph.add_run(match.group(4))
                run.font.bold = True
                run.font.size = Pt(10)
                run.font.name = 'Calibri'
            elif match.group(6):  # italic
                run = paragraph.add_run(match.group(6))
                run.font.italic = True
                run.font.size = Pt(10)
                run.font.name = 'Calibri'
            elif match.group(8):  # inline code
                run = paragraph.add_run(match.group(8))
                run.font.name = 'Consolas'
                run.font.size = Pt(9)
                run.font.color.rgb = RGBColor(192, 57, 43)
            elif match.group(10):  # link
                link_text = match.group(10)
                link_url = match.group(11)
                run = paragraph.add_run(f"{link_text} ({link_url})")
                run.font.size = Pt(10)
                run.font.color.rgb = RGBColor(41, 128, 185)
                run.font.underline = True
                run.font.name = 'Calibri'
            elif match.group(13):  # strikethrough
                run = paragraph.add_run(match.group(13))
                run.font.strike = True
                run.font.size = Pt(10)
                run.font.name = 'Calibri'

            last_end = match.end()

        # Add remaining plain text
        if last_end < len(text):
            remaining = text[last_end:]
            if remaining:
                run = paragraph.add_run(remaining)
                run.font.size = Pt(10)
                run.font.name = 'Calibri'

    # ─── Section Divider ──────────────────────────────────────────────────

    def _add_section_divider(self):
        p = self.doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        pPr = p._p.get_or_add_pPr()
        pBdr = parse_xml(
            f'<w:pBdr {nsdecls("w")}>'
            f'  <w:bottom w:val="single" w:sz="12" w:space="1" '
            f'w:color="{self.theme.primary}"/>'
            f'</w:pBdr>'
        )
        pPr.append(pBdr)

    # ─── Info Box ─────────────────────────────────────────────────────────

    def _add_info_box(self, text, bg_color=None, border_color=None,
                      text_color=None):
        bg_color = bg_color or "D4E6F1"
        border_color = border_color or self.theme.primary
        text_color = text_color or RGBColor(*self.theme.primary_rgb)

        table = self.doc.add_table(rows=1, cols=1)
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        cell = table.rows[0].cells[0]
        self._set_cell_shading(cell, bg_color)
        self._set_cell_border(cell,
                              top={"val": "single", "sz": "8", "color": border_color},
                              bottom={"val": "single", "sz": "8", "color": border_color},
                              left={"val": "single", "sz": "8", "color": border_color},
                              right={"val": "single", "sz": "8", "color": border_color})
        cell.text = ""
        for i, line in enumerate(text.split("\n")):
            p = cell.paragraphs[0] if i == 0 else cell.add_paragraph()
            self._add_formatted_text(p, line)
            for run in p.runs:
                run.font.color.rgb = text_color
                if i == 0:
                    run.font.bold = True
        self.doc.add_paragraph()

    # ─── Token Rendering ─────────────────────────────────────────────────

    def render(self, tokens: List[Token], source_text: str = "") -> Document:
        """Render all tokens into the document."""
        # Extract metadata for cover page
        self._extract_metadata(tokens, source_text)

        # Create cover page
        self._create_cover_page()

        # Render each token
        for token in tokens:
            self._render_token(token)

        # Add header/footer
        self._add_header_footer()

        return self.doc

    def _extract_metadata(self, tokens: List[Token], source_text: str):
        """Extract document title, subtitle, and metadata from tokens."""
        for token in tokens:
            if token.type == TokenType.HEADING and token.level == 1:
                self._document_title = token.content
                break

        for token in tokens:
            if token.type == TokenType.HEADING and token.level == 2:
                self._document_subtitle = token.content
                break
            if token.type == TokenType.HEADING and token.level == 3:
                self._document_subtitle = token.content
                break

        # Try to extract key-value metadata from the first table
        # (commonly "Document Control" table)
        for token in tokens:
            if token.type == TokenType.TABLE:
                td = token.metadata.get('table_data')
                if td and len(td.headers) == 2:
                    header_lower = [h.lower().strip() for h in td.headers]
                    if any(k in header_lower[0] for k in ['field', 'key', 'property', 'attribute']):
                        for row in td.rows:
                            if len(row) >= 2:
                                key = re.sub(r'\*\*', '', row[0]).strip()
                                val = re.sub(r'\*\*', '', row[1]).strip()
                                self._document_metadata[key] = val
                        break

    def _create_cover_page(self):
        """Generate a professional cover page."""
        for _ in range(4):
            self.doc.add_paragraph()

        # Title
        if self._document_title:
            p = self.doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            run = p.add_run(re.sub(r'\*\*', '', self._document_title))
            run.font.size = Pt(28)
            run.font.bold = True
            run.font.color.rgb = RGBColor(*self.theme.primary_rgb)
            run.font.name = 'Calibri'

        # Subtitle
        if self._document_subtitle:
            p = self.doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            run = p.add_run(re.sub(r'\*\*', '', self._document_subtitle))
            run.font.size = Pt(16)
            run.font.color.rgb = RGBColor.from_string(self.theme.text_light)
            run.font.name = 'Calibri'

        self.doc.add_paragraph()

        # Divider
        p = self.doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run("━" * 50)
        run.font.color.rgb = RGBColor(*self.theme.primary_rgb)
        run.font.size = Pt(12)

        self.doc.add_paragraph()

        # Metadata from first table
        if self._document_metadata:
            display_fields = [
                'Document ID', 'Project Name', 'Version', 'Status',
                'Classification', 'Created By', 'Created Date'
            ]
            meta_items = []
            for field_name in display_fields:
                for key, val in self._document_metadata.items():
                    if field_name.lower() in key.lower():
                        meta_items.append((key, val))
                        break

            if not meta_items:
                # Fallback: show first 7 items
                meta_items = list(self._document_metadata.items())[:7]

            if meta_items:
                info_table = self.doc.add_table(rows=len(meta_items), cols=2)
                info_table.alignment = WD_TABLE_ALIGNMENT.CENTER
                for i, (label, value) in enumerate(meta_items):
                    row = info_table.rows[i]
                    cell_l = row.cells[0]
                    cell_l.text = ""
                    cell_l.width = Inches(2.5)
                    p = cell_l.paragraphs[0]
                    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
                    run = p.add_run(label + ":")
                    run.font.size = Pt(11)
                    run.font.bold = True
                    run.font.color.rgb = RGBColor(*self.theme.primary_rgb)
                    run.font.name = 'Calibri'

                    cell_r = row.cells[1]
                    cell_r.text = ""
                    cell_r.width = Inches(3.5)
                    p = cell_r.paragraphs[0]
                    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
                    run = p.add_run("  " + value)
                    run.font.size = Pt(11)
                    run.font.color.rgb = RGBColor.from_string(self.theme.text_light)
                    run.font.name = 'Calibri'

        self.doc.add_page_break()

    def _render_token(self, token: Token):
        """Dispatch rendering based on token type."""
        handlers = {
            TokenType.HEADING: self._render_heading,
            TokenType.PARAGRAPH: self._render_paragraph,
            TokenType.TABLE: self._render_table,
            TokenType.UNORDERED_LIST: self._render_unordered_list,
            TokenType.ORDERED_LIST: self._render_ordered_list,
            TokenType.CHECKLIST: self._render_checklist,
            TokenType.CODE_BLOCK: self._render_code_block,
            TokenType.HORIZONTAL_RULE: self._render_horizontal_rule,
            TokenType.BLOCKQUOTE: self._render_blockquote,
        }
        handler = handlers.get(token.type)
        if handler:
            handler(token)

    def _render_heading(self, token: Token):
        """Render a heading with appropriate level and styling."""
        level = min(token.level, 4)  # Max heading level 4 in python-docx styles
        clean_text = re.sub(r'\*\*', '', token.content)

        # For top-level headings, add a visual separator
        if level <= 2:
            self._add_section_divider()

        heading = self.doc.add_heading(level=level)
        self._add_formatted_text(heading, clean_text)
        # Override formatting to match theme
        for run in heading.runs:
            run.font.color.rgb = RGBColor(*self.theme.primary_rgb)
            run.font.bold = True
            run.font.name = 'Calibri'

    def _render_paragraph(self, token: Token):
        """Render a paragraph with inline formatting."""
        p = self.doc.add_paragraph()
        self._add_formatted_text(p, token.content)

    def _render_table(self, token: Token):
        """Render a table with professional styling."""
        td: TableData = token.metadata.get('table_data')
        if not td:
            return

        num_cols = len(td.headers)
        num_rows = len(td.rows)

        table = self.doc.add_table(rows=1 + num_rows, cols=num_cols)
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        table.autofit = True

        # Determine if this is a key-value table (2 columns, first is label-like)
        is_kv_table = (num_cols == 2 and
                       any(kw in td.headers[0].lower()
                           for kw in ['field', 'key', 'property', 'metric',
                                      'attribute', 'criterion', 'aspect',
                                      'review', 'exception', 'document',
                                      'overall']))

        # Determine header color based on content heuristics
        header_color = self.theme.bg_header
        header_text_lower = ' '.join(td.headers).lower()
        if any(kw in header_text_lower for kw in ['bug', 'defect', 'gap', 'not ready',
                                                   'anti-pattern', 'risk']):
            header_color = "C0392B"
        elif any(kw in header_text_lower for kw in ['spike', 'research', 'exception',
                                                     'warning']):
            header_color = "F39C12"
        elif any(kw in header_text_lower for kw in ['success', 'ready', 'best practice',
                                                     'achievement']):
            header_color = "27AE60"

        self._set_table_borders(table, color=header_color)

        # Header row
        hdr = table.rows[0]
        for i, header_text in enumerate(td.headers):
            cell = hdr.cells[i]
            cell.text = ""
            p = cell.paragraphs[0]
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            clean_header = re.sub(r'\*\*', '', header_text)
            run = p.add_run(clean_header)
            run.font.size = Pt(9)
            run.font.bold = True
            run.font.color.rgb = RGBColor(255, 255, 255)
            run.font.name = 'Calibri'
            self._set_cell_shading(cell, header_color)
            cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER

        # Data rows
        for r_idx, row_data in enumerate(td.rows):
            row = table.rows[1 + r_idx]
            for c_idx in range(num_cols):
                cell = row.cells[c_idx]
                cell_text = row_data[c_idx] if c_idx < len(row_data) else ""
                cell.text = ""
                p = cell.paragraphs[0]
                cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER

                # Clean and format cell text
                clean_text = cell_text.strip()

                # Detect special cell content
                if clean_text in ('✅', '✅ Yes', '✓'):
                    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                    run = p.add_run('✅')
                    run.font.size = Pt(10)
                elif clean_text in ('❌', '❌ No', '✗'):
                    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                    run = p.add_run('❌')
                    run.font.size = Pt(10)
                elif clean_text.startswith('☐') or clean_text.startswith('☑'):
                    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                    run = p.add_run(clean_text)
                    run.font.size = Pt(10)
                else:
                    self._add_formatted_text(p, clean_text)
                    for run in p.runs:
                        run.font.size = Pt(9)
                        run.font.name = 'Calibri'
                        run.font.color.rgb = RGBColor.from_string(self.theme.text_dark)

                    # Bold first column in key-value tables
                    if is_kv_table and c_idx == 0:
                        for run in p.runs:
                            run.font.bold = True
                            run.font.color.rgb = RGBColor(*self.theme.primary_rgb)

                # Alternating row shading
                if r_idx % 2 == 1:
                    self._set_cell_shading(cell, self.theme.bg_alt_row)

        self.doc.add_paragraph()  # spacing after table

    def _render_unordered_list(self, token: Token):
        """Render an unordered list."""
        for item in token.children:
            p = self.doc.add_paragraph(style='List Bullet')
            self._add_formatted_text(p, item)

    def _render_ordered_list(self, token: Token):
        """Render an ordered list."""
        for i, item in enumerate(token.children, 1):
            p = self.doc.add_paragraph()
            p.paragraph_format.left_indent = Inches(0.3)
            run = p.add_run(f"{i}. ")
            run.font.bold = True
            run.font.size = Pt(10)
            run.font.color.rgb = RGBColor(*self.theme.primary_rgb)
            run.font.name = 'Calibri'
            self._add_formatted_text(p, item)

    def _render_checklist(self, token: Token):
        """Render a checklist with checkbox symbols."""
        for item in token.children:
            p = self.doc.add_paragraph()
            p.paragraph_format.left_indent = Inches(0.3)

            if item['checked']:
                run = p.add_run("☑ ")
                run.font.color.rgb = RGBColor(39, 174, 96)
            else:
                run = p.add_run("☐ ")
                run.font.color.rgb = RGBColor.from_string(self.theme.text_muted)
            run.font.size = Pt(11)
            run.font.name = 'Calibri'

            self._add_formatted_text(p, item['text'])

    def _render_code_block(self, token: Token):
        """Render a code block in a styled box.

        Diagram blocks (is_diagram=True) get a distinct teal-border dark-bg style
        and a "DIAGRAM / ACTIVITY FLOW" caption so they visually stand out.
        Regular code blocks keep the left-blue-stripe code style.
        """
        lang = token.metadata.get('language', '')
        is_diagram = token.metadata.get('is_diagram', False)

        table = self.doc.add_table(rows=1, cols=1)
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        cell = table.rows[0].cells[0]

        if is_diagram:
            # Dark-warm-grey background, teal left border for diagrams
            bg_color = "2C3E50"   # dark navy-grey
            border_color = "1ABC9C"  # teal/mint accent
            self._set_cell_shading(cell, bg_color)
            self._set_cell_border(
                cell,
                top={"val": "single", "sz": "4", "color": border_color},
                bottom={"val": "single", "sz": "4", "color": border_color},
                left={"val": "single", "sz": "12", "color": border_color},
                right={"val": "single", "sz": "4", "color": border_color},
            )
            font_color = RGBColor(0xEC, 0xF0, 0xF1)   # near-white
            font_size = Pt(8)
            label = "ACTIVITY FLOW / DIAGRAM"
        else:
            # Light grey background, blue left stripe for code
            bg_color = "F4F6F7"
            border_color = self.theme.primary
            self._set_cell_shading(cell, bg_color)
            self._set_cell_border(
                cell,
                top={"val": "single", "sz": "4", "color": self.theme.border},
                bottom={"val": "single", "sz": "4", "color": self.theme.border},
                left={"val": "single", "sz": "8", "color": border_color},
                right={"val": "single", "sz": "4", "color": self.theme.border},
            )
            font_color = RGBColor.from_string(self.theme.text_dark)
            font_size = Pt(8)
            label = lang.upper() if lang else ''

        cell.text = ""

        # Optional label line (language or diagram type)
        if label:
            p = cell.paragraphs[0]
            run = p.add_run(label)
            run.font.size = Pt(7)
            run.font.bold = True
            run.font.color.rgb = RGBColor.from_string(self.theme.text_muted) if not is_diagram \
                else RGBColor(0x1A, 0xBC, 0x9C)
            run.font.name = 'Consolas'
            p = cell.add_paragraph()
        else:
            p = cell.paragraphs[0]

        # Content lines
        for i, line in enumerate(token.content.split('\n')):
            if i > 0:
                p = cell.add_paragraph()
            run = p.add_run(line)
            run.font.name = 'Consolas'
            run.font.size = font_size
            run.font.color.rgb = font_color

        self.doc.add_paragraph()

    def _render_horizontal_rule(self, token: Token):
        """Render a horizontal rule / section divider."""
        self._add_section_divider()

    def _render_blockquote(self, token: Token):
        """Render a blockquote in a styled box."""
        self._add_info_box(
            token.content,
            bg_color="EBF5FB",
            border_color=self.theme.secondary,
            text_color=RGBColor(*self.theme.primary_rgb)
        )

    # ─── Header / Footer ─────────────────────────────────────────────────

    def _add_header_footer(self):
        """Add professional header and footer."""
        doc_id = self._document_metadata.get('Document ID', '')
        title_short = self._document_title[:50] if self._document_title else 'Document'
        classification = self._document_metadata.get('Classification', 'Internal')

        for section in self.doc.sections:
            # Header
            header = section.header
            header.is_linked_to_previous = False
            p = header.paragraphs[0] if header.paragraphs else header.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.RIGHT

            header_parts = []
            if doc_id:
                header_parts.append(doc_id)
            header_parts.append(re.sub(r'\*\*', '', title_short))
            if classification:
                header_parts.append(classification)
            header_text = '  |  '.join(header_parts)

            run = p.add_run(header_text)
            run.font.size = Pt(7)
            run.font.color.rgb = RGBColor.from_string(self.theme.text_muted)
            run.font.name = 'Calibri'

            # Footer
            footer = section.footer
            footer.is_linked_to_previous = False
            p = footer.paragraphs[0] if footer.paragraphs else footer.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            run = p.add_run("Page ")
            run.font.size = Pt(8)
            run.font.color.rgb = RGBColor.from_string(self.theme.text_muted)
            run.font.name = 'Calibri'

            # Page number field
            fldChar1 = parse_xml(
                f'<w:fldChar {nsdecls("w")} w:fldCharType="begin"/>')
            run._r.append(fldChar1)
            instrText = parse_xml(
                f'<w:instrText {nsdecls("w")} xml:space="preserve"> PAGE </w:instrText>')
            run._r.append(instrText)
            fldChar2 = parse_xml(
                f'<w:fldChar {nsdecls("w")} w:fldCharType="end"/>')
            run._r.append(fldChar2)

            version = self._document_metadata.get('Version', '')
            project = self._document_metadata.get('Project Name', '')
            footer_extra_parts = []
            if version:
                footer_extra_parts.append(f"v{version}")
            if project:
                footer_extra_parts.append(project)

            if footer_extra_parts:
                run2 = p.add_run("  |  " + '  |  '.join(footer_extra_parts))
                run2.font.size = Pt(8)
                run2.font.color.rgb = RGBColor.from_string(self.theme.text_muted)
                run2.font.name = 'Calibri'

    def save(self, filepath: str):
        """Save the document to a file."""
        self.doc.save(filepath)


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN CONVERTER FUNCTION
# ═══════════════════════════════════════════════════════════════════════════════

def convert_llm_output_to_docx(
    markdown_text: str,
    output_path: str = None,
    theme: DocumentTheme = None
) -> str:
    """
    Convert LLM markdown output to a professionally formatted DOCX document.

    Args:
        markdown_text: The raw markdown text from LLM output.
        output_path: Optional output file path. Auto-generated if not provided.
        theme: Optional DocumentTheme for custom styling.

    Returns:
        The path to the generated DOCX file.
    """
    # Auto-generate filename if not provided
    if not output_path:
        # Try to extract a meaningful filename from content
        title_match = re.search(r'^#\s+(.+)$', markdown_text, re.MULTILINE)
        if title_match:
            title_clean = re.sub(r'[^\w\s-]', '', title_match.group(1))
            title_clean = re.sub(r'\s+', '_', title_clean.strip())[:50]
            output_path = f"{title_clean}_Document.docx"
        else:
            output_path = "LLM_Output_Document.docx"

    print("=" * 60)
    print("  LLM Output → Professional DOCX Converter")
    print("=" * 60)
    print()

    # Parse
    print("[1/3] Parsing markdown content...")
    parser = MarkdownParser(markdown_text)
    tokens = parser.parse()
    print(f"      Parsed {len(tokens)} content blocks")

    # Count token types for summary
    type_counts = {}
    for t in tokens:
        type_name = t.type.name
        type_counts[type_name] = type_counts.get(type_name, 0) + 1

    for ttype, count in sorted(type_counts.items()):
        print(f"        • {ttype}: {count}")

    # Render
    print("[2/3] Rendering document...")
    renderer = DocxRenderer(theme=theme or DEFAULT_THEME)
    renderer.render(tokens, source_text=markdown_text)

    # Save
    print(f"[3/3] Saving to: {output_path}")
    renderer.save(output_path)

    file_size = os.path.getsize(output_path)
    print()
    print("=" * 60)
    print(f"  ✅ Document generated successfully!")
    print(f"     File: {output_path}")
    print(f"     Size: {file_size / 1024:.1f} KB")
    print("=" * 60)

    return output_path


def convert_file(input_path: str, output_path: str = None, theme: DocumentTheme = None) -> str:
    """
    Read markdown from a file and convert to DOCX.

    Args:
        input_path: Path to the markdown file.
        output_path: Optional output path.
        theme: Optional document theme.

    Returns:
        Path to generated DOCX file.
    """
    with open(input_path, 'r', encoding='utf-8') as f:
        markdown_text = f.read()

    if not output_path:
        base = os.path.splitext(os.path.basename(input_path))[0]
        output_path = f"{base}.docx"

    return convert_llm_output_to_docx(markdown_text, output_path, theme)


# ═══════════════════════════════════════════════════════════════════════════════
# BATCH CONVERSION — ALL .md FILES IN FOLDER
# ═══════════════════════════════════════════════════════════════════════════════

def batch_convert_folder(folder_path: str, theme: DocumentTheme = None) -> None:
    """Convert every .md file in folder_path to a .docx beside it."""
    from pathlib import Path

    folder = Path(folder_path)
    if not folder.exists():
        print(f"[ERROR] Folder not found: {folder}")
        sys.exit(1)

    md_files = sorted(folder.rglob("*.md"))
    if not md_files:
        print(f"[INFO] No .md files found in: {folder}")
        return

    print(f"\n[BATCH] Found {len(md_files)} markdown file(s) in: {folder}\n")
    ok, failed = 0, 0

    for md_path in md_files:
        docx_path = str(md_path.with_suffix(".docx"))
        print(f"━━━ Processing: {md_path.name}")
        try:
            convert_file(str(md_path), docx_path, theme)
            ok += 1
        except Exception as exc:
            print(f"[FAILED] {md_path.name} → {exc}")
            failed += 1

    print(f"\n{'='*60}")
    print(f"  BATCH COMPLETE  ✅ Success: {ok}   ❌ Failed: {failed}")
    print(f"{'='*60}\n")


# ═══════════════════════════════════════════════════════════════════════════════
# NOTEBOOK (.ipynb) TEMPLATE CONVERTER
# ═══════════════════════════════════════════════════════════════════════════════

# ─── Slim-mode cell-classification helpers ───────────────────────────────────

_PROMPT_PATTERNS = re.compile(
    r'You are an expert|Your task is to generate|PRIMARY OBJECTIVE'
    r'|Generate a complete.*document|Fill every.*field|You must produce',
    re.IGNORECASE
)

_BOX_SET = frozenset(
    '\u2502\u250c\u2514\u2510\u2518\u2500\u252c\u2534\u251c\u2524\u253c'
    '\u25bc\u25b2\u25ba\u25c4\u2192\u2190\u2191\u2193'
)


def _nb_is_prompt_cell(source: str) -> bool:
    """True if cell is an LLM-instruction/prompt block (should be skipped)."""
    stripped = source.strip()
    # Starts with a 'Prompt :' heading
    if re.match(r'^Prompt\s*:', stripped, re.IGNORECASE):
        return True
    # Body contains LLM-instruction phrases
    if _PROMPT_PATTERNS.search(stripped):
        return True
    return False


def _nb_is_structural_cell(source: str) -> bool:
    """True if cell contains real document structure: tables, headings, banners."""
    has_table   = bool(re.search(r'^\|.+\|', source, re.MULTILINE))
    has_heading = bool(re.search(r'^#{1,6}\s+\S|^={4,}\s*$', source, re.MULTILINE))
    has_checklist = bool(re.search(r'^\s*[-*]\s+\[[ xX]\]', source, re.MULTILINE))
    return has_table or has_heading or has_checklist


def _nb_has_diagram_chars(source: str) -> bool:
    """True if cell contains ASCII box-drawing / flow diagram characters."""
    return any(c in source for c in _BOX_SET)


def _slim_filter_cells(cells_with_index):
    """
    Given a list of (cell_index, cell_type, source) tuples, return only
    the sources that belong in a slim template document.

    Rules:
      1. Skip cells that are LLM prompts (is_prompt=True).
      2. Skip cell 0 when it is pure explanation prose (no structure, no diagrams).
      3. If there are diagram-only cells (no structure but has box chars),
         keep them only if surrounded by structural cells (useful visual context).
      4. Skip any remaining pure-prose cells.
    """
    kept = []
    for i, cell_type, source in cells_with_index:
        if not source.strip():
            continue
        if _nb_is_prompt_cell(source):
            continue  # always drop prompt cells
        structural = _nb_is_structural_cell(source)
        has_diagram = _nb_has_diagram_chars(source)
        if i == 0 and not structural and not has_diagram:
            continue  # drop cell-0 pure explanation
        if structural or has_diagram:
            kept.append(source)
        # else: pure prose non-diagram cell — skip in slim mode
    return kept


def extract_notebook_markdown(nb_path: "Path", slim: bool = False) -> str:
    """
    Extract all cell sources from a Jupyter notebook (.ipynb) and return
    them as a single markdown string. Handles Windows MAX_PATH via robocopy.

    Args:
        nb_path: Path to the .ipynb file.
        slim:    When True, strip explanation prose and LLM prompt cells,
                 keeping only real document structure (tables, headings,
                 checklists, flow diagrams).
    """
    import json as _json, subprocess as _sp, tempfile as _tmp, shutil as _sh

    path_str = str(nb_path)
    tmp_dir  = None

    if sys.platform == "win32" and len(path_str) > 240:
        src_dir  = str(nb_path.parent)   # ~234 chars, within MAX_PATH
        src_file = nb_path.name
        tmp_dir  = _tmp.mkdtemp()
        # robocopy handles long-path sources (> MAX_PATH) natively
        r = _sp.run(
            ["robocopy", src_dir, tmp_dir, src_file,
             "/IS", "/IT", "/NFL", "/NDL", "/NJH", "/NJS"],
            capture_output=True, timeout=30
        )
        if r.returncode > 1:
            raise OSError(
                f"robocopy failed (code {r.returncode}) for: {src_file}\n"
                + r.stderr.decode(errors="replace")
            )
        read_path = os.path.join(tmp_dir, src_file)
    else:
        read_path = path_str

    try:
        try:
            with open(read_path, "r", encoding="utf-8") as fh:
                raw = fh.read()
        except UnicodeDecodeError:
            with open(read_path, "r", encoding="utf-8-sig") as fh:
                raw = fh.read()
    finally:
        if tmp_dir:
            _sh.rmtree(tmp_dir, ignore_errors=True)

    nb = _json.loads(raw)

    # Build (index, cell_type, source) list
    raw_cells = []
    for i, cell in enumerate(nb.get("cells", [])):
        cell_type = cell.get("cell_type", "")
        source    = "".join(cell.get("source", []))
        if source.strip():
            raw_cells.append((i, cell_type, source))

    if slim:
        # Filter to structural / diagram content only
        kept_sources = _slim_filter_cells(raw_cells)
        return "\n\n".join(kept_sources)

    # Full mode — include everything (markdown, code, raw)
    parts = []
    code_lang = nb.get("metadata", {}).get("kernelspec", {}).get("language", "python")
    for _i, cell_type, source in raw_cells:
        if cell_type == "markdown":
            parts.append(source)
        elif cell_type == "code":
            parts.append(f"```{code_lang}\n{source}\n```")
        elif cell_type == "raw":
            parts.append(source)

    return "\n\n".join(parts)


def batch_convert_templates(workspace_root: str, output_folder_name: str = "Project_Templates",
                            theme: DocumentTheme = None, slim: bool = False) -> None:
    """
    Search workspace_root recursively for every *template*.ipynb file,
    extract its content, convert to .docx, and save in output_folder_name
    (created directly inside workspace_root).

    Args:
        slim: When True, strip explanation prose and LLM prompts so the
              DOCX contains only essential document structure.
    """
    from pathlib import Path
    import fnmatch

    root = Path(workspace_root)
    if not root.exists():
        print(f"[ERROR] Workspace root not found: {root}")
        sys.exit(1)

    # Find all *template*.ipynb (case-insensitive) across all sub-folders
    all_ipynb = list(root.rglob("*.ipynb"))
    template_files = [
        p for p in all_ipynb
        if fnmatch.fnmatch(p.name.lower(), "*template*")
    ]

    if not template_files:
        print(f"[INFO] No template notebooks found under: {root}")
        return

    output_dir = root / output_folder_name
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*60}")
    print(f"  NOTEBOOK TEMPLATE -> DOCX CONVERTER")
    print(f"{'='*60}")
    mode_label = "SLIM (essential content only)" if slim else "FULL"
    print(f"  Found {len(template_files)} template notebook(s)")
    print(f"  Mode  : {mode_label}")
    print(f"  Output folder: {output_dir}")
    print(f"{'='*60}\n")

    ok, failed, skipped = 0, 0, 0
    TIMEOUT_S = 180   # max seconds per notebook before we skip it

    for nb_path in sorted(template_files):
        # Build a clean output filename from the notebook name
        clean_name = re.sub(r'[_\-]+', '_', nb_path.stem)
        clean_name = re.sub(r'(?i)_?template_?', '', clean_name).strip('_')
        docx_name = f"{clean_name}_Template.docx"
        docx_path = output_dir / docx_name

        print(f"\n=== {nb_path.name}")
        print(f"    Folder : {nb_path.parent.name}")
        print(f"    Output : {docx_name}")

        # Run the conversion in a thread so we can time-box it
        import concurrent.futures as _cf

        def _convert_one(nb_p=nb_path, docx_p=docx_path, th=theme, _slim=slim):
            md = extract_notebook_markdown(nb_p, slim=_slim)
            if not md.strip():
                return "empty"
            convert_llm_output_to_docx(md, str(docx_p), th)
            return "ok"

        with _cf.ThreadPoolExecutor(max_workers=1) as _pool:
            _fut = _pool.submit(_convert_one)
            try:
                result = _fut.result(timeout=TIMEOUT_S)
                if result == "empty":
                    print(f"    [SKIP] Notebook is empty.\n")
                    skipped += 1
                else:
                    ok += 1
            except _cf.TimeoutError:
                print(f"    [TIMEOUT] Skipped - took > {TIMEOUT_S}s to convert.\n")
                skipped += 1
            except Exception as exc:
                print(f"    [FAILED] {exc}\n")
                failed += 1

    print(f"\n{'='*60}")
    print(f"  BATCH COMPLETE  OK:{ok}  SKIP:{skipped}  FAIL:{failed}")
    print(f"  All .docx files saved in: {output_dir}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    WORKSPACE = (
        r"c:\Users\rahim.shaikh\My_Work\Practice_work\My_Project\Python_AI_ML"
        r"\timepass\Test_Project\hacakthon_project"
        r"\hackathon_Prompt+Sample_Docs+Template_to_follow"
    )

    import argparse as _argparse
    _parser = _argparse.ArgumentParser(description="LLM Output -> DOCX converter")
    _parser.add_argument("--md-only",  action="store_true", help="Only convert .md files")
    _parser.add_argument("--nb-only",  action="store_true", help="Only convert template notebooks")
    _parser.add_argument("--slim",     action="store_true",
                         help="Strip explanation prose and LLM prompts; keep only essential document structure")
    _args, _ = _parser.parse_known_args()

    run_md = not _args.nb_only
    run_nb = not _args.md_only
    slim   = _args.slim

    # Slim mode outputs to a separate folder so both versions are preserved
    nb_out_folder = "Project_Templates_Slim" if slim else "Project_Templates"

    # 1. Convert all .md files in "Test_Creation docx from llm output"
    if run_md:
        SOURCE_FOLDER = WORKSPACE + r"\Test_Creation docx from llm output"
        batch_convert_folder(SOURCE_FOLDER)

    # 2. Convert all *template*.ipynb files
    if run_nb:
        batch_convert_templates(WORKSPACE, output_folder_name=nb_out_folder, slim=slim)
