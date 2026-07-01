"""
identify_input_textboxes.py
============================
Calls the OpenAI (GPT) API to identify textboxes in text.json that contain
actual input/data values (e.g. guest name, dates, amounts) rather than
static field labels.

Writes ONLY the Name and Text of identified input textboxes to:
    text_json/null_text.json

Usage:
    pip install openai python-dotenv
    Create a .env file in the same folder as this script:
        OPENAI_API_KEY=sk-your-key-here
    python identify_input_textboxes.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI


# ── Config ────────────────────────────────────────────────────────
_SCRIPT_DIR    = Path(__file__).resolve().parent
_TEXT_JSON     = _SCRIPT_DIR / "text_json" / "text.json"
_NULL_TEXT_OUT = _SCRIPT_DIR / "text_json" / "null_text.json"
_ENV_FILE      = _SCRIPT_DIR / ".env"

_MODEL = "gpt-4o"


# ── Load API key from .env file ───────────────────────────────────
load_dotenv(dotenv_path=_ENV_FILE)


# ── Prompt ────────────────────────────────────────────────────────
_SYSTEM_PROMPT = """
You are a document analysis assistant specialising in hotel registration card data extraction.

You will be given a list of textbox items from a hotel registration card JSON file.
Each item has a "Name" and a "Text" field.

Your task is to identify ONLY the textboxes that contain actual INPUT VALUES —
meaning real data that was dynamically filled in for a specific guest or booking
by either the guest themselves or the hotel system/staff.

INCLUDE these as input values:
- Guest personal details (name, surname, first name, middle name)
- Dates (arrival date, departure date, date of birth — any date in any format)
- Room details (room number, room type, rate, daily rate)
- Booking/reservation references (reservation number, confirmation number)
- Guest counts (number of adults, number of children, number of nights)
- Contact details filled in (phone number, mobile, email address)
- Address details filled in (street, city, state, zip code, country, nationality)
- Payment amounts (total cost, daily rate, any monetary value)
- Passport/ID details filled in (passport number, place of issue, expiry date)
- Company/agent names filled in
- Purpose of visit values filled in
- Membership/loyalty program numbers filled in
- Wakeup call time values filled in
- Clerk codes, staff codes, system identifiers (e.g. "SAM000056@GHGBHE", "HGBHE")
- Any alphanumeric code that looks like a system-generated or staff-entered value
- Any text that is clearly a value filled into a blank field on the form

DO NOT INCLUDE these — they are permanent parts of the form template:
- Field labels ending with colon (e.g. "Full Name:", "Arrival Date:", "Room Number:")
- Field labels without colon (e.g. "City", "Country", "Nationality", "Surname")
- Section headers and titles (e.g. "Registration Card", "REGISTRATION", "Method Of Payment")
- Hotel name, hotel address, hotel contact information
- Terms and conditions text (any numbered or unnumbered policy text)
- Static instructional sentences (e.g. "I/We confirm the accuracy...")
- Checkbox option labels (e.g. "No ☐  Yes ☐", "Cash", "Visa", "Master", "American Express")
- Payment method labels (e.g. "Credit Card:", "Diners:", "Others:")
- Signature line labels (e.g. "Signature", "Guest Signature", "GSO Signature")
- Wakeup call label (e.g. "Wakeup Call")
- Purpose of visit option labels (e.g. "Leisure & Vacation", "Other Reasons", "Conference meeting" — ONLY if these are static checkbox options, NOT if they are filled-in values)
- Any text in Arabic or other languages that is a label/header translation
- "Enjoy your stay with us!" or similar closing messages
- Copyright, registration, VAT number text that is part of the hotel footer
- Any text that would appear identically on every printed copy of the blank form

DECISION RULE:
Ask yourself: "Would this text be blank on an empty/unfilled registration card?"
- If YES → it is an input value → INCLUDE it
- If NO  → it is a permanent label or template text → DO NOT INCLUDE it

Return ONLY a valid JSON object in this exact format with no explanation or markdown:
{
  "input_textboxes": ["Textbox10", "Textbox14", ...]
}
""".strip()


def load_text_json(path: Path) -> dict:
    if not path.is_file():
        raise FileNotFoundError(f"text.json not found at {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def call_gpt_to_identify_inputs(items: list[dict]) -> list[str]:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "OPENAI_API_KEY not found.\n"
            f"Make sure your .env file exists at {_ENV_FILE} and contains:\n"
            "  OPENAI_API_KEY=sk-your-key-here"
        )

    client = OpenAI(api_key=api_key)

    compact = [{"Name": item["Name"], "Text": item.get("Text", "")} for item in items]
    user_message = (
        "Here are the textbox items:\n\n"
        + json.dumps(compact, ensure_ascii=False, indent=2)
    )

    print(f"Sending {len(items)} textboxes to GPT for analysis...")

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
    print(f"GPT response:\n{raw}\n")

    result = json.loads(raw)
    return result.get("input_textboxes", [])


def build_null_text_json(items: list[dict], input_names: list[str]) -> dict:
    """
    Return only Name and Text for each identified input textbox.
    """
    name_set = set(input_names)
    filtered = [
        {"Name": item["Name"], "Text": item.get("Text", "")}
        for item in items
        if item["Name"] in name_set
    ]
    return {"ReportItems": filtered}


def main() -> int:
    print(f"Loading: {_TEXT_JSON}")
    data = load_text_json(_TEXT_JSON)
    items = data.get("ReportItems", [])
    print(f"Loaded {len(items)} textboxes.\n")

    input_names = call_gpt_to_identify_inputs(items)
    print(f"GPT identified {len(input_names)} input-value textbox(es):")
    for name in input_names:
        text = next((i["Text"] for i in items if i["Name"] == name), "?")
        print(f"  {name}: \"{text}\"")

    null_data = build_null_text_json(items, input_names)
    _NULL_TEXT_OUT.parent.mkdir(parents=True, exist_ok=True)
    _NULL_TEXT_OUT.write_text(
        json.dumps(null_data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"\nWrote {len(null_data['ReportItems'])} input textbox(es) to {_NULL_TEXT_OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())