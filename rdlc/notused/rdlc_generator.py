from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Iterator
from xml.sax.saxutils import escape


RD_NS = "http://schemas.microsoft.com/sqlserver/reporting/2008/01/reportdefinition"
RD_DESIGNER = "http://schemas.microsoft.com/SQLServer/reporting/reportdesigner"


def text_json_dir(base: Path | None = None) -> Path:
    """Folder containing JSON specs (default: ``text_json`` next to this script)."""
    root = base if base is not None else Path(__file__).resolve().parent
    return root / "text_json"


def xml_output_dir(base: Path | None = None) -> Path:
    """Folder for generated XML (default: ``XML_file`` next to this script)."""
    root = base if base is not None else Path(__file__).resolve().parent
    return root / "XML_file"


def list_text_json_files(json_dir: Path | None = None, base: Path | None = None) -> list[Path]:
    """
    Every JSON file placed directly in ``text_json`` (or ``json_dir``).

    Picks up all ``*.json`` names (case-insensitive), sorted alphabetically.
    Each file is processed separately; output XML uses the same stem as the JSON file.
    """
    d = (text_json_dir(base) if json_dir is None else Path(json_dir)).expanduser().resolve()
    if not d.is_dir():
        return []
    found = [p for p in d.iterdir() if p.is_file() and p.suffix.lower() == ".json"]
    return sorted(found, key=lambda p: p.name.lower())


def load_text_json(path: Path, encoding: str = "utf-8") -> dict[str, Any]:
    """Load one JSON spec file."""
    raw = path.read_text(encoding=encoding)
    if not raw.strip():
        raise ValueError(f"Empty file: {path}")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise TypeError(f"Expected JSON object in {path}, got {type(data).__name__}")
    return data


def iter_text_json_specs(json_dir: Path | None = None, base: Path | None = None) -> Iterator[tuple[Path, dict[str, Any]]]:
    """Yield ``(path, spec)`` for every JSON file in ``text_json``."""
    for path in list_text_json_files(json_dir, base=base):
        yield path, load_text_json(path)


def _safe_report_item_name(name: str) -> str:
    """RDLC names should be simple identifiers."""
    s = re.sub(r"[^\w]", "_", name or "Textbox")
    if s and s[0].isdigit():
        s = "N" + s
    return s or "Textbox"


def _text_run_xml(run: dict[str, Any]) -> str:
    val = escape(str(run.get("value", "")))
    fw = run.get("font_weight")
    style = ""
    if fw:
        style = f"<Style><FontWeight>{escape(str(fw))}</FontWeight></Style>"
    return f"<TextRun><Value>{val}</Value>{style}</TextRun>"


def _paragraphs_xml(tb: dict[str, Any]) -> str:
    paras = tb.get("paragraphs")
    if not isinstance(paras, list) or not paras:
        return (
            "<Paragraphs><Paragraph><TextRuns>"
            "<TextRun><Value /></TextRun>"
            "</TextRuns></Paragraph></Paragraphs>"
        )
    parts: list[str] = []
    for para in paras:
        if not isinstance(para, dict):
            continue
        runs = para.get("runs")
        if not isinstance(runs, list):
            runs = []
        trs = "".join(_text_run_xml(r) for r in runs if isinstance(r, dict))
        if not trs:
            trs = "<TextRun><Value /></TextRun>"
        parts.append(f"<Paragraph><TextRuns>{trs}</TextRuns></Paragraph>")
    if not parts:
        return (
            "<Paragraphs><Paragraph><TextRuns>"
            "<TextRun><Value /></TextRun>"
            "</TextRuns></Paragraph></Paragraphs>"
        )
    return f"<Paragraphs>{''.join(parts)}</Paragraphs>"


def _textbox_paragraphs_indented(tb: dict[str, Any]) -> str:
    raw = _paragraphs_xml(tb)
    return "\n".join("      " + line if line.strip() else line for line in raw.splitlines())


def _textbox_element(tb: dict[str, Any]) -> str:
    name = _safe_report_item_name(str(tb.get("name", "Textbox")))
    default_name = escape(str(tb.get("default_name", name)))
    border_style = escape(str(tb.get("border_style", "None")))
    z = tb.get("zindex")
    z_el = f"<ZIndex>{int(z)}</ZIndex>" if isinstance(z, int) else ""

    top = escape(str(tb.get("top", "0in")))
    left = escape(str(tb.get("left", "0in")))
    height = escape(str(tb.get("height", "0.25in")))
    width = escape(str(tb.get("width", "1in")))

    return f"""    <Textbox Name="{escape(name)}">
      <CanGrow>true</CanGrow>
      <KeepTogether>true</KeepTogether>
{_textbox_paragraphs_indented(tb)}
      <rd:DefaultName>{default_name}</rd:DefaultName>
      <Top>{top}</Top>
      <Left>{left}</Left>
      <Height>{height}</Height>
      <Width>{width}</Width>
      {z_el}
      <Style>
        <Border>
          <Style>{border_style}</Style>
        </Border>
      </Style>
    </Textbox>"""


