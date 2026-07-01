from __future__ import annotations

import json
from pathlib import Path

import fitz  # PyMuPDF

from PyMudPdf import _extract_text_blocks

# PDF points (1/72") to centimeters
_PT_TO_CM = 2.54 / 72.0

# Approximate width scale (cm per character). Used when bbox width is small.
_CHAR_WIDTH_CM_6PT = 0.12
_CHAR_WIDTH_CM_7PT = 0.13
_CHAR_WIDTH_CM_8PT = 0.145

# PyMuPDF span flags: 16 is commonly used for "bold" (plus font-name heuristics).
_BOLD_FLAG = 16

_OUTPUT_NAME      = "text.json"
_PAGE_OUTPUT_NAME = "page.json"

# Standard RDLC margin/spacing defaults (not stored in PDF itself)
_RDLC_LEFT_MARGIN    = "0.15cm"
_RDLC_RIGHT_MARGIN   = "0.15cm"
_RDLC_TOP_MARGIN     = "0.25cm"
_RDLC_BOTTOM_MARGIN  = "0.25cm"
_RDLC_COL_SPACING    = "0.13cm"


def _script_dir() -> Path:
    return Path(__file__).resolve().parent


def _fmt_cm(value: float) -> str:
    return f"{value:.5f}cm"


# ── Page dimension extraction ──────────────────────────────────────

def _extract_page_dimensions(pdf_path: Path) -> dict[str, str]:
    """
    Read the first page mediabox dimensions from the PDF using PyMuPDF
    and return a dict matching the RDLC <Page> element structure.
    """
    with fitz.open(pdf_path) as doc:
        page = doc[0]
        w_pt = float(page.rect.width)
        h_pt = float(page.rect.height)

    return {
        "PageHeight":    _fmt_cm(h_pt * _PT_TO_CM),
        "PageWidth":     _fmt_cm(w_pt * _PT_TO_CM),
        "LeftMargin":    _RDLC_LEFT_MARGIN,
        "RightMargin":   _RDLC_RIGHT_MARGIN,
        "TopMargin":     _RDLC_TOP_MARGIN,
        "BottomMargin":  _RDLC_BOTTOM_MARGIN,
        "ColumnSpacing": _RDLC_COL_SPACING,
        "Style":         "",
    }


# ── Text extraction helpers ───────────────────────────────────────

def _line_width_cm(text: str, x0: float, x1: float, *, font_size_out: str) -> float:
    bbox_w = max(0.0, (x1 - x0) * _PT_TO_CM)
    n = len(text.strip()) or 1
    if font_size_out == "8pt":
        char_w = _CHAR_WIDTH_CM_8PT
    elif font_size_out == "6pt":
        char_w = _CHAR_WIDTH_CM_6PT
    else:
        char_w = _CHAR_WIDTH_CM_7PT
    length_w = n * char_w
    return max(bbox_w, length_w)


def _line_font_size_pt(line: dict[str, object]) -> float | None:
    stats = line.get("stats")
    if isinstance(stats, dict):
        mx = stats.get("max_font_size")
        if isinstance(mx, (int, float)):
            return float(mx)
        mn = stats.get("min_font_size")
        if isinstance(mn, (int, float)):
            return float(mn)
    spans = line.get("spans")
    if isinstance(spans, list):
        best: float | None = None
        for span in spans:
            if not isinstance(span, dict):
                continue
            s = span.get("size")
            if isinstance(s, (int, float)):
                f = float(s)
                best = f if best is None else max(best, f)
        return best
    return None


def _is_bold_line(line: dict[str, object]) -> bool:
    spans = line.get("spans")
    if not isinstance(spans, list):
        return False
    for span in spans:
        if not isinstance(span, dict):
            continue
        flags = span.get("flags")
        if isinstance(flags, int) and (flags & _BOLD_FLAG) != 0:
            return True
        font = span.get("font")
        if isinstance(font, str) and "bold" in font.lower():
            return True
    return False


def _font_and_height_for_line(line: dict[str, object]) -> tuple[str, str]:
    """
    Rule (by extracted PDF font size in pt):
      - <= 7pt  => FontSize=6pt,  Height=0.380cm
      - <= 9pt  => FontSize=7pt,  Height=0.380cm  (i.e. 7pt < size <= 9pt)
      - > 9pt   => FontSize=8pt,  Height=0.434cm
    If size is unknown, falls through to the 8pt branch.
    """
    pt = _line_font_size_pt(line)
    if pt is not None and pt <= 7.0:
        return "6pt", "0.380cm"
    if pt is not None and pt <= 9.0:
        return "7pt", "0.380cm"
    return "8pt", "0.434cm"


