# Wiki Compile Log

## 2026-06-04 Phase 3 Source Sets And Search Scoping

- Added the Phase 3 implementation plan at
  `docs/plans/2026-06-04-phase-3-source-sets-implementation-plan.md`.
- Added `wfrp_companion/library/source_sets.py` as the SQLite-backed owner for
  source-set sync, active source-set selection, and per-book enablement.
- Added `tools/source_sets.py` with `init`, `list`, `books`, `activate`,
  `enable`, and `disable` commands.
- Created the built-in `rules-core` / `Rules/Core` source set over the real
  local library: 26 book rows were inserted, the source set was made active,
  core/GM essentials and rules/mechanics books were enabled by default, and
  adventure/world books were left disabled.
- Updated `tools/search_text.py` so exact search uses the active source set by
  default, supports `--source-set`, keeps direct `--book-id` filters, and uses
  `--all-books` as the explicit whole-library override.
- Kept the ownership boundary explicit: `source_set_books.enabled` controls
  scope membership, while `books.copy_status`, `books.text_status`,
  `books.search_status`, `book_readiness`, and `search_exact()` control search
  readiness.
- Added regression coverage for source-set bootstrap/idempotency/conflicts,
  malformed active settings, per-book toggles, source-set CLI behavior, active
  source-set search defaults, whole-library override behavior, and enabled but
  not-indexed books being suppressed by search readiness.
- Ran the full coverage gate across `wfrp_companion` and tracked tool modules:
  146 tests passed with 100% coverage. `ruff check .` also passed.
- Completed independent implementation review, fixed the reported source-set
  membership/readiness boundary issue, and received code green-light pending
  this wiki refresh.

## 2026-06-04 Page Text Import And Global FTS Search

- Added the execution plan at
  `docs/plans/2026-06-04-page-text-import-global-fts-implementation-plan.md`.
- Added `wfrp_companion/library/page_text_importer.py` and
  `tools/import_page_text.py` to import ignored private
  `data/page_text/<book_id>.json` files into SQLite `pages` and `page_text`.
- Added `wfrp_companion/search/fts.py`, `tools/rebuild_fts.py`, and
  `tools/search_text.py` for a whole-library SQLite FTS5 projection over
  copied, text-imported books.
- Kept per-book lifecycle ownership explicit through `books.text_status`,
  `books.search_status`, and idempotent `ingest_jobs` keys for
  `import_page_text` and `rebuild_fts`.
- Ran the real local import and search pipeline: 26 books imported from
  page-text JSON, 3,736 pages imported, 26 books indexed, 3,736 pages indexed,
  and exact search returned cited book/page hits.
- Added regression coverage for idempotent import, failed import repair,
  malformed JSON quarantine, same-key running job protection, stale job
  recovery, stale FTS projection cleanup, readiness-gated search, per-book
  filters, and CLI entrypoints.
- Ran the full coverage gate across `wfrp_companion` and tool modules: 120
  tests passed with 100% coverage. `ruff check .` also passed.
- Completed independent implementation review and fixed the reported P1/P2
  issues before this wiki refresh.

## 2026-06-04 Phase 2 Managed PDF Library Import

- Added the Phase 2 implementation plan at
  `docs/plans/2026-06-04-phase-2-managed-pdf-library-import-implementation-plan.md`.
- Accepted ADR `docs/adr/0002-managed-local-pdf-storage.md` for local managed
  PDF copies, absolute `books.managed_pdf_path`, and versioned
  `source-<original_sha256>.pdf` filenames.
- Added `wfrp_companion/library/` with identity, discovery, storage, and
  importer modules for local managed PDF import.
- Added `tools/import_pdfs.py`, which imports all readable PDFs from the
  configured source root, validates the root before initializing SQLite, and
  reports copy/failure summaries without printing book text.
- Ran the importer against `/Users/aftoncarlson/TTRPGs/WFRP 2e`: 26 candidates,
  26 copied, 0 failed. A rerun reported 26 skipped current, confirming
  idempotency.
- Added tests for book/folder identity, recursive PDF discovery, atomic managed
  copy storage, SQLite import state, collision/failure reporting, stale job
  recovery, and CLI behavior.
- Updated `.gitignore` to scope local data ignores to repo-root paths so
  `wfrp_companion/library/` and `tests/library/` can be tracked while generated
  `data/` remains ignored.

## 2026-06-03 Phase 1 SQLite Foundation

- Added the durable implementation plan at
  `docs/plans/2026-06-03-local-reference-library-implementation-plan.md`.
- Added the first app package under `wfrp_companion/`.
- Added config loading in `wfrp_companion/config.py` for `WFRP_PDF_ROOT`,
  `WFRP_DATA_DIR`, `WFRP_DB_PATH`, and `WFRP_ASSET_DIR`.
- Added SQLite connection/schema initialization in
  `wfrp_companion/db/connection.py` and `wfrp_companion/db/schema.sql`.
- Added `tools/init_db.py`, which works both as `python tools/init_db.py` and
  as an imported CLI main.
- Expanded `environment.yml` with FastAPI, Uvicorn, Pillow, OpenCV, ImageHash,
  and pytest-cov for planned API/image work and coverage enforcement.
- Added `tests/db/test_schema.py` with 100% coverage over the new Python
  package and init CLI.
- Updated `.gitignore` to keep `.coverage*` out of Git.

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