def _header_report_items(header: dict[str, Any]) -> str:
    items: list[str] = []
    hotel = str(header.get("hotel_name", ""))
    if hotel.strip():
        tb = {
            "name": "HeaderHotelName",
            "default_name": "HeaderHotelName",
            "top": header.get("hotel_name_top", "0cm"),
            "left": header.get("hotel_name_left", "0cm"),
            "height": header.get("hotel_name_height", "0.5cm"),
            "width": header.get("hotel_name_width", "10cm"),
            "border_style": "None",
            "paragraphs": [{"runs": [{"value": hotel}]}],
        }
        items.append(_textbox_element(tb))
    lines = header.get("address_lines")
    if isinstance(lines, list) and any(str(x).strip() for x in lines):
        addr = "\n".join(str(x) for x in lines)
        tb = {
            "name": "HeaderAddress",
            "default_name": "HeaderAddress",
            "top": header.get("address_top", "0cm"),
            "left": header.get("address_left", "0cm"),
            "height": header.get("address_height", "1cm"),
            "width": header.get("address_width", "10cm"),
            "border_style": "None",
            "paragraphs": [{"runs": [{"value": addr}]}],
        }
        items.append(_textbox_element(tb))
    if not items:
        return ""
    return "\n".join(items) + "\n"


def spec_to_rdlc_xml(spec: dict[str, Any]) -> str:
    """Build RDLC-style XML (SSRS 2008 reportdefinition namespace) from the JSON spec."""
    report_width = escape(str(spec.get("report_width", "21cm")))
    body = spec.get("body") if isinstance(spec.get("body"), dict) else {}
    body_height = escape(str(body.get("height", "29.7cm")))

    page = spec.get("page") if isinstance(spec.get("page"), dict) else {}
    ph = escape(str(page.get("page_height", "29.7cm")))
    pw = escape(str(page.get("page_width", "21cm")))
    lm = escape(str(page.get("left_margin", "0cm")))
    rm = escape(str(page.get("right_margin", "0cm")))
    tm = escape(str(page.get("top_margin", "0cm")))
    bm = escape(str(page.get("bottom_margin", "0cm")))

    textboxes = body.get("textboxes")
    if not isinstance(textboxes, list):
        textboxes = []

    body_items = "\n".join(_textbox_element(tb) for tb in textboxes if isinstance(tb, dict))

    header = spec.get("header") if isinstance(spec.get("header"), dict) else {}
    header_height = escape(str(header.get("height", "0cm")))
    header_block = ""
    h_items = _header_report_items(header)
    if h_items.strip():
        header_block = f"""  <PageHeader>
    <Height>{header_height}</Height>
    <PrintOnFirstPage>true</PrintOnFirstPage>
    <PrintOnLastPage>true</PrintOnLastPage>
    <ReportItems>
{h_items}    </ReportItems>
  </PageHeader>
"""

    return f"""<?xml version="1.0" encoding="utf-8"?>
<Report xmlns="{RD_NS}" xmlns:rd="{RD_DESIGNER}">
  <AutoRefresh>0</AutoRefresh>
  {header_block}  <Body>
    <ReportItems>
{body_items}
    </ReportItems>
    <Height>{body_height}</Height>
    <Style />
  </Body>
  <Width>{report_width}</Width>
  <Page>
    <PageHeight>{ph}</PageHeight>
    <PageWidth>{pw}</PageWidth>
    <LeftMargin>{lm}</LeftMargin>
    <RightMargin>{rm}</RightMargin>
    <TopMargin>{tm}</TopMargin>
    <BottomMargin>{bm}</BottomMargin>
  </Page>
</Report>
"""


def write_spec_xml(spec: dict[str, Any], source_json: Path, output_dir: Path) -> Path:
    """Write ``<stem>.xml`` for the given spec into ``output_dir``."""
    output_dir.mkdir(parents=True, exist_ok=True)
    out = output_dir / f"{source_json.stem}.xml"
    out.write_text(spec_to_rdlc_xml(spec), encoding="utf-8")
    return out


def process_spec(spec: dict[str, Any], source: Path, output_dir: Path) -> Path:
    """Generate RDLC XML from spec and save under ``XML_file`` (or ``output_dir``)."""
    out = write_spec_xml(spec, source, output_dir)
    report_id = spec.get("report_id", "")
    body = spec.get("body")
    n_boxes = 0
    if isinstance(body, dict):
        tbs = body.get("textboxes")
        if isinstance(tbs, list):
            n_boxes = len(tbs)

    print(f"Loaded: {source.name}")
    print(f"  report_id: {report_id!r}")
    print(f"  textboxes: {n_boxes}")
    print(f"  XML: {out}")
    return out


def run_all(json_dir: Path | None = None, output_dir: Path | None = None, base: Path | None = None) -> int:
    in_dir = (text_json_dir(base) if json_dir is None else Path(json_dir)).expanduser().resolve()
    out_root = (xml_output_dir(base) if output_dir is None else Path(output_dir)).expanduser().resolve()

    print(f"Scanning for *.json in: {in_dir}")
    paths = list_text_json_files(json_dir, base=base)
    if not paths:
        print(f"No JSON files found in {in_dir}")
        return 1

    print(f"Found {len(paths)} JSON file(s): {', '.join(p.name for p in paths)}")
    print(f"XML output folder: {out_root}")
    print()

    ok = 0
    for path in paths:
        try:
            spec = load_text_json(path)
        except (json.JSONDecodeError, OSError, TypeError, ValueError) as e:
            print(f"Skip {path.name}: {e}")
            continue
        process_spec(spec, path, out_root)
        ok += 1

    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Load every *.json in text_json/ and write RDLC-style XML to XML_file/."
    )
    parser.add_argument(
        "--json-dir",
        type=Path,
        default=None,
        help="Override input folder (default: text_json next to rdlc_generator.py)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Override output folder (default: XML_file next to rdlc_generator.py)",
    )
    args = parser.parse_args()
    return run_all(json_dir=args.json_dir, output_dir=args.output_dir)


if __name__ == "__main__":
    raise SystemExit(main())
