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
- The Library tab groups books by SQLite category, persists per-book toggles
  through `PUT /api/source-sets/{source_set_id}/books/{book_id}`, and exposes
  section-level bulk checkboxes that call the same endpoint for each changed
  book in the visible category.
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
- `AgentChatPanel` now creates chat threads, sends messages through
  `/api/chat/threads/{thread_id}/messages/stream`, renders streamed Familiar
  deltas, shows failed provider runs, and opens citations in the reader.
- `wfrp_companion/assistant/chat_service.py` owns the server-side Familiar loop:
  idempotent user-message acceptance, source-set snapshot retrieval, prompt
  assembly, provider streaming, and completed/failed model-run persistence.
- `wfrp_companion/assistant/provider.py` wraps the OpenAI Responses API with
  `stream=True`; the API key stays server-side in `OPENAI_API_KEY`.
- `tools/dev.py` starts the local API and Vite frontend together and waits for
  readiness probes.

Phase 7 PR1 adds the typed source-object schema and migration foundation:

- `schema_migrations` records applied local SQLite migrations.
- `wfrp_companion/db/migrations.py` owns explicit migration application for
  existing SQLite databases. It refuses missing or uninitialized DB paths,
  preflights legacy retrieval-hit rank conflicts, applies DDL inside a real
  rollbackable transaction, and records a migration only after all work
  succeeds.
- `tools/migrate_db.py` applies pending local migrations and reports row counts
  only. It must not print private extracted book text.
- `source_objects`, `source_object_links`, `book_object_status`,
  `book_query_profiles`, `source_object_search`, and
  `source_object_search_fts` are now part of the target SQLite schema.
- `wfrp_companion/source_objects/models.py` owns the first source-object model
  contracts and deterministic source-object IDs. IDs hash normalized text so
  whitespace-only OCR changes do not churn identifiers.

Phase 7 PR2 adds the first deterministic source-object extraction foundation:

- `wfrp_companion/source_objects/layout.py` reads PyMuPDF page layout metadata
  when the managed PDF is available and returns an empty layout set when it is
  missing or unreadable.
- `wfrp_companion/source_objects/store.py` owns source-object extraction
  eligibility, text snapshot hashes, job claims, stale-running recovery,
  source-object replacement, and `book_object_status` updates.
- `wfrp_companion/source_objects/extractor.py` creates `rule_section` objects
  from heading patterns and `page_chunk` fallback objects for uncovered text.
- `tools/extract_source_objects.py` runs that extraction for the eligible
  library or selected `--book-id` values.
- Rule-section IDs use page-local title-bucket ordinals plus normalized text
  hashes so unrelated earlier same-page headings do not churn unchanged later
  section IDs.

Phase 7 PR3 adds the first Familiar source-map/object-aware retrieval
integration:

- Source-object extraction now writes `source_object_search` rows and rebuilds
  `source_object_search_fts`; `book_object_status.status='indexed'` means the
  extracted objects have a current search projection.
- Familiar resolves checked books from the thread's active source set for each
  new model run and stores that source snapshot in
  `retrieval_runs.metadata_json`.
- Retrieval builds a compact enabled-book source map, generates page-FTS and
  source-object candidates, resolves candidates to complete source-object spans
  when available, and reranks candidates with deterministic semantic-overlap
  scoring before prompt assembly.
- Prompt context and citations are assembled only from the checked-book
  snapshot. Citations retain `pdf_page_number` for Grimoire jumps while
  displaying printed page labels or ranges.

Phase 7 PR4 keeps retrieval behavior stable while splitting
`wfrp_companion/assistant/retrieval.py` into focused retrieval modules:

- `retrieval.py` remains the public facade for `retrieve_context()` and
  re-exports the current retrieval contracts for compatibility.
- `source_map.py`, `query_planner.py`, `candidates.py`, `evidence.py`, and
  `reranking.py` now own the separable parts of the retrieval pipeline.
- This split is the scaffolding for later durable source-map/profile state,
  object-search backfills, rank fusion, vector candidates, table/stat/glossary
  extraction, and page-label calibration.

Phase 7 PR5 adds durable source-map/profile ownership over those focused
retrieval modules:

- Migration `0002_source_map_retrieval` adds `book_retrieval_status`,
  `book_source_maps`, and `retrieval_run_source_books` to both fresh schemas
  and migrated SQLite databases.