def _build_report_item(
    text: str,
    top_cm: float,
    left_cm: float,
    width_cm: float,
    font_size: str,
    height: str,
    is_bold: bool,
    index: int,
) -> dict[str, object]:
    name = f"Textbox{index}"
    return {
        "Name": name,
        "DefaultName": name,
        "CanGrow": True,
        "KeepTogether": True,
        "Text": text,
        "FontSize": font_size,
        "IsBold": is_bold,
        "FontWeight": "Bold" if is_bold else "Normal",
        "Top": _fmt_cm(top_cm),
        "Left": _fmt_cm(left_cm),
        "Height": height,
        "Width": _fmt_cm(width_cm),
        "ZIndex": index,
        "Border": "None",
        "PaddingLeft": "1pt",
        "PaddingRight": "1pt",
        "PaddingTop": "0.5pt",
        "PaddingBottom": "0.5pt",
    }


# ── Main extraction ───────────────────────────────────────────────

def pdf_folder_to_report_items(
    pdf_dir: Path,
) -> tuple[list[dict[str, object]], dict[str, str] | None]:
    """
    Returns (report_items, page_dimensions).
    page_dimensions is taken from the FIRST pdf found; None if no PDFs exist.
    """
    if not pdf_dir.is_dir():
        raise FileNotFoundError(f"PDF folder not found: {pdf_dir}")

    pdf_paths = sorted(
        p for p in pdf_dir.iterdir()
        if p.is_file() and p.suffix.lower() == ".pdf"
    )

    items: list[dict[str, object]] = []
    page_dims: dict[str, str] | None = None
    n = 0

    for pdf_path in pdf_paths:
        # Extract page dimensions from first PDF only
        if page_dims is None:
            page_dims = _extract_page_dimensions(pdf_path)

        with fitz.open(pdf_path) as doc:
            for page in doc:
                for line in _extract_text_blocks(page):
                    text = (line.get("text") or "").strip()
                    if not text:
                        continue
                    bbox = line.get("bbox")
                    if not bbox or len(bbox) < 4:
                        continue
                    x0, y0, x1, y1 = (
                        float(bbox[0]), float(bbox[1]),
                        float(bbox[2]), float(bbox[3]),
                    )
                    left_cm = x0 * _PT_TO_CM
                    top_cm  = y0 * _PT_TO_CM
                    font_size, height = _font_and_height_for_line(line)
                    width_cm = _line_width_cm(text, x0, x1, font_size_out=font_size)
                    is_bold  = _is_bold_line(line)
                    n += 1
                    items.append(
                        _build_report_item(
                            text, top_cm, left_cm, width_cm,
                            font_size, height, is_bold, n,
                        )
                    )

    return items, page_dims


def main() -> int:
    root    = _script_dir()
    pdf_dir = root / "pdf_doc"
    out_dir = root / "text_json"

    out_dir.mkdir(parents=True, exist_ok=True)

    pdf_paths = sorted(
        p for p in pdf_dir.iterdir()
        if p.is_file() and p.suffix.lower() == ".pdf"
    )
    if not pdf_paths:
        print(
            f"No PDF files in {pdf_dir.resolve()} — "
            "text.json will only contain an empty ReportItems list."
        )

    report_items, page_dims = pdf_folder_to_report_items(pdf_dir)

    # ── Write text.json ───────────────────────────────────────────
    text_path = out_dir / _OUTPUT_NAME
    text_path.write_text(
        json.dumps({"ReportItems": report_items}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(report_items)} textbox(es) to {text_path.resolve()}")

    # ── Write page.json ───────────────────────────────────────────
    if page_dims is not None:
        page_path = out_dir / _PAGE_OUTPUT_NAME
        page_path.write_text(
            json.dumps({"Page": page_dims}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"Wrote page dimensions to {page_path.resolve()}")
        print(f"  PageWidth  = {page_dims['PageWidth']}")
        print(f"  PageHeight = {page_dims['PageHeight']}")
    else:
        print("No page dimensions extracted (no PDFs found).")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())