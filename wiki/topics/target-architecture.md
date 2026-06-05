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

Phase 2 and Phase 3 populate the first library, text, exact-search, and
source-set source-of-truth rows:

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
- `wfrp_companion/library/source_sets.py` owns source-set creation, active
  source-set selection, per-book enablement, and the built-in `Rules/Core`
  source set.
- `tools/import_page_text.py`, `tools/rebuild_fts.py`, and
  `tools/search_text.py` provide the local command-line pipeline.
- `tools/source_sets.py` syncs the built-in source set and provides local
  listing, activation, enable, and disable commands.
- `tools/search_text.py` now searches the active source set by default, accepts
  `--source-set` for a named set, keeps `--book-id` for direct per-book checks,
  and uses `--all-books` as the explicit whole-library override.
- `book_readiness.search_ready` becomes true when the managed PDF is copied,
  page text is imported, and FTS search is indexed.

Phase 4 exposes the first local backend API over that SQLite state:

- `wfrp_companion/api/app.py` creates the FastAPI app and syncs the built-in
  source set at startup.
- `tools/serve_api.py` starts the local API with configurable host, port,
  data directory, and database path.
- `wfrp_companion/library/catalog.py` owns the read model for book lists, book
  detail, page references, and guarded managed-PDF reader paths.
- `/api/health` confirms the API is initialized without exposing private local
  paths.
- `/api/books`, `/api/books/{book_id}`,
  `/api/books/{book_id}/pages/{page_number}`, and
  `/api/books/{book_id}/pdf` expose library and reader data. The PDF route
  serves managed PDFs inline and relies on Starlette `FileResponse` for HTTP
  range requests.
- `/api/source-sets`, `/api/source-sets/active`, and
  `/api/source-sets/{source_set_id}/books/{book_id}` expose existing
  source-set state and per-book toggles.
- `wfrp_companion/search/scope.py` resolves default active source-set, named
  source-set, explicit book, and whole-library search scope for both CLI and
  API callers.
- `/api/search/exact` returns resolved scope, ranked snippets, and book/page
  citations while `search_exact()` remains the readiness gate.

Phase 5 adds the first browser GUI over the local API:

- `frontend/` is a React/Vite/TypeScript package with Vitest, Testing Library,
  Playwright, PDF.js, and lucide icons.
- `frontend/src/lib/apiClient.ts` is the only frontend module that calls
  `fetch()`.
- `frontend/src/state/workspaceState.ts` and
  `frontend/src/state/workspaceStorage.ts` own view-only state: panel sizes,
  collapsed/maximized panels, left-tab selection, collapsed library categories,
  and open PDF tabs.
- `localStorage` state is validated deeply before use. Malformed saved layouts
  fall back to defaults rather than reaching `AppShell`.
- The Library tab groups books by SQLite category and persists per-book toggles
  through `PUT /api/source-sets/{source_set_id}/books/{book_id}`.
- The Search tab calls `/api/search/exact`, shows grouped snippet results,
  lazily fetches full page text through
  `/api/books/{book_id}/pages/{page_number}/text`, and can open exact pages in
  the reader.
- `/api/books/{book_id}/pages/{page_number}/text` is search-readiness guarded;
  direct requests cannot return page text for books that are not indexed and
  searchable.
- `PdfReaderPanel` maintains one tab per opened book and renders the managed
  PDF through PDF.js from `/api/books/{book_id}/pdf`.
- `PdfCanvas` has loading, error, retry, high-DPI scaling, stale-render
  cancellation, and cleanup behavior covered by tests.
- `AgentChatPanel` is a UI-only chat shell. It does not write `chat_threads` or
  call model APIs yet.

The schema already includes the planned tables for pages, page text, FTS
projection, source sets, visual assets, readiness state, and future AI
chat/retrieval metadata. The current populated runtime source-of-truth areas
are library folders, books, pages, page text, page search, FTS, ingest jobs, and
the `book_readiness` view. Source-set state is now populated in `source_sets`,
`source_set_books`, and `app_settings.active_source_set_id`. The local API now
surfaces library, source-set, exact-search, page-text, and managed-PDF reader
operations. The frontend now surfaces library selection, exact search,
page-text expansion, PDF reading, and a chat placeholder. Later phases will
populate visual assets and AI chat/retrieval metadata.

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
- `source_sets` defines named selectable book groups.
- `source_set_books.enabled` is the explicit per-book membership toggle for a
  source set. It is not a search-readiness flag.
- `app_settings.active_source_set_id` stores the active source set for default
  retrieval/search scope.
- The built-in `rules-core` / `Rules/Core` source set enables
  `Core Book & GM Essentials` and `Rules and Mechanics Toolkits` by default and
  leaves other categories disabled until the user enables individual books.
- Readiness remains owned by `books` lifecycle columns and the
  `book_readiness` view; source sets decide scope, while search decides whether
  a scoped book is currently searchable.
- API responses must not expose `books.managed_pdf_path`; managed PDFs are only
  served through guarded reader endpoints under the configured local data dir.
- `/api/books/{book_id}/pages/{page_number}/text` reads full imported page text
  from SQLite `page_text`, requires `book_readiness.search_ready`, and
  intentionally returns no filesystem paths.

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
- `docs/plans/2026-06-04-phase-3-source-sets-implementation-plan.md`
- `docs/plans/2026-06-04-phase-4-local-backend-api-implementation-plan.md`
- `wiki/concepts/private-copyright-boundary.md`
- `wiki/concepts/hybrid-search-for-rules.md`
