# Target Architecture

## MVP Shape

[coverage: medium]

The first useful version should be a local-first web app with:

- A browser GUI for library/search/chat.
- A small backend API for PDF ingestion, indexing, retrieval, and AI calls.
- Local storage for PDFs, extracted text, indexes, and campaign notes.
- OpenAI API integration for assistant responses.

The recommended default is a practical split:

- Frontend: React with Vite or Next.js.
- Backend: Python FastAPI or Node/TypeScript. Python dependencies are managed
  with Conda via `environment.yml`.
- PDF viewing: PDF.js.
- PDF extraction: PyMuPDF in the Conda environment, with Tesseract OCR
  available for scanned/image-heavy pages.
- Database: SQLite for app metadata and campaign state.
- Search: SQLite FTS or Tantivy-style full-text index plus a vector store.
- Vector store: LanceDB, Chroma, or pgvector depending on chosen backend.

Pick exact dependencies when implementation starts and verify current docs.
The first Python dependency decision is recorded in
`docs/adr/0001-conda-python-tooling.md`.

Phase 1 implementation has started the target architecture:

- `wfrp_companion/config.py` owns local path configuration.
- `wfrp_companion/db/schema.sql` defines the SQLite source-of-truth schema.
- `wfrp_companion/db/connection.py` initializes SQLite with foreign keys and
  WAL mode.
- `tools/init_db.py` creates the local database.

Phase 2 populates the first library, text, and exact-search source-of-truth
rows:

- `wfrp_companion/library/` owns PDF identity, discovery, managed storage, and
  SQLite import behavior.
- `tools/import_pdfs.py` imports every readable PDF from the configured source
  root into ignored managed local storage.
- `library_folders`, `books`, and `ingest_jobs` now have a working importer.
- `books.managed_pdf_path` is an absolute path to a versioned managed copy under
  `data/library/pdfs/<book_id>/source-<original_sha256>.pdf`.
- `book_readiness.reader_ready` becomes true when `books.copy_status='copied'`.
- `wfrp_companion/library/page_text_importer.py` imports private
  `data/page_text/<book_id>.json` files into `pages` and `page_text`.
- `wfrp_companion/search/fts.py` owns the global exact-search rebuild and query
  path over `page_search` and `page_search_fts`.
- `tools/import_page_text.py`, `tools/rebuild_fts.py`, and
  `tools/search_text.py` provide the local command-line pipeline.
- `book_readiness.search_ready` becomes true when the managed PDF is copied,
  page text is imported, and FTS search is indexed.

The schema already includes the planned tables for pages, page text, FTS
projection, source sets, visual assets, readiness state, and future AI
chat/retrieval metadata. The current populated runtime source-of-truth areas
are library folders, books, pages, page text, page search, FTS, ingest jobs, and
the `book_readiness` view. Later phases will populate visual assets, source-set
UI state, API surfaces, reader surfaces, and AI chat/retrieval metadata.

## Major Modules

[coverage: medium]

- Library: PDF registration, book metadata, file paths, cover thumbnails.
- Reader: in-browser PDF rendering, page navigation, citation links.
- Ingestion: text extraction, page segmentation, OCR fallback, chunking.
- Retrieval: full-text search, future vector search, ranking, citation
  assembly.
- Assistant: prompt construction, model calls, streamed responses, refusal when
  context is insufficient.
- Campaign: notes, session summaries, NPCs, locations, adventure prep artifacts.

## SQLite Source Of Truth

[coverage: high]

SQLite is now the app-owned metadata source of truth. The database schema lives
in `wfrp_companion/db/schema.sql` and is initialized by `tools/init_db.py`.

Important schema decisions:

- `books` has explicit lifecycle columns for copy, text, search, and visual
  status.
- Managed PDF copy state is owned by `books.copy_status`,
  `books.managed_pdf_path`, `books.original_sha256`, `books.managed_sha256`,
  and `ingest_jobs(job_type='copy_pdf')`.
- `book_readiness` is a derived view. Do not add a second mutable readiness
  status.
- `page_assets` is tied back to `pages` with a composite foreign key so asset
  rows cannot drift from their referenced page.
- Boolean-like fields use `check (... in (0, 1))` constraints.
- SQLite FTS5 is populated through a whole-library rebuild in
  `wfrp_companion/search/fts.py`.
- `page_search` is a rebuildable projection, not canonical text storage.
- `page_search_fts` is a rebuildable FTS5 index over `page_search`.
- Runtime page text is owned by `pages` and `page_text`; ignored JSON files
  under `data/page_text/` are import inputs, not application state.
- `ingest_jobs(job_type='import_page_text')` and
  `ingest_jobs(job_type='rebuild_fts')` record idempotent text/search work.
- Exact search reads only books whose lifecycle columns make them search-ready.

## Local-First Boundary

[coverage: high]

Default to keeping PDFs, extracted text, indexes, and notes on the user's
machine. Only send the minimum retrieved context and user prompt to the model
provider for an answer.

## Future Hosted Option

[coverage: medium]

A hosted option can exist later, but it should be explicit. Hosting changes the
privacy, copyright, backup, auth, and cost profile enough that it should be an
intentional decision rather than an accidental architecture drift.

## Sources

- `wiki/topics/project-overview.md`
- `wiki/topics/local-tooling-and-packaging.md`
- `docs/adr/0001-conda-python-tooling.md`
- `docs/adr/0002-managed-local-pdf-storage.md`
- `docs/plans/2026-06-04-page-text-import-global-fts-implementation-plan.md`
- `wiki/concepts/private-copyright-boundary.md`
- `wiki/concepts/hybrid-search-for-rules.md`
