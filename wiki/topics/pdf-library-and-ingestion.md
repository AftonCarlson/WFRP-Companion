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
pipeline. Phase 3 adds source-set selection over that indexed library. Phase 4
adds local API surfaces for the library, reader PDF stream, source-set toggles,
and exact search:

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
- Page-text import preserves optional page labels from JSON and, when JSON has
  no label, reads labels from the managed PDF with PyMuPDF. Runtime page
  identity is therefore `pages.page_number` for the PDF jump target plus
  optional `pages.page_label` for the printed/display page label.
- `tools/rebuild_fts.py` rebuilds the global exact-search projection in
  `page_search` and `page_search_fts`.
- `tools/source_sets.py` syncs the built-in `Rules/Core` source set and toggles
  per-book membership.
- `tools/search_text.py` queries imported text through SQLite FTS5, applies the
  active source set by default, and returns ranked book/page/snippet results.
- `wfrp_companion/library/catalog.py` exposes API-facing book/page read models
  and validates managed reader PDF paths.
- `/api/books/{book_id}/pdf` serves the managed local PDF inline with HTTP
  range support. It rejects unknown books, not-reader-ready books, missing
  managed files, non-PDF paths, and paths outside
  `data/library/pdfs/<book_id>/`.
- `/api/search/exact` uses the same scope resolver as `tools/search_text.py`
  and returns query, scope, snippets, scores, and book/page citations.

The managed-storage decision is recorded in
`docs/adr/0002-managed-local-pdf-storage.md`.

## Reader Responsibilities

[coverage: medium]

The GUI should allow a GM to open a book, navigate pages, search within the
book, and jump from a chat citation directly to the cited page. PDF.js is the
likely browser-side renderer.

The local API now provides the reader backend needed for that GUI:

- `GET /api/books` lists books with readiness flags but no private filesystem
  paths.
- `GET /api/books/{book_id}` returns book detail plus
  `managed_pdf_available`.
- `GET /api/books/{book_id}/pages/{page_number}` returns page identity,
  label, text/image counts, and text availability without returning raw page
  text.
- `GET /api/books/{book_id}/pdf` returns the managed PDF stream for PDF.js.

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
  counts, page text hashes, generated timestamps, and resolved page labels
  still match.
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
- Per-book filtering is supported by `book_id`.
- Source-set-aware search is implemented in `tools/search_text.py`: default
  search uses `app_settings.active_source_set_id`, `--source-set` uses a named
  source set, `--book-id` bypasses source sets for direct checks, and
  `--all-books` deliberately restores whole-library search.
- `wfrp_companion/search/scope.py` now owns that scope resolution for both CLI
  and API callers. API search validates explicit unknown `book_id` values as
  `404`; the CLI preserves its historical zero-hit behavior for unknown direct
  book IDs.
- `/api/search/exact` accepts `query`, `limit`, `source_set_id`, repeatable
  `book_id`, and `all_books` parameters.
- `/api/search/exact` returns `pdf_page_number` for reader jumps and
  `page_label` when a raw or calibrated printed label is available. The
  frontend should use `pdf_page_number` for Grimoire opens and display
  `page_label` only as printed-page context.
- Source-set membership is owned by `source_set_books.enabled`; readiness is
  still owned by `books` lifecycle state and enforced by `search_exact()`.

The real local FTS rebuild on 2026-06-04 indexed 26 books and 3,736 pages. A
rerun skipped the rebuild as current, and `tools/search_text.py "critical hit"`
returned cited exact-search hits.

The real local source-set sync on 2026-06-04 created `rules-core`, inserted 26
book membership rows, set it active, and enabled the `Core Book & GM Essentials`
and `Rules and Mechanics Toolkits` categories by default. Adventure modules and
world/faction sourcebooks remain disabled until individually enabled.

Phase 7 PR1 adds the source-object schema foundation for richer extraction:

- `source_objects` will store typed page spans for rules sections, tables,
  table rows, stat blocks, NPCs, monsters, locations, encounters, boxed text,
  map references, image references, index entries, cross references, and page
  fallback chunks.
