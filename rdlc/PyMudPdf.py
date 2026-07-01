from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF  # type: ignore[import-not-found]


@dataclass(frozen=True)
class AppConfig:
    input_dir: Path
    output_dir: Path
    output_encoding: str = "utf-8"


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _unique_output_base(output_dir: Path, pdf_path: Path) -> Path:
    stem = pdf_path.stem
    ts = _timestamp()
    candidate_base = output_dir / f"{stem}_{ts}"
    if not (candidate_base.with_suffix(".txt").exists() or candidate_base.with_suffix(".json").exists()):
        return candidate_base

    i = 1
    while True:
        candidate_base = output_dir / f"{stem}_{ts}_{i}"
        if not (candidate_base.with_suffix(".txt").exists() or candidate_base.with_suffix(".json").exists()):
            return candidate_base
        i += 1


def _safe_pymupdf_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    for key, getter in [
        ("pymupdf", lambda: getattr(fitz, "__version__", "")),
        ("pymupdf_version", lambda: getattr(fitz, "pymupdf_version", "")),
        ("fitz_version", lambda: getattr(fitz, "fitz_version", "")),
        ("version_bind", lambda: getattr(fitz, "VersionBind", "")),
        ("version_fitz", lambda: getattr(fitz, "VersionFitz", "")),
    ]:
        try:
            value = getter()
        except Exception:
            value = ""
        if value:
            versions[key] = str(value)
    return versions


