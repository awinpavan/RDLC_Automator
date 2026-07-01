"""
generate_input_boxes.py
========================
Reads text.json, line.json, and page.json from text_json/ folder,
sends them to GPT to:
  1. Identify which textboxes need an input value
  2. Find the best non-overlapping location next to each label
  3. Generate in_text.json with the input box definitions

Output:
    text_json/in_text.json

Usage:
    pip install openai python-dotenv
    python generate_input_boxes.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI


# ── Config ────────────────────────────────────────────────────────
_SCRIPT_DIR     = Path(__file__).resolve().parent
_TEXT_JSON      = _SCRIPT_DIR / "text_json" / "text.json"
_LINE_JSON      = _SCRIPT_DIR / "text_json" / "line.json"
_PAGE_JSON      = _SCRIPT_DIR / "text_json" / "page.json"
_IN_TEXT_OUT    = _SCRIPT_DIR / "text_json" / "in_text.json"
_ENV_FILE       = _SCRIPT_DIR / ".env"

_MODEL = "gpt-4o"

load_dotenv(dotenv_path=_ENV_FILE)


# ── Prompt ────────────────────────────────────────────────────────
_SYSTEM_PROMPT = """
You are a document layout assistant for hotel registration card RDLC reports.

You will receive:
- A list of textbox items (with Name, Text, Top, Left, Height, Width)
- A list of line items (with Name, Top, Left, Height, Width)
- Page dimensions (PageWidth, PageHeight, margins)

Your tasks:
1. IDENTIFY which textboxes are field LABELS that need an input box next to them.
   These are labels like "Full Name:", "Arrival Date:", "Room Number:", "NIF/VAT:", etc.
   Do NOT create input boxes for:
   - Static content, headers, footers, hotel info, terms and conditions
   - Textboxes that already have an actual value next to them at the same Top position

2. For each identified label, FIND the best position to place an input textbox:
   - Place it to the RIGHT of the label textbox (Left = label.Left + label.Width + 0.1cm)
   - Use the same Top as the label textbox
   - Height should be 0.434cm (standard row height)
   - Width should extend to fill the available space in that row WITHOUT overlapping:
     a) Any other existing textbox
     b) Any line (check if the input box top/bottom would cross a horizontal line,
        or if the input box left/right would cross a vertical line)
   - Minimum width: 1.5cm. If there is less than 1.5cm available, skip that label.
   - Maximum width: extend to PageWidth - RightMargin, but stop before any obstacle

3. OUTPUT a JSON object in this exact format with no explanation:
{
  "input_boxes": [
    {
      "Name": "Input_Textbox1",
      "DefaultName": "Input_Textbox1",
      "CanGrow": true,
      "KeepTogether": true,
      "Text": "",
      "FontSize": "7pt",
      "IsBold": false,
      "FontWeight": "Normal",
      "Top": "5.96455cm",
      "Left": "9.50000cm",
      "Height": "0.434cm",
      "Width": "3.20000cm",
      "ZIndex": 200,
      "Border": "None",
      "PaddingLeft": "2pt",
      "PaddingRight": "2pt",
      "PaddingTop": "2pt",
      "PaddingBottom": "2pt",
      "ForLabel": "Textbox9"
    }
  ]
}

Rules for naming: use "Input_" prefix followed by the label textbox name.
ForLabel field: the Name of the label textbox this input box belongs to.
ZIndex: start from 200 and increment by 1 for each input box.
Text: always empty string "" — this is where the guest will write/type.

CRITICAL overlap rules:
- A horizontal line at Top=T means there is a line across the page at height T.
  Do not place an input box whose top < T < top+height (i.e. line cuts through the box).
- A vertical line at Left=L means there is a vertical line at position L.
  Do not place an input box that crosses this vertical line.
