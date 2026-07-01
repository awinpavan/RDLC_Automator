"""
place_input_boxes.py
=====================
Reads:
  - text_json/input.json   — input boxes with blank Top/Left
  - text_json/line.json    — line positions
  - text_json/page.json    — page dimensions
  - text_json/text.json    — existing textbox positions (for overlap check)

For each input box, finds the best position to the RIGHT of its label
without overlapping any textbox or line.

Writes: text_json/input.json  (overwrites with Top/Left filled in)

Usage:
    python place_input_boxes.py
"""

from __future__ import annotations

import json
from pathlib import Path


# ── Config ────────────────────────────────────────────────────────
_SCRIPT_DIR = Path(__file__).resolve().parent
_INPUT_JSON = _SCRIPT_DIR / "text_json" / "input.json"
_LINE_JSON  = _SCRIPT_DIR / "text_json" / "line.json"
_PAGE_JSON  = _SCRIPT_DIR / "text_json" / "page.json"
_TEXT_JSON  = _SCRIPT_DIR / "text_json" / "text.json"

# Gap between label right edge and input box left edge
_GAP_CM = 0.10

# Minimum input box width to be considered valid
_MIN_WIDTH_CM = 1.0

# Tolerance for vertical overlap checks (cm)
_V_TOL = 0.01


# ── Helpers ───────────────────────────────────────────────────────

def load_json(path: Path) -> dict:
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


def cm(value: str) -> float:
    """Parse '5.09739cm' → 5.09739. Returns 0.0 if blank."""
    if not value:
        return 0.0
    return float(str(value).strip().lower().replace("cm", "").strip())


def fmt(value: float) -> str:
    return f"{value:.5f}cm"


def overlaps_vertically(
    top_a: float, height_a: float,
    top_b: float, height_b: float,
    tol: float = _V_TOL,
) -> bool:
    """True if two vertical ranges overlap (with tolerance)."""
    return (top_a + tol) < (top_b + height_b) and (top_a + height_a - tol) > top_b


def find_right_position(
    label_top: float,
    label_left: float,
    label_width: float,
    input_height: float,
    input_width: float,
    max_right: float,
    obstacles: list[dict],  # each: {left, top, width, height, name}
) -> tuple[float, float] | None:
    """
    Try to place input box to the RIGHT of the label.
    Returns (top, left) if a valid position is found, else None.
    """
    candidate_top  = label_top
    candidate_left = label_left + label_width + _GAP_CM

    # Find the nearest obstacle to the right on the same row
    nearest_obstacle_left = max_right

    for obs in obstacles:
        obs_left   = obs["left"]
        obs_top    = obs["top"]
        obs_width  = obs["width"]
        obs_height = obs["height"]

        # Only obstacles that overlap vertically with input box row
        if not overlaps_vertically(candidate_top, input_height, obs_top, obs_height):
            continue

        # Obstacle is to the right of where we want to start
        if obs_left >= candidate_left:
            nearest_obstacle_left = min(nearest_obstacle_left, obs_left - _GAP_CM)

        # Obstacle overlaps with where we want to start — push right
        elif obs_left + obs_width > candidate_left:
            candidate_left = obs_left + obs_width + _GAP_CM

    available_width = nearest_obstacle_left - candidate_left

    # If not enough space to the right, try BELOW the label
    if available_width < _MIN_WIDTH_CM:
        return find_below_position(
            label_top, label_left, label_width,
            input_height, input_width, max_right, obstacles
        )

    # Clamp width to available space if input_width exceeds it
    actual_width = min(input_width, available_width)
    return candidate_top, candidate_left


def find_below_position(
    label_top: float,
    label_left: float,
    label_width: float,
    input_height: float,
    input_width: float,
    max_right: float,
    obstacles: list[dict],
) -> tuple[float, float] | None:
    """
    Fallback: try to place input box directly BELOW the label.
    """
    candidate_top  = label_top + input_height + _GAP_CM
    candidate_left = label_left

    # Check for vertical conflicts below
    for obs in obstacles:
        if not overlaps_vertically(candidate_top, input_height, obs["top"], obs["height"]):
            continue
        if obs["left"] < candidate_left + input_width and obs["left"] + obs["width"] > candidate_left:
            candidate_top = obs["top"] + obs["height"] + _GAP_CM

    return candidate_top, candidate_left


