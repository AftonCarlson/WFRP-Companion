# PDF Library And Ingestion

## Library Responsibilities

[coverage: high]

The library should track each owned PDF with:

- Stable book id.
- Display title.
- File path or managed storage path.
- Page count.
- Extraction status.
- Optional cover image or first-page thumbnail.
- Optional edition/source metadata.

Avoid storing large copied text in fixtures or docs. Keep extracted text local.

Phase 2 implements the managed PDF library import and the first page-text/search
pipeline:

- `tools/import_pdfs.py` imports all readable PDFs from
  `/Users/aftoncarlson/TTRPGs/WFRP 2e` by default.
- The importer preserves source folder hierarchy in `library_folders`.
- Each readable PDF gets a stable `books.id` derived from the source-relative
  path without the PDF suffix.
- Each managed PDF is copied to
  `data/library/pdfs/<book_id>/source-<original_sha256>.pdf`.
- `books.original_source_path` and `books.managed_pdf_path` are absolute paths.
- `ingest_jobs` records idempotent `copy_pdf` work using
  `copy_pdf:<book_id>:<original_sha256>`.
- Failed or ambiguous candidates are surfaced through CLI failure details and
  failed `copy_pdf` jobs when the source can be hashed.
- Stale interrupted `running` copy jobs can be recovered by age or immediately
  with `--retry-running`.
- `tools/import_page_text.py` imports private OCR/text JSON from
  `data/page_text/<book_id>.json` into SQLite `pages` and `page_text`.
- `tools/rebuild_fts.py` rebuilds the global exact-search projection in
  `page_search` and `page_search_fts`.
- `tools/search_text.py` queries imported text through SQLite FTS5 and returns
  ranked book/page/snippet results.

The managed-storage decision is recorded in
`docs/adr/0002-managed-local-pdf-storage.md`.

## Reader Responsibilities

[coverage: medium]

The GUI should allow a GM to open a book, navigate pages, search within the
book, and jump from a chat citation directly to the cited page. PDF.js is the
likely browser-side renderer.

## Extraction Pipeline

[coverage: high]

Ingestion should run through the repo Conda environment and preserve page-level
provenance:

- Extract text page by page.
- Keep book id, page number, and extraction method.
- Detect low-text pages that may need OCR.
- Normalize whitespace enough for search without destroying table/list meaning.
- Chunk text with overlap, but keep every chunk tied back to page spans.

The initial extraction spike uses PyMuPDF from `environment.yml`, with Poppler
tools available for independent metadata/text-density cross-checks and
Tesseract available for OCR through PyMuPDF's OCR text-page path.

The first audit found that 24 of 26 PDFs returned zero embedded text on every
page. OCR should be treated as a near-term ingestion requirement rather than a
rare fallback.

Page-text import into SQLite is implemented in
`wfrp_companion/library/page_text_importer.py`. It treats ignored
`data/page_text/*.json` as compatibility input and makes SQLite the runtime
source of truth:

- Each JSON file must match a managed `books.id` and its filename.
- Imported pages are written to `pages`; page text and per-page text hashes are
  written to `page_text`.
- `books.text_status` moves through `importing`, `imported`, and `failed`.
- Successful jobs use
  `import_page_text:<book_id>:<json_sha256>`.
- File-level quarantine jobs use
  `import_page_text_file:<relative_json_path>:<json_sha256>` with no
  `target_id`.
- A current imported book is only skipped when the book status, JSON SHA, page
  counts, page text hashes, and generated timestamps still match.
- Failed or stale imports are repairable with a normal rerun, `--force`,
  `--retry-running`, or `--stale-running-minutes`.

The real local import run on 2026-06-04 imported 26 books and 3,736 pages from
ignored `data/page_text/` with 0 failures. A rerun skipped all 26 as current.

Exact search is implemented in `wfrp_companion/search/fts.py`:

- `rebuild_global_fts()` rebuilds one whole-library projection from copied,
  imported books into `page_search` and `page_search_fts`.
- `books.search_status` moves through `indexing`, `indexed`, and `failed`.
- Successful jobs use `rebuild_fts:global:<text_snapshot_sha256>`.
- Search is readiness-gated: `search_exact()` only returns hits for books with
  `copy_status='copied'`, `text_status='imported'`, and
  `search_status='indexed'`.
- Per-book filtering is supported by `book_id`, which is the basis for future
  user-controlled source-set toggles.

The real local FTS rebuild on 2026-06-04 indexed 26 books and 3,736 pages. A
rerun skipped the rebuild as current, and `tools/search_text.py "critical hit"`
returned cited exact-search hits.

## OCR

[coverage: medium]

Some PDFs are scanned, image-heavy, or have maps/tables with poor text layers.
The local extraction tool already uses OCR for those pages. OCR output should be
labeled so lower-confidence text can be treated carefully.

Page-level OCR output is stored under ignored `data/page_text/`, one record per
source page, with the source PDF path, page number, extraction method,
character count, word count, and text. These files are private local derived
data and must not be committed.

The page-text extraction tool is `tools/extract_page_text.py`. It generated
local text references for 26 PDFs / 3,736 pages under `data/page_text/` on
2026-06-03. The run produced 391 embedded-text pages, 3,214 OCR pages, and 131
empty OCR pages with source references preserved.

## Maps And Images

[coverage: low]

Maps and visual references should stay linked to PDF pages at first. Do not try
to solve map extraction before the reader plus citation loop works.

## Sources

- `wiki/topics/target-architecture.md`
- `wiki/topics/local-tooling-and-packaging.md`
- `docs/adr/0002-managed-local-pdf-storage.md`
- `docs/plans/2026-06-04-page-text-import-global-fts-implementation-plan.md`
- `docs/audits/2026-06-03-pdf-extraction-audit.md`
- `docs/audits/2026-06-03-page-text-ocr-extraction.md`
- `wiki/concepts/private-copyright-boundary.md`