- `source_object_links` will store explicit relationships between extracted
  objects and referenced objects/pages/books.
- `book_object_status` will own per-book source-object extraction/indexing
  readiness.
- `book_query_profiles` will store deterministic per-book evidence for which
  query types should be boosted.
- `source_object_search` and `source_object_search_fts` are rebuildable search
  projections over `source_objects`.

Phase 7 PR2 adds the first deterministic extractor:

- `wfrp_companion/source_objects/layout.py` reads optional PyMuPDF page layout
  metadata from managed PDFs when available and falls back safely when the PDF
  is missing or unreadable.
- `wfrp_companion/source_objects/store.py` owns eligible-book selection,
  text-snapshot hashing, extraction job claims, stale-running recovery, page
  loading, source-object replacement, and `book_object_status` updates.
- `wfrp_companion/source_objects/extractor.py` extracts page-local,
  deterministic `rule_section` objects from heading patterns and
  lower-confidence `page_chunk` fallback objects for uncovered text.
- `tools/extract_source_objects.py` runs extraction for all eligible books or
  repeatable `--book-id` filters, with `--force`, `--retry-running`, and
  `--stale-running-minutes` recovery options.
- OCR-derived pages are detected from `pages.extraction_method` values that
  start with `ocr`; confidence is capped when word geometry is unavailable.
- Rule-section IDs use page-local title-bucket ordinals and normalized text so
  inserting or removing unrelated earlier same-page headings does not churn
  unchanged later section IDs.
- CLI output reports counts and truncated failure summaries only. It must not
  print extracted book text.

The real local source-object smoke run on 2026-06-05 extracted one indexed
book into 738 source objects, then skipped the same book as current on rerun.
This proves the extractor, status row, job idempotency, and snapshot-drift
checks work against the live private database without committing private text.

Current boundary: source objects can now be populated, but object FTS,
table/stat/location extraction, and Familiar object-aware ranking remain later
Phase 7 PRs. Page-level `page_text` plus `page_search_fts` still remain the
active retrieval surface for Familiar and exact search.

Phase 7 PR10 adds printed page-label calibration/backfill:

- `wfrp_companion/library/page_labels.py` builds page-label calibration
  metadata from imported `pages.page_label` values plus optional offset
  anchors.
- `tools/backfill_page_labels.py` runs the backfill for all eligible copied and
  imported books or selected `--book-id` values. It supports
  `--anchor book_id:pdf_page_number:printed_label`, `--force`,
  `--retry-running`, and `--stale-running-minutes`.
- The backfill stores only calibration metadata and counts in
  `book_page_label_calibrations`; it does not export page text.
- Roman/front-matter labels before an offset anchor are preserved, and stored
  anchors are reused after page text/label snapshot drift on plain reruns.
  Pages without a proven label, or pages whose imported/calibrated labels
  conflict, are marked for manual review instead of being shown as confident
  printed-page citations.
- Exact search, Familiar prompt context, and reloaded chat citations prefer
  current calibrated labels/ranges. The PDF page number remains the jump target.

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

As of 2026-06-05, `tools/extract_page_text.py` also writes optional
`page_label` values from PyMuPDF, and the importer can backfill labels from the
managed PDF even for older JSON files that do not contain that field.

## Maps And Images

[coverage: low]

Maps and visual references should stay linked to PDF pages at first. Do not try
to solve map extraction before the reader plus citation loop works.

## Sources

- `wiki/topics/target-architecture.md`
- `wiki/topics/local-tooling-and-packaging.md`
- `docs/adr/0002-managed-local-pdf-storage.md`
- `docs/plans/2026-06-04-page-text-import-global-fts-implementation-plan.md`
- `docs/plans/2026-06-04-phase-3-source-sets-implementation-plan.md`
- `docs/plans/2026-06-04-phase-4-local-backend-api-implementation-plan.md`
- `docs/audits/2026-06-03-pdf-extraction-audit.md`
- `docs/audits/2026-06-03-page-text-ocr-extraction.md`
- `wiki/concepts/private-copyright-boundary.md`