def _text_from_spans(spans: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for span in spans:
        t = span.get("text", "")
        if t:
            parts.append(str(t))
    return "".join(parts)


def _extract_text_blocks(page: Any) -> list[dict[str, Any]]:
    """
    Extract structured "text blocks" with metadata using page.get_text("dict").

    Each "text block" corresponds to a single extracted LINE (newline boundary),
    not PyMuPDF's original block grouping.

    We keep only PyMuPDF text blocks (type==0), then split them into lines.
    """
    d = page.get_text("dict")
    blocks_out: list[dict[str, Any]] = []

    line_block_index = 0

    for source_block_idx, block in enumerate(d.get("blocks", []) or []):
        if block.get("type") != 0:
            continue

        for line_idx, line in enumerate(block.get("lines", []) or []):
            spans_out: list[dict[str, Any]] = []
            fonts: set[str] = set()
            sizes: list[float] = []

            for span in line.get("spans", []) or []:
                font = span.get("font")
                if font:
                    fonts.add(str(font))
                size = span.get("size")
                if isinstance(size, (int, float)):
                    sizes.append(float(size))

                spans_out.append(
                    {
                        "text": span.get("text", ""),
                        "bbox": span.get("bbox"),
                        "font": span.get("font"),
                        "size": span.get("size"),
                        "flags": span.get("flags"),
                        "color": span.get("color"),
                        "ascender": span.get("ascender"),
                        "descender": span.get("descender"),
                        "origin": span.get("origin"),
                    }
                )

            line_text = _text_from_spans(spans_out)

            blocks_out.append(
                {
                    "block_index": line_block_index,
                    "source_block_index": source_block_idx,
                    "source_line_index": line_idx,
                    "type": 0,
                    "bbox": line.get("bbox"),
                    "text": line_text,
                    "wmode": line.get("wmode"),
                    "dir": line.get("dir"),
                    "stats": {
                        "span_count": len(spans_out),
                        "fonts": sorted(fonts),
                        "min_font_size": min(sizes) if sizes else None,
                        "max_font_size": max(sizes) if sizes else None,
                    },
                    "spans": spans_out,
                }
            )
            line_block_index += 1

    return blocks_out


# ── Unit conversion ────────────────────────────────────────────────────────────
_PT_TO_CM = 2.54 / 72.0

# Character width estimates per pt size, used to pad bbox width when it is too
# narrow (e.g. glyphs extracted with no advance-width information).
_CHAR_WIDTH_CM_BY_PT: dict[str, float] = {
    "6pt": 0.12,
    "7pt": 0.13,
    "8pt": 0.145,
}
_CHAR_WIDTH_CM_DEFAULT = 0.13


def _char_width_for_size(font_size_pt_str: str) -> float:
    return _CHAR_WIDTH_CM_BY_PT.get(font_size_pt_str, _CHAR_WIDTH_CM_DEFAULT)


def _fmt_cm(value: float) -> str:
    return f"{value:.5f}cm"


# ── Font-size extraction ───────────────────────────────────────────────────────

def _actual_font_size_pt(line: dict[str, Any]) -> float | None:
    """
    Return the largest font size (in PDF points) found on this line,
    or None if no size information is available.
    """
    stats = line.get("stats") or {}
    mx = stats.get("max_font_size")
    if isinstance(mx, (int, float)):
        return float(mx)
    mn = stats.get("min_font_size")
    if isinstance(mn, (int, float)):
        return float(mn)
    # Fall back to scanning spans directly
    best: float | None = None
    for span in line.get("spans") or []:
        if not isinstance(span, dict):
            continue
        s = span.get("size")
        if isinstance(s, (int, float)):
            f = float(s)
            best = f if best is None else max(best, f)
    return best


def _format_font_size_pt(pt: float) -> str:
    """Format a float point-size as an RDLC-style string, e.g. 7.0 → '7pt'."""
    if abs(pt - round(pt)) < 1e-6:
        return f"{int(round(pt))}pt"
    return f"{pt:g}pt"


def _font_size_pt_str_from_line(line: dict[str, Any]) -> str:
    """
    Return the actual PDF font size for this line as an RDLC pt string.
    Falls back to '7pt' only when no size can be found at all.
    """
    pt = _actual_font_size_pt(line)
    if pt is None:
        return "7pt"
    return _format_font_size_pt(pt)


# ── Line height from actual bbox ───────────────────────────────────────────────

def _line_height_cm(bbox: list | tuple) -> str:
    """Compute line height from its PDF bounding box."""
    y0, y1 = float(bbox[1]), float(bbox[3])
    h = max(0.0, (y1 - y0) * _PT_TO_CM)
    return _fmt_cm(h)


# ── Width: use bbox but guarantee at least character-count estimate ────────────

def _line_width_cm(text: str, x0: float, x1: float, font_size_pt_str: str) -> float:
    bbox_w = max(0.0, (x1 - x0) * _PT_TO_CM)
    n = len(text.strip()) or 1
    char_w = _char_width_for_size(font_size_pt_str)
    return max(bbox_w, n * char_w)


# ── Bold detection ─────────────────────────────────────────────────────────────
_BOLD_FLAG = 16


def _is_bold_line(line: dict[str, Any]) -> bool:
    for span in line.get("spans") or []:
        if not isinstance(span, dict):
            continue
        flags = span.get("flags")
        if isinstance(flags, int) and (flags & _BOLD_FLAG):
            return True
        font = span.get("font")
        if isinstance(font, str) and "bold" in font.lower():
            return True
    return False


# ── Report-item builders ───────────────────────────────────────────────────────

def _build_report_item(
    text: str,
    top_cm: float,
    left_cm: float,
    width_cm: float,
    height: str,           # already formatted cm string
    font_size_pt: str,     # actual PDF size, e.g. "7pt", "8.5pt"
    is_bold: bool,
    index: int,
) -> dict[str, Any]:
    name = f"Textbox{index}"
    return {
        "Name": name,
        "DefaultName": name,
        "CanGrow": True,
        "KeepTogether": True,
        "Text": text,
        "FontSize": font_size_pt,
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


# ── Per-document extraction ────────────────────────────────────────────────────

def report_items_actual_from_document(
    doc: Any, *, start_index: int = 1
) -> tuple[list[dict[str, Any]], int]:
    """
    One ReportItems entry per line.

    Measurements are taken directly from the PDF:
      - Top / Left   from line bbox (converted to cm)
      - Width        from line bbox, padded by character-count estimate if too narrow
      - Height       from line bbox (converted to cm)
      - FontSize     actual PDF point size (e.g. "7pt", "8pt", "10.5pt")
      - IsBold       from span flags / font name
    """
    items: list[dict[str, Any]] = []
    n = start_index
    for page in doc:
        for line in _extract_text_blocks(page):
            text = (line.get("text") or "").strip()
            if not text:
                continue
            bbox = line.get("bbox")
            if not bbox or len(bbox) < 4:
                continue
            x0, y0, x1, y1 = float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])
            left_cm   = x0 * _PT_TO_CM
            top_cm    = y0 * _PT_TO_CM
            font_size = _font_size_pt_str_from_line(line)    # ← actual PDF size
            height    = _line_height_cm(bbox)                # ← actual bbox height
            width_cm  = _line_width_cm(text, x0, x1, font_size)
            is_bold   = _is_bold_line(line)
            items.append(
                _build_report_item(text, top_cm, left_cm, width_cm, height, font_size, is_bold, n)
            )
            n += 1
    return items, n


# ── Kept for backward compatibility (used by extract_pdf_as_json) ──────────────

_CHAR_WIDTH_CM = 0.13
_REPORT_TEXTBOX_HEIGHT = "0.3900cm"


def _line_width_cm_legacy(text: str, x0: float, x1: float) -> float:
    bbox_w = max(0.0, (x1 - x0) * _PT_TO_CM)
    n = len(text.strip()) or 1
    return max(bbox_w, n * _CHAR_WIDTH_CM)


def _build_report_textbox_item(
    text: str,
    top_cm: float,
    left_cm: float,
    width_cm: float,
    index: int,
) -> dict[str, Any]:
    name = f"Textbox{index}"
    return {
        "Name": name,
        "DefaultName": name,
        "CanGrow": True,
        "KeepTogether": True,
        "Text": text,
        "FontSize": "7pt",
        "Top": f"{top_cm:.5f}cm",
        "Left": f"{left_cm:.5f}cm",
        "Height": _REPORT_TEXTBOX_HEIGHT,
        "Width": f"{width_cm:.5f}cm",
        "ZIndex": index,
        "Border": "None",
        "PaddingLeft": "1pt",
        "PaddingRight": "1pt",
        "PaddingTop": "1pt",
        "PaddingBottom": "1pt",
    }


