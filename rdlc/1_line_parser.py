"""
line_parser.py
==============
Extracts lines and table-border edges from a PDF using pdfplumber,
then writes line.json in a format compatible with the text_xml_generator.

Output JSON structure
---------------------
{
  "Lines": [
    {
      "Name": "Line1",
      "Top":    "9.23150cm",
      "Left":   "7.78087cm",
      "Height": "4.10633cm",   # non-zero  => vertical line
      "Width":  "0cm",         #   zero    => vertical line
      "ZIndex": 1,
      "BorderStyle": "Solid"
    },
    ...
  ]
}

A horizontal line  →  Height ≈ 0, Width  = length
A vertical   line  →  Width  ≈ 0, Height = length
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pdfplumber

# ── unit conversion ────────────────────────────────────────────────
_PT_TO_CM = 2.54 / 72.0          # 1 PDF point = 1/72 inch

# Two edges closer than this (in points) are considered the same line
_MERGE_TOL = 2.0

# Minimum rendered length (pt) – shorter segments are ignored
_MIN_LENGTH_PT = 6.0

_OUTPUT_NAME = "line.json"


def _fmt_cm(value: float) -> str:
    return f"{value:.5f}cm"


# ── geometry helpers ────────────────────────────────────────────────

def _is_horizontal(line: dict) -> bool:
    return abs((line.get("y0", 0) - line.get("y1", 0))) < _MERGE_TOL


def _is_vertical(line: dict) -> bool:
    return abs((line.get("x0", 0) - line.get("x1", 0))) < _MERGE_TOL


def _line_to_record(line: dict, page_height_pt: float, index: int) -> dict | None:
    """
    Convert a pdfplumber line dict to a report-item record.

    pdfplumber uses bottom-left origin; RDLC uses top-left origin.
    So:  top_pt = page_height - y1   (y1 is the higher y value in PDF coords)
    """
    x0 = float(line.get("x0", 0))
    y0 = float(line.get("y0", 0))
    x1 = float(line.get("x1", 0))
    y1 = float(line.get("y1", 0))

    # Normalise so x0 <= x1, y0 <= y1
    if x0 > x1:
        x0, x1 = x1, x0
    if y0 > y1:
        y0, y1 = y1, y0

    width_pt  = x1 - x0
    height_pt = y1 - y0

    horiz = height_pt < _MERGE_TOL
    vert  = width_pt  < _MERGE_TOL

    if not horiz and not vert:
        # diagonal – skip
        return None

    length_pt = width_pt if horiz else height_pt
    if length_pt < _MIN_LENGTH_PT:
        return None

    # RDLC top = distance from top of page
    # In PDF coords, y=0 is bottom; y1 is the TOP edge of the line bbox
    top_pt  = page_height_pt - y1
    left_pt = x0

    top_cm    = top_pt  * _PT_TO_CM
    left_cm   = left_pt * _PT_TO_CM
    width_cm  = (width_pt  * _PT_TO_CM) if horiz else 0.0
    height_cm = (height_pt * _PT_TO_CM) if vert  else 0.0

    return {
        "Name":        f"Line{index}",
        "Top":         _fmt_cm(top_cm),
        "Left":        _fmt_cm(left_cm),
        "Height":      _fmt_cm(height_cm),
        "Width":       _fmt_cm(width_cm),
        "ZIndex":      index,
        "BorderStyle": "Solid",
    }


def _dedup_lines(raw: list[dict]) -> list[dict]:
    """
    Remove near-duplicate segments that pdfplumber may report multiple times
    (e.g. once as a 'line' and again as a table-edge rect side).

    Two records are duplicates if their Top, Left, Height, Width all differ
    by less than _MERGE_TOL * _PT_TO_CM cm.
    """
    tol = _MERGE_TOL * _PT_TO_CM

    def _val(s: str) -> float:
        return float(s.rstrip("cm"))

    unique: list[dict] = []
    for rec in raw:
        t, l, h, w = _val(rec["Top"]), _val(rec["Left"]), _val(rec["Height"]), _val(rec["Width"])
        is_dup = False
        for u in unique:
            if (
                abs(_val(u["Top"])    - t) < tol
                and abs(_val(u["Left"])   - l) < tol
                and abs(_val(u["Height"]) - h) < tol
                and abs(_val(u["Width"])  - w) < tol
            ):
                is_dup = True
                break
        if not is_dup:
            unique.append(rec)
    return unique


def _rect_to_lines(rect: dict, page_height_pt: float) -> list[dict]:
    """
    Decompose a filled/stroked rectangle into its four border segments.
    pdfplumber 'rect' keys: x0, y0, x1, y1
    """
    x0 = float(rect["x0"])
    y0 = float(rect["y0"])
    x1 = float(rect["x1"])
    y1 = float(rect["y1"])

    if x0 > x1:
        x0, x1 = x1, x0
    if y0 > y1:
        y0, y1 = y1, y0

    return [
        {"x0": x0, "y0": y1, "x1": x1, "y1": y1},  # top edge
        {"x0": x0, "y0": y0, "x1": x1, "y1": y0},  # bottom edge
        {"x0": x0, "y0": y0, "x1": x0, "y1": y1},  # left edge
        {"x0": x1, "y0": y0, "x1": x1, "y1": y1},  # right edge
    ]


# ── main extraction ────────────────────────────────────────────────

def extract_lines_from_pdf(pdf_path: Path) -> list[dict]:
    raw_records: list[dict] = []
    index = 1

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            ph = float(page.height)   # page height in points

            # ── 1. explicit line objects ───────────────────────────
            for ln in page.lines:
                rec = _line_to_record(ln, ph, index)
                if rec:
                    raw_records.append(rec)
                    index += 1

            # ── 2. table edges (pdfplumber table-finder) ──────────
            #   Extract table bounding boxes and their cell borders
            try:
                tables = page.find_tables()
                for tbl in tables:
                    bbox = tbl.bbox          # (x0, top, x1, bottom) – top-left origin
                    # Convert bbox to bottom-left origin used by pdfplumber internally
                    # pdfplumber table bbox uses TOP-LEFT origin (top = distance from top)
                    t_x0, t_top, t_x1, t_bot = bbox
                    # Reconstruct as bottom-left
                    rects_from_table = [
                        {"x0": t_x0, "y0": ph - t_bot, "x1": t_x1, "y1": ph - t_top}
                    ]
                    for r in rects_from_table:
                        for edge in _rect_to_lines(r, ph):
                            rec = _line_to_record(edge, ph, index)
                            if rec:
                                raw_records.append(rec)
                                index += 1
            except Exception:
                pass  # table detection optional

            # ── 3. rect objects (drawn borders) ───────────────────
            for rect in page.rects:
                for edge in _rect_to_lines(rect, ph):
                    rec = _line_to_record(edge, ph, index)
                    if rec:
                        raw_records.append(rec)
                        index += 1

            # ── 4. curves that look like lines ────────────────────
            for curve in page.curves:
                pts = curve.get("pts", [])
                if len(pts) == 2:
                    synthetic = {
                        "x0": pts[0][0], "y0": pts[0][1],
                        "x1": pts[1][0], "y1": pts[1][1],
                    }
                    rec = _line_to_record(synthetic, ph, index)
                    if rec:
                        raw_records.append(rec)
                        index += 1

    deduped = _dedup_lines(raw_records)

    # Re-index cleanly after dedup
    for i, rec in enumerate(deduped, start=1):
        rec["Name"]   = f"Line{i}"
        rec["ZIndex"] = i

    return deduped


# ── entry point ────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Extract lines/table borders from a PDF and write line.json"
    )
    parser.add_argument(
        "pdf",
        nargs="?",
        help="Path to the PDF file (default: pdf_doc/<first pdf found>)",
    )
    parser.add_argument(
        "--out-dir",
        default=None,
        help="Output directory for line.json (default: same folder as this script / text_json/)",
    )
    args = parser.parse_args(argv)

    script_dir = Path(__file__).resolve().parent

    # Resolve PDF path
    if args.pdf:
        pdf_path = Path(args.pdf).expanduser().resolve()
    else:
        pdf_dir = script_dir / "pdf_doc"
        if not pdf_dir.is_dir():
            print(f"ERROR: No PDF path given and pdf_doc/ folder not found at {pdf_dir}")
            return 1
        pdfs = sorted(pdf_dir.glob("*.pdf"))
        if not pdfs:
            print(f"ERROR: No PDF files found in {pdf_dir}")
            return 1
        pdf_path = pdfs[0]

    if not pdf_path.is_file():
        print(f"ERROR: PDF not found: {pdf_path}")
        return 1

    # Resolve output directory
    out_dir = Path(args.out_dir).expanduser().resolve() if args.out_dir else script_dir / "text_json"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / _OUTPUT_NAME

    print(f"Extracting lines from: {pdf_path}")
    lines = extract_lines_from_pdf(pdf_path)
    payload = {"Lines": lines}
    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(lines)} line(s) to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())