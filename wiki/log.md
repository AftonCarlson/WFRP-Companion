# Wiki Compile Log

## 2026-06-03 Page Text OCR Extraction

- Added `tools/extract_page_text.py` to produce private local page-level text
  references under ignored `data/page_text/`.
- Added Tesseract to `environment.yml` and updated the Conda environment.
- Ran full extraction for `/Users/aftoncarlson/TTRPGs/WFRP 2e`: 26 books,
  3,736 page records, 15,612,529 characters, 2,668,305 words, 391 embedded-text
  pages, 3,214 OCR pages, 131 empty OCR pages, and 0 OCR errors.
- Recorded the count-only run summary in
  `docs/audits/2026-06-03-page-text-ocr-extraction.md`.

## 2026-06-03 PDF Extraction Audit

- Added `tools/pdf_audit.py` to audit PDF extraction quality without saving
  extracted book text.
- Ran the audit against `/Users/aftoncarlson/TTRPGs/WFRP 2e`.
- Recorded summary findings in
  `docs/audits/2026-06-03-pdf-extraction-audit.md`: 26 PDFs, 3,736 pages, 2
  PDFs with useful embedded text, and 24 likely image/scanned PDFs that need
  OCR strategy before reliable search/RAG ingestion.

## 2026-06-03 UI Hero Asset

- Added the generated pixel-art UI banner at `assets/ui/buttlordxai-hero.png`.
- Replaced the initial banner source with
  `/Users/aftoncarlson/Downloads/Gemini_Generated_Image_4dky2p4dky2p4dky (1).png`
  while keeping the app-facing asset path stable.
- Replaced the banner again with
  `/Users/aftoncarlson/Downloads/Gemini_Generated_Image_yu4cwbyu4cwbyu4c.png`,
  still keeping the same app-facing path.
- Replaced the banner again with
  `/Users/aftoncarlson/Downloads/Gemini_Generated_Image_xipclexipclexipc-clean.png`,
  still keeping the same app-facing path.
- Added `assets/ui/README.md` to record source path, dimensions, format, and
  intended usage.
- Updated UI/UX and local tooling wiki topics to treat `assets/ui/` as the
  repo-owned source asset location until a frontend asset pipeline exists.

## 2026-06-03 Conda Python Tooling

- Accepted Conda as the canonical Python package manager for the project.
- Added `environment.yml` with Python 3.12, PyMuPDF, Poppler, pytest, and ruff.
- Added ADR `docs/adr/0001-conda-python-tooling.md`.
- Updated local tooling, target architecture, PDF ingestion, implementation
  standards, and testing topics to use the `wfrp-companion` Conda environment.

## 2026-06-03 Initial Development Scaffold

- Created root agent guidance in `CLAUDE.md` and `AGENTS.md`.
- Added the initial wiki navigation layer: `CONTEXT.md`, `INDEX.md`,
  `schema.md`, and this log.
- Added initial topic pages for project overview, target architecture, PDF
  ingestion, AI/RAG, UI/UX, local tooling, implementation standards, and tests.
- Added concepts for the private copyright boundary and hybrid search strategy.
- No application code exists yet; these pages describe the intended development
  system and MVP architecture.
