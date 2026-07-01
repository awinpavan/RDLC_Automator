"""
merge_input_into_text.py
=========================
Reads text_json/input.json and text_json/text.json,
converts each input box to the standard textbox format,
appends them to text.json ReportItems, and overwrites text.json.

The input box fields that are NOT part of the standard textbox format
(LabelTop, LabelLeft, LabelWidth, ForLabel, ForLabelText, FieldKey)
are stripped out before merging.

Usage:
    python merge_input_into_text.py
"""

from __future__ import annotations

import json
from pathlib import Path


# ── Config ────────────────────────────────────────────────────────
_SCRIPT_DIR = Path(__file__).resolve().parent
_TEXT_JSON  = _SCRIPT_DIR / "text_json" / "text.json"
_INPUT_JSON = _SCRIPT_DIR / "text_json" / "input.json"

# Fields that exist in input.json but NOT in standard textbox format
# These are stripped before merging into text.json
_EXTRA_FIELDS = {
    "LabelTop",
    "LabelLeft",
    "LabelWidth",
    "ForLabel",
    "ForLabelText",
    "FieldKey",
}


def load_json(path: Path) -> dict:
    """Load JSON with BOM stripping."""
    if not path.is_file():
        raise FileNotFoundError(f"Not found: {path}")
    raw = path.read_bytes()
    if raw.startswith(b'\xef\xbb\xbf'):
        raw = raw[3:]
    try:
        return json.loads(raw.decode("utf-8").strip())
    except json.JSONDecodeError:
        obj, _ = json.JSONDecoder().raw_decode(raw.decode("utf-8").strip())
        return obj


def to_standard_textbox(input_box: dict) -> dict:
    """
    Strip input.json-specific fields so the result matches
    the standard textbox structure in text.json.
    """
    return {k: v for k, v in input_box.items() if k not in _EXTRA_FIELDS}


def main() -> int:
    # ── Load both files ────────────────────────────────────────────
    print(f"Loading text.json  from: {_TEXT_JSON}")
    text_data  = load_json(_TEXT_JSON)
    text_items = text_data.get("ReportItems", [])
    print(f"  {len(text_items)} existing textbox(es)")

    print(f"Loading input.json from: {_INPUT_JSON}")
    input_data  = load_json(_INPUT_JSON)
    input_items = input_data.get("ReportItems", [])
    print(f"  {len(input_items)} input box(es) to merge\n")

    # ── Convert and append ─────────────────────────────────────────
    print("Merging input boxes into text.json:")
    for item in input_items:
        standard = to_standard_textbox(item)
        text_items.append(standard)
        print(f"  + {standard['Name']:<14} "
              f"Top={standard.get('Top',''):<14} "
              f"Left={standard.get('Left',''):<14} "
              f"[{item.get('ForLabelText', '')}]")

    # ── Overwrite text.json ────────────────────────────────────────
    text_data["ReportItems"] = text_items
    _TEXT_JSON.write_text(
        json.dumps(text_data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"\nDone. text.json now has {len(text_items)} textbox(es) "
          f"({len(text_items) - len(input_items)} original + "
          f"{len(input_items)} input boxes)")
    print(f"Saved to: {_TEXT_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())