- `wfrp_companion/source_objects/source_map_builder.py` owns source-map
  eligibility, source-map input snapshots, guarded rebuild jobs, stale-running
  recovery, source-map persistence, and derived `book_query_profiles` rebuilds.
- `tools/rebuild_source_maps.py` is the local count-oriented CLI for rebuilding
  those source maps after source-object extraction.
- `wfrp_companion/assistant/source_map.py` now prefers current durable
  `book_source_maps` for the checked books on a Familiar run and falls back to
  dynamic source-map construction for missing, stale, or malformed durable
  rows.
- `wfrp_companion/assistant/chat_store.py` snapshots each retrieval run's
  checked books into `retrieval_run_source_books`, preserving a queryable proof
  of Library scope alongside the JSON compatibility metadata.

Phase 7 PR6 adds a standalone source-object search backfill path:

- `wfrp_companion/source_objects/store.py::rebuild_source_object_search()`
  rebuilds `source_object_search` and `source_object_search_fts` from current
  `source_objects` without rerunning source-object extraction.
- `tools/rebuild_source_object_fts.py` is the count-oriented local CLI for
  repairing missing or stale object-search projections.
- The backfill uses existing `ingest_jobs(job_type='rebuild_source_object_fts')`
  and `book_object_status.status='indexing'/'indexed'` transitions so projection
  readiness stays explicit and repairable. Currentness checks validate both the
  projection rows and the FTS index rowids, object-type postings, and
  vocabulary before skipping a rebuild.

Phase 7 PR7 adds the rank-fusion/reranker seam for later vector retrieval:

- `wfrp_companion/assistant/candidates.py` now keeps channel candidates long
  enough for RRF instead of immediately collapsing the pool to one best
  lexical hit per evidence key.
- `wfrp_companion/assistant/reranking.py` exposes `ReciprocalRankFusion`,
  `Reranker`, and `DeterministicReranker`; `retrieve_context()` still uses the
  deterministic local reranker by default.
- RRF reasons and deterministic reranker judgments are preserved on selected
  hits through `retrieval_hits.rank_reasons_json`, making ranking decisions
  auditable without logging private book text.
- The reranker remains the authority for whether a lexical/object candidate is
  relevant enough to enter prompt context. Weak lexical-only hits can be
  rejected, while exact object-type queries such as table lookups are preserved
  through normalized source-object type relevance text.
- Vector candidates, embeddings, and provider/local cross-encoder rerankers
  remain later phases and should attach to this pipeline as additional
  candidate/reranker implementations under the same checked-book scope.

Phase 7 PR8 attaches the first local vector candidate implementation to that
pipeline:

- Migration `0003_vector_retrieval` adds `source_object_embeddings`, keyed by
  source object, book, embedding model, embedding dimensions, and text snapshot.
- `wfrp_companion/source_objects/embeddings.py` owns the deterministic
  `local-hash` embedding MVP, vector blob encoding, embedding snapshot hashes,
  guarded rebuild jobs, stale-running recovery, currentness checks, and status
  writes.
- `tools/rebuild_embeddings.py` is the count-oriented local CLI. It applies
  pending migrations before using `ingest_jobs(job_type='rebuild_embeddings')`
  so existing databases are repaired before vector rebuilds begin.
- `wfrp_companion/assistant/candidates.py` queries vectors only for checked
  books whose `book_retrieval_status.vector_status='indexed'` state is current
  for the configured embedding model/dimensions and current source-object
  snapshot.
- Vector candidate rows are scoped through `source_objects.book_id`; embedding
  rows whose `book_id` disagrees with their source object are rejected instead
  of becoming evidence.
- The vector channel feeds RRF and `DeterministicReranker`; exact lexical/object
  channels remain present and vectors cannot bypass final relevance judgment.

Phase 7 PR9 makes structured source-object evidence and scoped link traversal
part of the retrieval architecture:

- Migration `0004_structured_evidence` adds `glossary_entry` object support and
  `glossary_definition` link support for existing databases and fresh schemas.
- Deterministic extraction now recognizes simple pipe tables/table rows,
  stat/profile blocks, index entries, glossary entries, and cross-reference
  lines from imported page text. These are conservative heuristics before
  richer layout/OCR table reconstruction exists.
- `source_object_links` is now populated during source-object replacement for
  parent table/profile relationships and deterministic same-book
  index/glossary/cross-reference targets.
- `book_object_status.extractor_version` invalidates old extracted/indexed
  rows when extraction heuristics change, so normal extraction runs refresh
  structured evidence instead of silently skipping legacy object sets.