def report_items_from_document(
    doc: Any, *, start_index: int = 1
) -> tuple[list[dict[str, Any]], int]:
    items: list[dict[str, Any]] = []
    n = start_index
    for page in doc:
        for line in _extract_text_blocks(page):
            text = (line.get("text") or "").strip()
            if not text:
                continue
            bbox = line.get("bbox")
            if not bbox or len(bbox) < 4:
                continue
            x0, y0, x1, y1 = float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])
            left_cm  = x0 * _PT_TO_CM
            top_cm   = y0 * _PT_TO_CM
            width_cm = _line_width_cm_legacy(text, x0, x1)
            items.append(_build_report_textbox_item(text, top_cm, left_cm, width_cm, n))
            n += 1
    return items, n


# ── Full JSON extraction (for analysis / debugging) ────────────────────────────

def extract_pdf_as_json(pdf_path: Path) -> dict:
    stat = pdf_path.stat()
    with fitz.open(pdf_path) as doc:
        pages: list[dict] = []
        full_parts: list[str] = []
        for idx, page in enumerate(doc, start=1):
            page_text = page.get_text("text")
            pages.append(
                {
                    "page_number": idx,
                    "text": page_text,
                    "text_blocks": _extract_text_blocks(page),
                }
            )
            full_parts.append(page_text.rstrip())

        full_text = "\n".join(full_parts).rstrip() + "\n"
        report_items, _ = report_items_from_document(doc)

        return {
            "source": {
                "file_name": pdf_path.name,
                "file_path": str(pdf_path.resolve()),
                "file_size_bytes": stat.st_size,
                "modified_time_iso": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            },
            "document": {
                "page_count": int(doc.page_count),
                "metadata": doc.metadata or {},
            },
            "extraction": {
                "method": "pymupdf",
                "versions": _safe_pymupdf_versions(),
                "extracted_at_iso": datetime.now().isoformat(),
            },
            "ReportItems": report_items,
            "text": {
                "full_text": full_text,
                "pages": pages,
            },
        }


# ── text_1.json writer ─────────────────────────────────────────────────────────

def _write_text_1_json(
    project_root: Path,
    pdf_paths: list[Path],
    *,
    encoding: str = "utf-8",
) -> tuple[Path, int]:
    """
    Merge all lines from pdf_paths into a single text_1.json (ReportItems only),
    using actual PDF font sizes and bbox-accurate dimensions per line.
    """
    out_path = project_root / "text_1.json"
    items: list[dict[str, Any]] = []
    next_index = 1
    for pdf_path in pdf_paths:
        with fitz.open(pdf_path) as doc:
            part, next_index = report_items_actual_from_document(doc, start_index=next_index)
            items.extend(part)
    out_path.write_text(
        json.dumps({"ReportItems": items}, ensure_ascii=False, indent=2) + "\n",
        encoding=encoding,
        errors="replace",
    )
    return out_path, len(items)


# ── Folder runner ──────────────────────────────────────────────────────────────

def parse_folder(config: AppConfig) -> list[dict[str, Path]]:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    if not config.input_dir.exists():
        raise FileNotFoundError(f"Input folder not found: {config.input_dir}")

    written: list[dict[str, Path]] = []
    pdf_paths = sorted(
        p for p in config.input_dir.iterdir()
        if p.is_file() and p.suffix.lower() == ".pdf"
    )
    for pdf_path in pdf_paths:
        data = extract_pdf_as_json(pdf_path)
        out_base = _unique_output_base(config.output_dir, pdf_path)

        txt_path  = out_base.with_suffix(".txt")
        json_path = out_base.with_suffix(".json")

        txt_path.write_text(data["text"]["full_text"], encoding=config.output_encoding, errors="replace")
        json_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding=config.output_encoding,
            errors="replace",
        )
        written.append({"txt": txt_path, "json": json_path})

    project_root = Path(__file__).resolve().parent
    text_1_path, text_1_count = _write_text_1_json(project_root, pdf_paths, encoding=config.output_encoding)
    print(f"Wrote actual-measure ReportItems to {text_1_path} ({text_1_count} item(s))")

    return written


# ── CLI ────────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Parse PDFs in pdf_doc/ into unique .txt + .json files in parsed_pdf_doc/."
    )
    parser.add_argument("--input-dir",  default="pdf_doc",        help="Folder containing PDFs (default: pdf_doc)")
    parser.add_argument("--output-dir", default="parsed_pdf_doc", help="Folder to write outputs (default: parsed_pdf_doc)")
    args = parser.parse_args()

    config = AppConfig(input_dir=Path(args.input_dir), output_dir=Path(args.output_dir))
    written = parse_folder(config)

    print(f"Parsed {len(written)} PDF(s).")
    for item in written:
        print(f"- TXT:  {item['txt']}")
        print(f"  JSON: {item['json']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())