def build_obstacles(
    text_items: list[dict],
    line_items: list[dict],
) -> list[dict]:
    """
    Build a unified list of obstacles from textboxes and lines.
    For lines:
      - Horizontal line: Height=0, has Width  → treat as thin rectangle
      - Vertical line:   Width=0,  has Height → treat as thin rectangle
    """
    obstacles = []

    # Textboxes
    for tb in text_items:
        t = cm(tb.get("Top",    "0cm"))
        l = cm(tb.get("Left",   "0cm"))
        w = cm(tb.get("Width",  "0cm"))
        h = cm(tb.get("Height", "0cm"))
        if w > 0 and h > 0:
            obstacles.append({
                "name":   tb.get("Name", ""),
                "top":    t,
                "left":   l,
                "width":  w,
                "height": h,
            })

    # Lines
    for ln in line_items:
        t = cm(ln.get("Top",    "0cm"))
        l = cm(ln.get("Left",   "0cm"))
        w = cm(ln.get("Width",  "0cm"))
        h = cm(ln.get("Height", "0cm"))

        if h == 0 and w > 0:
            # Horizontal line — treat as very thin rectangle
            obstacles.append({
                "name":   ln.get("Name", ""),
                "top":    t - 0.02,
                "left":   l,
                "width":  w,
                "height": 0.04,
            })
        elif w == 0 and h > 0:
            # Vertical line — treat as very thin rectangle
            obstacles.append({
                "name":   ln.get("Name", ""),
                "top":    t,
                "left":   l - 0.02,
                "width":  0.04,
                "height": h,
            })

    return obstacles


def main() -> int:
    # ── Load all files ─────────────────────────────────────────────
    print(f"Loading input.json from: {_INPUT_JSON}")
    input_data  = load_json(_INPUT_JSON)
    input_items = input_data.get("ReportItems", [])
    print(f"  {len(input_items)} input box(es) to place")

    print(f"Loading line.json  from: {_LINE_JSON}")
    line_data   = load_json(_LINE_JSON)
    line_items  = line_data.get("Lines", [])
    print(f"  {len(line_items)} line(s) loaded")

    print(f"Loading page.json  from: {_PAGE_JSON}")
    page_data   = load_json(_PAGE_JSON)
    page        = page_data.get("Page", {})
    page_width  = cm(page.get("PageWidth",    "21.59cm"))
    right_margin = cm(page.get("RightMargin", "0.15cm"))
    max_right   = page_width - right_margin
    print(f"  Page: {page.get('PageWidth')} x {page.get('PageHeight')}")
    print(f"  Max right boundary: {fmt(max_right)}\n")

    print(f"Loading text.json  from: {_TEXT_JSON}")
    text_data   = load_json(_TEXT_JSON)
    text_items  = text_data.get("ReportItems", [])
    print(f"  {len(text_items)} textbox(es) loaded\n")

    # ── Build obstacle map ─────────────────────────────────────────
    obstacles = build_obstacles(text_items, line_items)
    print(f"Total obstacles (textboxes + lines): {len(obstacles)}\n")

    # ── Place each input box ───────────────────────────────────────
    print(f"  {'Name':<14} {'ForLabel':<14} {'LabelTop':<14} "
          f"{'LabelLeft':<14} → {'Top':<14} {'Left':<14} {'Status'}")
    print(f"  {'-'*13} {'-'*13} {'-'*13} {'-'*13}   {'-'*13} {'-'*13} {'-'*10}")

    placed  = 0
    skipped = 0

    for item in input_items:
        name         = item.get("Name", "")
        label_top    = cm(item.get("LabelTop",  ""))
        label_left   = cm(item.get("LabelLeft", ""))
        label_width  = cm(item.get("Width",     "2cm"))
        input_height = cm(item.get("Height",    "0.380cm"))
        input_width  = cm(item.get("Width",     "2cm"))

        if not item.get("LabelTop") or not item.get("LabelLeft"):
            print(f"  {name:<14} — LabelTop/LabelLeft missing, skipped")
            skipped += 1
            continue

        result = find_right_position(
            label_top, label_left, label_width,
            input_height, input_width, max_right, obstacles
        )

        if result is None:
            print(f"  {name:<14} {item.get('ForLabel',''):<14} "
                  f"{item.get('LabelTop',''):<14} {item.get('LabelLeft',''):<14} "
                  f"→ NO SPACE FOUND")
            skipped += 1
            continue

        new_top, new_left = result

        item["Top"]  = fmt(new_top)
        item["Left"] = fmt(new_left)

        # Add this placed input box as an obstacle for subsequent boxes
        obstacles.append({
            "name":   name,
            "top":    new_top,
            "left":   new_left,
            "width":  input_width,
            "height": input_height,
        })

        print(f"  {name:<14} {item.get('ForLabel',''):<14} "
              f"{item.get('LabelTop',''):<14} {item.get('LabelLeft',''):<14} "
              f"→ {fmt(new_top):<14} {fmt(new_left):<14} PLACED")
        placed += 1

    # ── Overwrite input.json ───────────────────────────────────────
    _INPUT_JSON.write_text(
        json.dumps(input_data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"\nResult: {placed} placed, {skipped} skipped")
    print(f"input.json updated at {_INPUT_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())