- Familiar resolves table-row, stat-block, index, and cross-reference
  candidates to complete parent/target source objects under the current checked
  Library scope. Glossary entries remain canonical evidence and can carry
  linked target context.
- Link traversal cannot cross unchecked books; the checked `source_book_ids`
  snapshot remains authoritative for candidates, prompt context, and citations.

Phase 7 PR10 adds printed page-label calibration/backfill:

- Migration `0005_page_label_calibration` adds
  `book_page_label_calibrations` and widens `ingest_jobs` for
  `backfill_page_labels`.
- `book_retrieval_status.page_label_status` remains the summary lifecycle
  state, while `book_page_label_calibrations` owns method, current page-text
  snapshot, safe failure status, and calibration metadata.
- `tools/backfill_page_labels.py` is the count-oriented local CLI for building
  those calibration rows from existing imported page labels plus optional
  offset anchors.
- Exact search and Familiar citations prefer current calibrated printed labels
  but retain `pdf_page_number` for Grimoire/PDF jumps.
- Manual-review gaps do not produce printed-page labels; the UI can still open
  the PDF page by number while avoiding false printed citations.

The schema already includes the planned tables for pages, page text, FTS
projection, source sets, visual assets, readiness state, and future AI
chat/retrieval/source-object metadata. The current populated runtime
source-of-truth areas are library folders, books, pages, page text, page
search, FTS, ingest jobs, source sets, chat threads, retrieval runs, model
runs, and the `book_readiness` view. Source-set state is now populated in
`source_sets`, `source_set_books`, and `app_settings.active_source_set_id`.
Typed source-object tables can now be populated with deterministic
`rule_section`, `page_chunk`, table, table-row, stat/profile,
index/glossary, and cross-reference rows, with derived `source_object_links`
for parent/target relationships. Object search projections are rebuilt during
extraction or repaired independently with `tools/rebuild_source_object_fts.py`.
Durable source-map/profile metadata can now be rebuilt from those source
objects into `book_source_maps` and `book_query_profiles`, with lifecycle
status in `book_retrieval_status`. Printed-page calibration metadata can now
be rebuilt into `book_page_label_calibrations`, with summary status also in
`book_retrieval_status`.
The local API now surfaces library, source-set, exact-search, page-text,
managed-PDF reader, and streaming chat operations. The frontend now surfaces
library selection, exact search, page-text expansion, PDF reading, and the
first cited streaming Familiar chat loop. Later phases will deepen typed
retrieval, chat history UX, campaign/session memory, visual assets, and
adventure-generation workflows.

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
- `chat_thread_source_books` snapshots enabled books when a chat thread is
  created. Existing threads do not silently change scope when the Library
  toggles change later.
- `model_runs` is the app-owned source of truth for Familiar generation state:
  `queued`, `retrieving`, `calling_model`, `completed`, or `failed`.
- `retrieval_runs` and `retrieval_hits` record the exact pages used for a chat
  answer; citations point back to `books` and `pages`.
- `retrieval_run_source_books` records the exact checked books considered by a
  retrieval run, including the source-set id and book-title snapshot. This is
  the relational audit trail for Library checkbox scope.
- `retrieval_hits` is now forward-compatible with typed retrieval: it has an
  app-owned `id`, optional `source_object_id`, and immutable snapshot columns
  for source-object type, title, heading path, confidence, rank reasons,
  text-snapshot hash, and metadata.
- `source_objects` is the planned canonical table for typed evidence spans.
  `source_object_search` and `source_object_search_fts` are rebuildable
  projections over those rows.
- `book_object_status` owns the future source-object extraction/indexing
  lifecycle per book. Frontend inference and incidental FTS row presence should
  not replace that lifecycle state.
- `book_retrieval_status` owns per-book retrieval-asset lifecycle state for
  source maps, future table indexes, future vectors, and page-label
  calibration.
- `book_page_label_calibrations` owns per-book printed-page calibration
  details, including the calibration method, page-text snapshot, offset-anchor
  metadata, missing/manual-review counts, and safe failure state.
- `book_source_maps` owns compact per-book retrieval routing metadata:
  summaries, aliases, chapters, best-source-for query types, and future
  index/glossary term lists. It is private local metadata derived from
  source-object state.
- `book_query_profiles` stores deterministic per-book query-type boost
  evidence derived from `book_source_maps`; do not hard-code boost assumptions
  in the frontend.
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
