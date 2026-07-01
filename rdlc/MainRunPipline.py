"""
run_pipeline.py
================
Master pipeline runner — executes all 8 scripts in order.
Each script must complete successfully before the next one starts.
If any script fails, the pipeline stops immediately.

Usage:
    python run_pipeline.py
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path


# ── Pipeline steps — edit filenames and order as needed ──────────
# Each entry: ("Step description", "script_filename.py")
PIPELINE: list[tuple[str, str]] = [
    ("Parse PDF lines",                   "1_line_parser.py"),
    ("Parse PDF text and page",           "2_Test_Parser.py"),
    ("Identify input value textboxes",    "3_GPT_null_Textbox.py"),
    ("Clean input values from text.json", "4_null_text.py"),
    ("Match expressions to labels",       "5_GPT_input.py"),
    ("Place input boxes on page",         "6_InputLoc.py"),
    ("Merge input boxes into text.json",  "7_InputAddOn.py"),
    ("Generate RDLC file",                "8_text_xml_generator_Line_Text.py"),
]

# ── Config ────────────────────────────────────────────────────────
_SCRIPT_DIR = Path(__file__).resolve().parent
_PYTHON     = sys.executable   # uses the same Python that runs this file


# ── Helpers ───────────────────────────────────────────────────────

def divider(char: str = "─", width: int = 60) -> str:
    return char * width


def print_header() -> None:
    print()
    print(divider("═"))
    print("  RDLC PIPELINE RUNNER")
    print(f"  {len(PIPELINE)} steps to execute")
    print(divider("═"))
    print()


def print_step_start(index: int, total: int, description: str, script: str) -> None:
    print(divider())
    print(f"  STEP {index}/{total}  —  {description}")
    print(f"  Script : {script}")
    print(divider())


def print_step_result(success: bool, elapsed: float) -> None:
    status = "✓  PASSED" if success else "✗  FAILED"
    print(f"\n  {status}  ({elapsed:.2f}s)\n")


def print_summary(results: list[tuple[str, bool, float]]) -> None:
    print()
    print(divider("═"))
    print("  PIPELINE SUMMARY")
    print(divider("═"))
    total_time = sum(e for _, _, e in results)
    for i, (desc, success, elapsed) in enumerate(results, 1):
        icon   = "✓" if success else "✗"
        status = "OK    " if success else "FAILED"
        print(f"  {icon}  Step {i:2d}  [{status}]  {elapsed:6.2f}s  —  {desc}")
    print(divider())
    all_passed = all(s for _, s, _ in results)
    if all_passed:
        print(f"  ✓  ALL {len(results)} STEPS COMPLETED SUCCESSFULLY  ({total_time:.2f}s total)")
    else:
        failed = sum(1 for _, s, _ in results if not s)
        print(f"  ✗  PIPELINE FAILED — {failed} step(s) did not complete")
    print(divider("═"))
    print()


# ── Main ──────────────────────────────────────────────────────────

def main() -> int:
    print_header()

    results: list[tuple[str, bool, float]] = []
    total = len(PIPELINE)

    for i, (description, script_name) in enumerate(PIPELINE, start=1):
        script_path = _SCRIPT_DIR / script_name

        print_step_start(i, total, description, script_name)

        # Check script exists before running
        if not script_path.is_file():
            print(f"  ERROR: Script not found at {script_path}")
            results.append((description, False, 0.0))
            print_summary(results)
            return 1

        start = time.time()
        try:
            result = subprocess.run(
                [_PYTHON, str(script_path)],
                cwd=str(_SCRIPT_DIR),
                check=False,          # we handle returncode ourselves
            )
            elapsed = time.time() - start
            success = result.returncode == 0

        except Exception as exc:
            elapsed = time.time() - start
            success = False
            print(f"  EXCEPTION: {exc}")

        print_step_result(success, elapsed)
        results.append((description, success, elapsed))

        # Stop pipeline on first failure
        if not success:
            print(f"  Pipeline stopped at step {i} — '{description}' failed.")
            print(f"  Fix the error above and re-run.\n")
            break

    print_summary(results)
    all_passed = all(s for _, s, _ in results)
    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())