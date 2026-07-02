# RDLC_Automator

[![Python >=3.8](https://img.shields.io/badge/python-%3E%3D3.8-blue)]() [![License: MIT](https://img.shields.io/badge/license-MIT-lightgrey)]()

RDLC_Automator converts registration-card PDFs from hotel groups (or any card-style PDFs) into a Microsoft Report Builder (RDLC) template automatically. It analyzes page geometry and text, detects lines and textboxes, infers input fields and expressions, and then generates an RDLC file that reproduces the layout and bindings — saving hours of manual template creation.

Why this project matters
- Convert batches of registration cards into editable RDLC templates quickly.
- Preserve exact positions, fonts, and borders from the original PDFs.
- Automate detection of input fields and expressions so templates are ready-to-use.

Key features
- Robust text extraction using PyMuPDF (fitz).
- Line, rectangle and table-edge extraction using pdfplumber.
- Multi-stage pipeline (line extraction → text extraction → field matching → RDLC generation).
- CLI-friendly: run the full pipeline or individual steps for debugging.
- Produces intermediate JSON (text.json, line.json, page.json) for inspection.

Demo
Add a short animated GIF or screenshot at docs/demo.gif showing:
PDF input → extraction (text.json / line.json) → generated RDLC preview.

Quick start (recommended)
1. Clone the repo and create a venv:
   ```
   git clone https://github.com/awinpavan/RDLC_Automator.git
   cd RDLC_Automator
   python -m venv .venv
   source .venv/bin/activate    # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. Place sample input PDFs in:
   ```
   rdlc/pdf_doc/
   ```

3. Run the full pipeline:
   ```
   python rdlc/MainRunPipline.py
   ```
   The runner executes the 8-step pipeline in order. It stops on the first failure and prints progress.

Individual steps
- Extract lines (borders, table edges) → text_json/line.json
  ```
  python rdlc/1_line_parser.py path/to/card.pdf --out-dir rdlc/text_json
  ```
- Extract text / page dimensions → text_json/text.json, text_json/page.json
  ```
  python rdlc/2_Test_Parser.py
  ```
- Parse PDFs into parsed_pdf_doc/ (.txt + .json) and merge text_1.json:
  ```
  python rdlc/PyMudPdf.py --input-dir rdlc/pdf_doc --output-dir rdlc/parsed_pdf_doc
  ```
- Steps 3 → 7 (3_GPT_null_Textbox.py → 7_InputAddOn.py) perform field detection, cleaning and merging.
- Step 8 (8_text_xml_generator_Line_Text.py) generates the RDLC XML into:
  ```
  rdlc/rdlc_generated/
  ```

Repository layout (high-level)
```
rdlc/
  1_line_parser.py
  2_Test_Parser.py
  3_GPT_null_Textbox.py
  4_null_text.py
  5_GPT_input.py
  6_InputLoc.py
  7_InputAddOn.py
  8_text_xml_generator_Line_Text.py
  MainRunPipline.py
  PyMudPdf.py
  pdf_doc/               # input PDFs
  parsed_pdf_doc/        # per-PDF parsed outputs
  text_json/             # intermediate JSON (text.json, line.json, page.json)
  rdlc_generated/        # generated RDLC outputs
```

How it works (short)
1. Parse PDF pages for lines and rects (pdfplumber) → line.json
2. Extract text lines and font metadata (PyMuPDF) → text.json + page.json
3. Detect null placeholders / input-like text and clean noisy text
4. Match labels to input expressions and compute textbox placements
5. Merge results and generate RDLC (XML) that includes textboxes, placements, and expression placeholders

Tips for best results
- Use clean, high-resolution PDFs with consistent layout for best extraction quality.
- Add at least one representative sample PDF to rdlc/pdf_doc/ for quick testing.
- Inspect the intermediate JSON in rdlc/text_json/ to tune heuristics (font-size thresholds, merge tolerances).
- Provide a sample dataset and a demo GIF in the repo root to drive attention.

What to add to make the repo more attractive
- An examples/ folder: one sample PDF, the generated RDLC, and the JSON outputs.
- A short demo GIF (docs/demo.gif) referenced by the README.
- requirements.txt and a LICENSE (MIT recommended) — included here.
- A short CONTRIBUTING.md explaining how to submit PDFs and debug runs.

Troubleshooting
- If extraction misses text: try increasing PDF DPI or using a different PDF variant (some PDFs embed fonts in unusual ways).
- If the pipeline fails on a step, run that script directly to see its console output and inspect the created JSON files in rdlc/text_json/.

Contributing
Contributions, issues and feature requests are welcome. Useful contributions:
- Example PDFs covering different hotel card layouts.
- Heuristic improvements for field detection and expression mapping.
- A small web demo or GUI for one-click conversions.

License
This project currently does not include a license file. I recommend MIT if you want wide reuse. I can add LICENSE (MIT) on request.

Contact
Created by Awin Pavan — link to your GitHub profile or contact email here.
