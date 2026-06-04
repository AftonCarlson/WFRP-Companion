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
- PDF extraction: PyMuPDF in the Conda environment for the initial ingestion
  spike; add OCR later only if extraction stats show it is needed.
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

Phase 2 populates the first library source-of-truth rows:

- `wfrp_companion/library/` owns PDF identity, discovery, managed storage, and
  SQLite import behavior.
- `tools/import_pdfs.py` imports every readable PDF from the configured source
  root into ignored managed local storage.
- `library_folders`, `books`, and `ingest_jobs` now have a working importer.
- `books.managed_pdf_path` is an absolute path to a versioned managed copy under
  `data/library/pdfs/<book_id>/source-<original_sha256>.pdf`.
- `book_readiness.reader_ready` becomes true when `books.copy_status='copied'`.

The schema already includes the planned tables for pages, page text, FTS
projection, source sets, visual assets, readiness state, and future AI
chat/retrieval metadata. Later phases will populate and serve those remaining
schema areas.

## Major Modules

[coverage: medium]

- Library: PDF registration, book metadata, file paths, cover thumbnails.
- Reader: in-browser PDF rendering, page navigation, citation links.
- Ingestion: text extraction, page segmentation, OCR fallback, chunking.
- Retrieval: full-text search, vector search, ranking, citation assembly.
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
- SQLite FTS5 is available through `page_search_fts`; population happens in a
  later phase.

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
- `wiki/concepts/private-copyright-boundary.md`
- `wiki/concepts/hybrid-search-for-rules.md`