- Do not overlap any existing textbox. Check both x-range and y-range overlap.
""".strip()


def load_json(path: Path) -> dict:
    if not path.is_file():
        raise FileNotFoundError(f"File not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def call_gpt(text_items: list, line_items: list, page: dict) -> list[dict]:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "OPENAI_API_KEY not found.\n"
            f"Make sure your .env file exists at {_ENV_FILE} and contains:\n"
            "  OPENAI_API_KEY=sk-your-key-here"
        )

    client = OpenAI(api_key=api_key)

    # Build compact payload — only send fields GPT needs for layout analysis
    compact_textboxes = [
        {
            "Name":   item.get("Name"),
            "Text":   item.get("Text", ""),
            "Top":    item.get("Top"),
            "Left":   item.get("Left"),
            "Height": item.get("Height"),
            "Width":  item.get("Width"),
        }
        for item in text_items
    ]

    compact_lines = [
        {
            "Name":   item.get("Name"),
            "Top":    item.get("Top"),
            "Left":   item.get("Left"),
            "Height": item.get("Height"),
            "Width":  item.get("Width"),
        }
        for item in line_items
    ]

    user_message = (
        "TEXTBOXES:\n"
        + json.dumps(compact_textboxes, ensure_ascii=False, indent=2)
        + "\n\nLINES:\n"
        + json.dumps(compact_lines, ensure_ascii=False, indent=2)
        + "\n\nPAGE:\n"
        + json.dumps(page, ensure_ascii=False, indent=2)
    )

    print(f"Sending {len(text_items)} textboxes and {len(line_items)} lines to GPT...")

    response = client.chat.completions.create(
        model=_MODEL,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user",   "content": user_message},
        ],
        temperature=0,
    )

    raw = response.choices[0].message.content.strip()
    print(f"GPT response received ({len(raw)} chars)\n")

    result = json.loads(raw)
    return result.get("input_boxes", [])


def build_in_text_json(input_boxes: list[dict]) -> dict:
    """
    Convert GPT output into the ReportItems format matching text.json structure.
    """
    report_items = []
    for box in input_boxes:
        report_items.append({
            "Name":          box.get("Name",        "Input_Textbox"),
            "DefaultName":   box.get("DefaultName", "Input_Textbox"),
            "CanGrow":       box.get("CanGrow",      True),
            "KeepTogether":  box.get("KeepTogether", True),
            "Text":          "",
            "FontSize":      box.get("FontSize",     "7pt"),
            "IsBold":        box.get("IsBold",       False),
            "FontWeight":    box.get("FontWeight",   "Normal"),
            "Top":           box.get("Top"),
            "Left":          box.get("Left"),
            "Height":        box.get("Height",       "0.434cm"),
            "Width":         box.get("Width"),
            "ZIndex":        box.get("ZIndex",       200),
            "Border":        box.get("Border",       "None"),
            "PaddingLeft":   box.get("PaddingLeft",  "2pt"),
            "PaddingRight":  box.get("PaddingRight", "2pt"),
            "PaddingTop":    box.get("PaddingTop",   "2pt"),
            "PaddingBottom": box.get("PaddingBottom","2pt"),
            "ForLabel":      box.get("ForLabel",     ""),
        })
    return {"ReportItems": report_items}


def main() -> int:
    # ── Load all three JSON files ──────────────────────────────────
    print(f"Loading text.json  from: {_TEXT_JSON}")
    text_data  = load_json(_TEXT_JSON)
    text_items = text_data.get("ReportItems", [])
    print(f"  {len(text_items)} textboxes loaded")

    print(f"Loading line.json  from: {_LINE_JSON}")
    line_data  = load_json(_LINE_JSON)
    line_items = line_data.get("Lines", [])
    print(f"  {len(line_items)} lines loaded")

    print(f"Loading page.json  from: {_PAGE_JSON}")
    page_data  = load_json(_PAGE_JSON)
    page       = page_data.get("Page", {})
    print(f"  Page: {page.get('PageWidth')} x {page.get('PageHeight')}\n")

    # ── Call GPT ───────────────────────────────────────────────────
    input_boxes = call_gpt(text_items, line_items, page)
    print(f"GPT identified {len(input_boxes)} input box location(s):")
    for box in input_boxes:
        print(f"  {box.get('Name')} → Top={box.get('Top')}, Left={box.get('Left')}, "
              f"Width={box.get('Width')}  [for: {box.get('ForLabel')}]")

    # ── Write in_text.json ─────────────────────────────────────────
    in_text_data = build_in_text_json(input_boxes)
    _IN_TEXT_OUT.parent.mkdir(parents=True, exist_ok=True)
    _IN_TEXT_OUT.write_text(
        json.dumps(in_text_data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"\nWrote {len(input_boxes)} input box(es) to {_IN_TEXT_OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())