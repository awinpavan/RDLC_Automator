"""
clean_text_json.py
==================
Reads text.json and null_text.json, removes any textbox from text.json
whose Name matches a Name in null_text.json, then overwrites text.json.

Usage:
    python clean_text_json.py
"""

from __future__ import annotations

import json
from pathlib import Path

_SCRIPT_DIR     = Path(__file__).resolve().parent
_TEXT_JSON      = _SCRIPT_DIR / "text_json" / "text.json"
_NULL_TEXT_JSON = _SCRIPT_DIR / "text_json" / "null_text.json"


def main() -> int:
    # ── Load text.json ─────────────────────────────────────────────
    if not _TEXT_JSON.is_file():
        print(f"ERROR: text.json not found at {_TEXT_JSON}")
        return 1
    text_data = json.loads(_TEXT_JSON.read_text(encoding="utf-8"))
    all_items = text_data.get("ReportItems", [])
    print(f"Loaded {len(all_items)} textbox(es) from text.json")

    # ── Load null_text.json ────────────────────────────────────────
    if not _NULL_TEXT_JSON.is_file():
        print(f"ERROR: null_text.json not found at {_NULL_TEXT_JSON}")
        return 1
    null_data = json.loads(_NULL_TEXT_JSON.read_text(encoding="utf-8"))

    # Build a set of Names to remove from null_text.json
    null_names: set[str] = set()
    for item in null_data.get("ReportItems", []):
        if isinstance(item, dict) and "Name" in item:
            null_names.add(item["Name"])

    print(f"\nNames to remove ({len(null_names)} total):")
    for name in sorted(null_names):
        print(f"  - {name}")

    # ── Compare and filter ─────────────────────────────────────────
    cleaned_items = []
    print("\nProcessing textboxes:")
    for item in all_items:
        name = item.get("Name", "")
        if name in null_names:
            print(f"  REMOVED  → {name}: \"{item.get('Text', '')}\"")
        else:
            cleaned_items.append(item)

    removed = len(all_items) - len(cleaned_items)
    print(f"\nResult: {removed} removed, {len(cleaned_items)} kept.")

    # ── Overwrite text.json ────────────────────────────────────────
    text_data["ReportItems"] = cleaned_items
    _TEXT_JSON.write_text(
        json.dumps(text_data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"text.json overwritten at {_TEXT_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())