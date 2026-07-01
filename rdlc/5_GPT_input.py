"""
generate_input_expressions.py
==============================
1. Loads text_json/text.json and text_json/expressions.json
2. GPT matches textbox labels to expression fields
3. Creates input textboxes with:
   - Top, Left left BLANK (for next GPT call to decide position)
   - LabelTop, LabelLeft copied from the matched label textbox
   - All other fields copied from the matched label textbox
4. Writes text_json/input.json

Usage:
    pip install openai python-dotenv
    python generate_input_expressions.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI


# ── Config ────────────────────────────────────────────────────────
_SCRIPT_DIR       = Path(__file__).resolve().parent
_TEXT_JSON        = _SCRIPT_DIR / "text_json" / "text.json"
_EXPRESSIONS_JSON = _SCRIPT_DIR / "text_json" / "expressions.json"
_INPUT_OUT        = _SCRIPT_DIR / "text_json" / "input.json"
_ENV_FILE         = _SCRIPT_DIR / ".env"

_MODEL = "gpt-4o"

load_dotenv(dotenv_path=_ENV_FILE)


# ── Prompt ────────────────────────────────────────────────────────
_SYSTEM_PROMPT = """
You are a hotel registration card data mapping assistant.

You will receive:
1. A list of textboxes from a registration card (each has "Name" and "Text")
2. A list of expression fields (each has "label_keywords", "expression", "field_key")

Your task:
- Compare each textbox's "Text" value against the "label_keywords" of each expression field
- A match occurs when the textbox text is the same as, contains, or is similar to any keyword
- Partial matches are valid (e.g. "Full Name:" matches keyword "First Name" or "Last Name")
- Bilingual labels are valid (e.g. "Nombre/Name:" matches keyword "Nombre" or "Name")
- Strip colons, slashes, and extra spaces when comparing
- A textbox can only match ONE expression field (the best/closest match)
- Each expression field can only be matched ONCE (no duplicates)

Return ONLY valid JSON with no explanation in this exact format:
{
  "matches": [
    {
      "textbox_name": "Textbox9",
      "textbox_text": "NIF/VAT:",
      "field_key": "RoomNumber",
      "expression": "=Lookup(\\"RoomNumber\\", Fields!FieldName.Value, Fields!FieldValue.Value, \\"DataSet1\\")"
    }
  ]
}

Only include textboxes that have a confident match. Skip any that do not clearly match.
""".strip()


# ── Helpers ───────────────────────────────────────────────────────

def load_json(path: Path) -> dict:
    """Load JSON with BOM stripping and error handling."""
    if not path.is_file():
        raise FileNotFoundError(f"File not found: {path}")
    raw = path.read_bytes()
    if raw.startswith(b'\xef\xbb\xbf'):
        raw = raw[3:]
    text = raw.decode("utf-8").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        decoder = json.JSONDecoder()
        obj, _ = decoder.raw_decode(text)
        return obj


def call_gpt_match(
    text_items: list[dict],
    expression_fields: list[dict],
) -> list[dict]:
    """Send textboxes and expressions to GPT for matching."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise EnvironmentError(
            f"OPENAI_API_KEY not found. Check {_ENV_FILE}"
        )

    client = OpenAI(api_key=api_key)

    compact_textboxes = [
        {"Name": item["Name"], "Text": item.get("Text", "")}
        for item in text_items
    ]

    compact_expressions = [
        {
            "label_keywords": field["label_keywords"],
            "expression":     field["expression"],
            "field_key":      field["field_key"],
        }
        for field in expression_fields
    ]

    user_message = (
        "TEXTBOXES FROM text.json:\n"
        + json.dumps(compact_textboxes, ensure_ascii=False, indent=2)
        + "\n\nEXPRESSION FIELDS FROM expressions.json:\n"
        + json.dumps(compact_expressions, ensure_ascii=False, indent=2)
    )

    print(f"Sending {len(text_items)} textboxes and "
          f"{len(expression_fields)} expression fields to GPT...")

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
    result = json.loads(raw)
    return result.get("matches", [])


