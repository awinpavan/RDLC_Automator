"""
text_xml_generator_Line_Text.py  (updated)
===========================================
Merges:
  • XML_file/core_rdlc_withoutTextbox.xml  – base RDLC skeleton
  • XML_file/textbox.xml                   – single-Textbox XML template
  • text_json/text.json                    – Textbox report items  (from text_parser.py)
  • text_json/line.json                    – Line report items     (from line_parser.py)
  • text_json/page.json                    – Page dimensions       (from text_parser.py)

Writes one .rdl per .json pair found in text_json/ into rdlc_generated/.

page.json expected schema
--------------------------
{
  "Page": {
    "PageHeight":    "29.69260cm",
    "PageWidth":     "21.00580cm",
    "LeftMargin":    "0.15cm",
    "RightMargin":   "0.15cm",
    "TopMargin":     "0.25cm",
    "BottomMargin":  "0.25cm",
    "ColumnSpacing": "0.13cm",
    "Style":         ""
  }
}
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape


# ═══════════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════════

def _script_dir() -> Path:
    return Path(__file__).resolve().parent


def _xml_text(s: str) -> str:
    return escape(str(s))


def _bool_xml(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    return "true" if str(v).lower() in ("1", "true", "yes") else "false"


# Minimum Textbox width (cm). Values below this are raised to this floor.
_MIN_TEXTBOX_WIDTH_CM = 0.86219


def _clamp_textbox_width_cm(width_raw: Any) -> str:
    s = str(width_raw).strip()
    m = re.match(r"^([0-9]+(?:\.[0-9]+)?)\s*cm\s*$", s, re.IGNORECASE)
    if not m:
        return s
    try:
        val = float(m.group(1))
    except ValueError:
        return s
    if val < _MIN_TEXTBOX_WIDTH_CM:
        return f"{_MIN_TEXTBOX_WIDTH_CM:.5f}cm"
    return s


# ═══════════════════════════════════════════════════════════════════
#  JSON loaders
# ═══════════════════════════════════════════════════════════════════

def load_report_items_from_json(path: Path) -> list[dict[str, Any]]:
    raw = path.read_text(encoding="utf-8")
    if not raw.strip():
        raise ValueError(f"Empty JSON: {path}")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise TypeError(f"Root must be an object: {path}")
    items = data.get("ReportItems")
    if items is None and isinstance(data.get("body"), dict):
        items = data["body"].get("textboxes")
    if not isinstance(items, list):
        raise KeyError(f"Expected top-level 'ReportItems' array in {path}")
    out: list[dict[str, Any]] = []
    for i, row in enumerate(items):
        if isinstance(row, dict):
            out.append(row)
        else:
            raise TypeError(f"ReportItems[{i}] must be an object in {path}")
    return out


def load_lines_from_json(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return []
    data = json.loads(raw)
    if not isinstance(data, dict):
        return []
    lines = data.get("Lines", [])
    if not isinstance(lines, list):
        return []
    return [row for row in lines if isinstance(row, dict)]


def load_page_from_json(path: Path) -> dict[str, str] | None:
    """
    Load page dimensions from page.json.
    Returns the inner 'Page' dict, or None if the file is absent/invalid.
    """
    if not path.is_file():
        return None
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    page = data.get("Page")
    if not isinstance(page, dict):
        return None
    return page


# ═══════════════════════════════════════════════════════════════════
#  Page XML rendering  (NEW)
# ═══════════════════════════════════════════════════════════════════

# Fallback defaults matching the original core XML
_DEFAULT_PAGE = {
    "PageHeight":    "29.7cm",
    "PageWidth":     "21cm",
    "LeftMargin":    "0.15cm",
    "RightMargin":   "0.15cm",
    "TopMargin":     "0.25cm",
    "BottomMargin":  "0.25cm",
    "ColumnSpacing": "0.13cm",
    "Style":         "",
}


def build_page_xml(page: dict[str, str] | None) -> str:
    """
    Render a full <Page>...</Page> XML block from page.json values.
    Falls back to _DEFAULT_PAGE for any missing key.
    """
    p = {**_DEFAULT_PAGE, **(page or {})}

    style_block = "        <Style />" if not p.get("Style") else f"        <Style>{_xml_text(p['Style'])}</Style>"

    return (
        "      <Page>\n"
        f"        <PageHeight>{_xml_text(p['PageHeight'])}</PageHeight>\n"
        f"        <PageWidth>{_xml_text(p['PageWidth'])}</PageWidth>\n"
        f"        <LeftMargin>{_xml_text(p['LeftMargin'])}</LeftMargin>\n"
        f"        <RightMargin>{_xml_text(p['RightMargin'])}</RightMargin>\n"
        f"        <TopMargin>{_xml_text(p['TopMargin'])}</TopMargin>\n"
        f"        <BottomMargin>{_xml_text(p['BottomMargin'])}</BottomMargin>\n"
        f"        <ColumnSpacing>{_xml_text(p['ColumnSpacing'])}</ColumnSpacing>\n"
        f"{style_block}\n"
        "      </Page>"
    )


def inject_page_into_xml(core_xml: str, page_block: str) -> str:
    """
    Replace the existing <Page>...</Page> block in core_xml with page_block.
    If none exists, insert it just after </Body>.
    """
    # Replace existing <Page> block
    replaced, count = re.subn(
        r"<Page>.*?</Page>",
        page_block,
        core_xml,
        count=1,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if count:
        return replaced

    # No existing <Page> — insert after </Body>
    return re.sub(
        r"(</Body>)",
        rf"\1\n{page_block}",
        core_xml,
        count=1,
        flags=re.IGNORECASE,
    )


# ═══════════════════════════════════════════════════════════════════
#  Textbox XML rendering
# ═══════════════════════════════════════════════════════════════════

_DEFAULT_TEXTBOX_TEMPLATE = """        <Textbox Name="Textbox5">
            <rd:DefaultName>Textbox2</rd:DefaultName>
            <CanGrow>true</CanGrow>
            <KeepTogether>true</KeepTogether>
            <Paragraphs>
              <Paragraph>
                <TextRuns>
                  <TextRun>
                    <Value>RESERVATION #</Value>
                    <Style>
                      <FontSize>7pt</FontSize>
                    </Style>
                  </TextRun>
                </TextRuns>
                <Style />
              </Paragraph>
            </Paragraphs>
            <Top>3.98451cm</Top>
            <Left>14.42529cm</Left>
            <Height>0.473cm</Height>
            <Width>2.35184cm</Width>
            <ZIndex>3</ZIndex>
            <Style>
              <Border>
                <Style>None</Style>
              </Border>
              <PaddingLeft>2pt</PaddingLeft>
              <PaddingRight>2pt</PaddingRight>
              <PaddingTop>2pt</PaddingTop>
              <PaddingBottom>2pt</PaddingBottom>
            </Style>
        </Textbox>"""


def extract_textbox_template(textbox_xml_path: Path) -> str:
    if not textbox_xml_path.is_file():
        return _DEFAULT_TEXTBOX_TEMPLATE
    text = textbox_xml_path.read_text(encoding="utf-8").lstrip("\ufeff").strip()
    if not text:
        return _DEFAULT_TEXTBOX_TEMPLATE
    m = re.search(r"<Textbox\b[^>]*>.*?</Textbox>", text, re.DOTALL | re.IGNORECASE)
    if not m:
        return _DEFAULT_TEXTBOX_TEMPLATE
    return m.group(0)


def render_textbox_from_item(item: dict[str, Any], template: str) -> str:
    name         = _xml_text(item.get("Name", "Textbox"))
    default_name = _xml_text(item.get("DefaultName", item.get("Name", "Textbox")))
    can_grow     = _bool_xml(item.get("CanGrow", True))
    keep_tog     = _bool_xml(item.get("KeepTogether", True))
    value        = _xml_text(item.get("Text", ""))
    font_size    = _xml_text(item.get("FontSize", "7pt"))
    is_bold      = item.get("IsBold")
    font_weight  = item.get("FontWeight")
    if font_weight is None and isinstance(is_bold, bool):
        font_weight = "Bold" if is_bold else "Normal"
    if font_weight is None:
        font_weight = "Normal"
    font_weight = _xml_text(str(font_weight))
    top    = _xml_text(item.get("Top",    "0cm"))
    left   = _xml_text(item.get("Left",   "0cm"))
    height = _xml_text(item.get("Height", "0.473cm"))
    width  = _xml_text(_clamp_textbox_width_cm(item.get("Width", "2cm")))
    border = _xml_text(item.get("Border", "None"))
    pad_l  = _xml_text(item.get("PaddingLeft",   "1pt"))
    pad_r  = _xml_text(item.get("PaddingRight",  "1pt"))
    pad_t  = _xml_text(item.get("PaddingTop",    "1pt"))
    pad_b  = _xml_text(item.get("PaddingBottom", "1pt"))

    z = item.get("ZIndex")
    z_line = f"\n            <ZIndex>{int(z)}</ZIndex>" if z is not None else ""

    block = template
    block = re.sub(r'Name="[^"]*"', f'Name="{name}"', block, count=1)
    block = re.sub(r"<rd:DefaultName>.*?</rd:DefaultName>",
                   f"<rd:DefaultName>{default_name}</rd:DefaultName>",
                   block, count=1, flags=re.DOTALL)
    block = re.sub(r"<CanGrow>.*?</CanGrow>",           f"<CanGrow>{can_grow}</CanGrow>",         block, count=1)
    block = re.sub(r"<KeepTogether>.*?</KeepTogether>", f"<KeepTogether>{keep_tog}</KeepTogether>", block, count=1)
    block = re.sub(r"<Value>.*?</Value>",               f"<Value>{value}</Value>",                block, count=1, flags=re.DOTALL)
    block = re.sub(r"<FontSize>.*?</FontSize>",         f"<FontSize>{font_size}</FontSize>",      block, count=1)

    if re.search(r"<FontWeight>.*?</FontWeight>", block):
        block = re.sub(r"<FontWeight>.*?</FontWeight>",
                       f"<FontWeight>{font_weight}</FontWeight>", block, count=1)
    else:
        block = re.sub(r"(<FontSize>.*?</FontSize>)",
                       rf"\1\n                      <FontWeight>{font_weight}</FontWeight>",
                       block, count=1, flags=re.DOTALL)

    block = re.sub(r"<Top>.*?</Top>",       f"<Top>{top}</Top>",          block, count=1)
    block = re.sub(r"<Left>.*?</Left>",     f"<Left>{left}</Left>",       block, count=1)
    block = re.sub(r"<Height>.*?</Height>", f"<Height>{height}</Height>", block, count=1)
    block = re.sub(r"<Width>.*?</Width>",   f"<Width>{width}</Width>",    block, count=1)

    if z is not None:
        if re.search(r"<ZIndex>\s*\d+\s*</ZIndex>", block):
            block = re.sub(r"<ZIndex>\s*\d+\s*</ZIndex>",
                           f"<ZIndex>{int(z)}</ZIndex>", block, count=1)
        else:
            block = re.sub(r"(</Width>)", rf"\1{z_line}", block, count=1)
    else:
        block = re.sub(r"\s*<ZIndex>\s*\d+\s*</ZIndex>\s*", "\n", block, count=1)

    block = re.sub(
        r"<Border>\s*<Style>.*?</Style>\s*</Border>",
        f"<Border>\n                <Style>{border}</Style>\n              </Border>",
        block, count=1, flags=re.DOTALL,
    )
    block = re.sub(r"<PaddingLeft>.*?</PaddingLeft>",     f"<PaddingLeft>{pad_l}</PaddingLeft>",     block, count=1)
    block = re.sub(r"<PaddingRight>.*?</PaddingRight>",   f"<PaddingRight>{pad_r}</PaddingRight>",   block, count=1)
    block = re.sub(r"<PaddingTop>.*?</PaddingTop>",       f"<PaddingTop>{pad_t}</PaddingTop>",       block, count=1)
    block = re.sub(r"<PaddingBottom>.*?</PaddingBottom>", f"<PaddingBottom>{pad_b}</PaddingBottom>", block, count=1)

    return block


# ═══════════════════════════════════════════════════════════════════
#  Line XML rendering
# ═══════════════════════════════════════════════════════════════════

def render_line_from_item(item: dict[str, Any]) -> str:
    name         = _xml_text(item.get("Name",        "Line1"))
    top          = _xml_text(item.get("Top",          "0cm"))
    left         = _xml_text(item.get("Left",         "0cm"))
    height       = _xml_text(item.get("Height",       "0cm"))
    width        = _xml_text(item.get("Width",        "0cm"))
    border_style = _xml_text(item.get("BorderStyle",  "Solid"))
    z            = item.get("ZIndex")
    z_block = f"\n            <ZIndex>{int(z)}</ZIndex>" if z is not None else ""

    return (
        f'          <Line Name="{name}">\n'
        f"            <Top>{top}</Top>\n"
        f"            <Left>{left}</Left>\n"
        f"            <Height>{height}</Height>\n"
        f"            <Width>{width}</Width>"
        f"{z_block}\n"
        f"            <Style>\n"
        f"              <Border>\n"
        f"                <Style>{border_style}</Style>\n"
        f"              </Border>\n"
        f"            </Style>\n"
        f"          </Line>"
    )


# ═══════════════════════════════════════════════════════════════════
#  Build combined <ReportItems> block
# ═══════════════════════════════════════════════════════════════════

def build_report_items_xml(
    textbox_items: list[dict[str, Any]],
    line_items:    list[dict[str, Any]],
    template:      str,
) -> str:
    blocks: list[str] = []

    for item in textbox_items:
        rendered = render_textbox_from_item(item, template)
        lines = []
        for line in rendered.strip().splitlines():
            lines.append("          " + line.lstrip())
        blocks.append("\n".join(lines))

    for item in line_items:
        blocks.append(render_line_from_item(item))

    inner = "\n".join(blocks)
    return f"        <ReportItems>\n{inner}\n        </ReportItems>"


# ═══════════════════════════════════════════════════════════════════
#  Core XML helpers
# ═══════════════════════════════════════════════════════════════════

def load_core_xml(core_path: Path) -> str:
    def _strip_reportitems(xml: str) -> str:
        return re.sub(
            r"(<Body>\s*)<ReportItems>.*?</ReportItems>\s*",
            r"\1",
            xml,
            count=1,
            flags=re.DOTALL | re.IGNORECASE,
        )

    if core_path.is_file() and core_path.stat().st_size > 50:
        s = core_path.read_text(encoding="utf-8").lstrip("\ufeff")
        return _strip_reportitems(s)

    alt = core_path.parent / "core_rdlc_withTextbox.xml"
    if alt.is_file() and alt.stat().st_size > 50:
        s = alt.read_text(encoding="utf-8").lstrip("\ufeff")
        stripped = _strip_reportitems(s)
        if stripped != s:
            return stripped

    raise ValueError(
        f"Core XML missing or empty: {core_path.resolve()}. "
        "Place core_rdlc_withoutTextbox.xml inside the XML_file/ folder."
    )


def inject_report_items_into_body(core_xml: str, report_items_block: str) -> str:
    m = re.search(
        r"(<Body>)(\s*)(<Height>.*?</Height>)",
        core_xml,
        re.DOTALL | re.IGNORECASE,
    )
    if not m:
        raise ValueError("Could not find <Body> ... <Height> in core XML")
    return (
        core_xml[: m.end(1)]
        + "\n"
        + report_items_block
        + m.group(2)
        + m.group(3)
        + core_xml[m.end():]
    )


def clear_output_dir(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for p in out_dir.iterdir():
        if p.is_file() and p.suffix.lower() == ".rdl":
            try:
                p.unlink()
            except OSError:
                pass


def list_json_files(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    return sorted(
        p for p in folder.iterdir()
        if p.is_file()
        and p.suffix.lower() == ".json"
        and p.name.lower() not in ("line.json", "page.json", "null_text.json","expressions.json","input.json","in_text.json")
    )


# ═══════════════════════════════════════════════════════════════════
#  Per-file generation
# ═══════════════════════════════════════════════════════════════════

def generate_rdl(
    textbox_items:     list[dict[str, Any]],
    line_items:        list[dict[str, Any]],
    page_dims:         dict[str, str] | None,
    core_path:         Path,
    textbox_tmpl_path: Path,
    out_path:          Path,
) -> None:
    core     = load_core_xml(core_path)
    template = extract_textbox_template(textbox_tmpl_path)

    # ── Inject <Page> block ────────────────────────────────────────
    page_block = build_page_xml(page_dims)
    core = inject_page_into_xml(core, page_block)

    # ── Inject <ReportItems> block ─────────────────────────────────
    ri_block = build_report_items_xml(textbox_items, line_items, template)
    full     = inject_report_items_into_body(core, ri_block)

    out_path.write_text(full, encoding="utf-8")


# ═══════════════════════════════════════════════════════════════════
#  main
# ═══════════════════════════════════════════════════════════════════

def main() -> int:
    root    = _script_dir()
    xml_dir = root / "XML_file"

    parser = argparse.ArgumentParser(
        description=(
            "Merge XML_file/core_rdlc_withoutTextbox.xml with Textboxes, Lines, "
            "and Page dimensions from text_json/; write .rdl to rdlc_generated/."
        )
    )
    parser.add_argument(
        "--core",
        type=Path,
        default=xml_dir / "core_rdlc_withoutTextbox.xml",
        help="Core RDLC XML (default: XML_file/core_rdlc_withoutTextbox.xml)",
    )
    parser.add_argument(
        "--textbox-template",
        type=Path,
        default=xml_dir / "textbox.xml",
        help="Textbox XML template (default: XML_file/textbox.xml)",
    )
    parser.add_argument(
        "--json-dir",
        type=Path,
        default=root / "text_json",
        help="Folder with text.json, line.json, page.json (default: text_json/)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=root / "rdlc_generated",
        help="Output folder for .rdl files (default: rdlc_generated/)",
    )
    parser.add_argument(
        "--line-json",
        type=Path,
        default=None,
        help="Explicit path to line.json (default: <json-dir>/line.json)",
    )
    parser.add_argument(
        "--page-json",
        type=Path,
        default=None,
        help="Explicit path to page.json (default: <json-dir>/page.json)",
    )
    args = parser.parse_args()

    core    = args.core.expanduser().resolve()
    tmpl    = args.textbox_template.expanduser().resolve()
    jdir    = args.json_dir.expanduser().resolve()
    out_dir = args.output_dir.expanduser().resolve()

    line_json_path = (
        args.line_json.expanduser().resolve() if args.line_json else jdir / "line.json"
    )
    page_json_path = (
        args.page_json.expanduser().resolve() if args.page_json else jdir / "page.json"
    )

    if not tmpl.is_file():
        print(f"Warning: textbox template not found at {tmpl} — using built-in default.")
    if not core.is_file():
        print(f"Warning: core XML not found at {core} — will try fallback.")

    # ── Load shared resources ──────────────────────────────────────
    line_items = load_lines_from_json(line_json_path)
    if line_items:
        print(f"Loaded {len(line_items)} line(s) from {line_json_path}")
    else:
        print(f"No line items loaded (line.json absent or empty at {line_json_path})")

    page_dims = load_page_from_json(page_json_path)
    if page_dims:
        print(f"Loaded page dimensions from {page_json_path}")
        print(f"  PageWidth  = {page_dims.get('PageWidth')}")
        print(f"  PageHeight = {page_dims.get('PageHeight')}")
    else:
        print(f"No page.json found at {page_json_path} — using default A4 dimensions.")

    json_files = list_json_files(jdir)
    if not json_files:
        print(f"No text .json files in {jdir}")
        return 1

    clear_output_dir(out_dir)

    for jp in json_files:
        out_file = out_dir / f"{jp.stem}.rdl"
        try:
            textbox_items = load_report_items_from_json(jp)
            generate_rdl(textbox_items, line_items, page_dims, core, tmpl, out_file)
            print(
                f"Wrote {out_file}  "
                f"({len(textbox_items)} textbox(es) + {len(line_items)} line(s) "
                f"+ page dims from {jp.name})"
            )
        except Exception as e:
            print(f"Failed {jp.name}: {e}")
            return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())