def build_input_textbox(
    match: dict,
    label_textbox: dict,
    input_index: int,
) -> dict:
    """
    Build an input textbox from the matched label textbox.

    Changes from the label textbox:
      - Name, DefaultName  → InputBox1, InputBox2, ...
      - Text               → the RDLC expression
      - Top                → "" (blank — next GPT call decides)
      - Left               → "" (blank — next GPT call decides)
      - ZIndex             → 500 + index

    Adds:
      - LabelTop           → the label textbox's Top (reference for next GPT call)
      - LabelLeft          → the label textbox's Left (reference for next GPT call)
      - ForLabel           → which textbox Name this input is for
      - ForLabelText       → the label's text content
      - FieldKey           → the dataset field key
    """
    input_name = f"InputBox{input_index}"

    # Copy all fields from the label textbox
    input_box = dict(label_textbox)

    # ── Fields that change ─────────────────────────────────────────
    input_box["Name"]        = input_name
    input_box["DefaultName"] = input_name
    input_box["Text"]        = match["expression"]
    input_box["ZIndex"]      = 500 + input_index

    # ── Store label's original position as reference ───────────────
    input_box["LabelTop"]    = label_textbox.get("Top",  "")
    input_box["LabelLeft"]   = label_textbox.get("Left", "")

    # ── Blank out position — next GPT call will decide ─────────────
    input_box["Top"]         = ""
    input_box["Left"]        = ""

    # ── Relationship metadata ──────────────────────────────────────
    input_box["ForLabel"]     = match["textbox_name"]
    input_box["ForLabelText"] = match["textbox_text"]
    input_box["FieldKey"]     = match["field_key"]

    return input_box


def main() -> int:
    # ── Load files ─────────────────────────────────────────────────
    print(f"Loading text.json        from: {_TEXT_JSON}")
    text_data  = load_json(_TEXT_JSON)
    text_items = text_data.get("ReportItems", [])
    print(f"  {len(text_items)} textboxes loaded")

    print(f"Loading expressions.json from: {_EXPRESSIONS_JSON}")
    expr_data         = load_json(_EXPRESSIONS_JSON)
    expression_fields = expr_data.get("fields", [])
    print(f"  {len(expression_fields)} expression fields loaded\n")

    # Build lookup map
    tb_by_name = {item["Name"]: item for item in text_items}

    # ── Call GPT ───────────────────────────────────────────────────
    matches = call_gpt_match(text_items, expression_fields)

    print(f"\nGPT found {len(matches)} match(es):\n")
    print(f"  {'Input Box':<14} {'Label Textbox':<14} {'Label Text':<40} {'Field Key'}")
    print(f"  {'-'*13} {'-'*13} {'-'*39} {'-'*20}")

    # ── Build input textboxes ──────────────────────────────────────
    report_items = []
    skipped      = []

    for i, match in enumerate(matches, start=1):
        tb_name = match.get("textbox_name")
        label   = tb_by_name.get(tb_name)

        if not label:
            skipped.append(tb_name)
            print(f"  WARNING: {tb_name} not found in text.json — skipped")
            continue

        input_box = build_input_textbox(match, label, i)
        report_items.append(input_box)

        print(f"  {'InputBox' + str(i):<14} {tb_name:<14} "
            f"{match.get('textbox_text', '')[:38]:<40} "
            f"{match.get('field_key', '')}")

    # ── Write input.json ───────────────────────────────────────────
    out_data = {"ReportItems": report_items}
    _INPUT_OUT.parent.mkdir(parents=True, exist_ok=True)
    _INPUT_OUT.write_text(
        json.dumps(out_data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"\nWrote {len(report_items)} input textbox(es) to {_INPUT_OUT}")
    if skipped:
        print(f"Skipped {len(skipped)} unresolved: {skipped}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())