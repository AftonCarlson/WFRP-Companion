# Wiki Compile Log

## 2026-06-05 Local Vector Retrieval Channel

- Added migration `0003_vector_retrieval` and the
  `source_object_embeddings` table for SQLite-local source-object vectors.
- Added disabled-by-default embedding configuration:
  `WFRP_EMBEDDING_PROVIDER`, `WFRP_EMBEDDING_MODEL`, and
  `WFRP_EMBEDDING_DIMENSIONS`. The only implemented provider is local
  deterministic `local-hash`; no hosted vector service is called.
- Added `wfrp_companion/source_objects/embeddings.py` and
  `tools/rebuild_embeddings.py` to rebuild local vector blobs from current
  `source_objects` with `ingest_jobs(job_type='rebuild_embeddings')`,
  `book_retrieval_status.vector_status`, snapshot invalidation, stale-running
  recovery, and count-only CLI output.
- Added vector candidate generation in `wfrp_companion/assistant/candidates.py`
  as one more candidate channel before RRF and deterministic reranking. Vector
  candidates are filtered to the checked `book_id` snapshot and only used for
  books whose embedding snapshot is current.
- Independent review found three issues: malformed embedding rows could cross
  scope if `source_object_embeddings.book_id` disagreed with
  `source_objects.book_id`, existing `0002` databases needed pending
  migrations before the new job type was used, and vector query-time currentness
  needed to prove the embedding snapshot. All were fixed with regressions;
  follow-up review reported no findings, and CodeRabbit reported 0 issues.
- Verification run for this pass: focused changed-module coverage reported 73
  tests passing with 100.00% coverage; full Python tests reported 372 tests
  passing with one existing Starlette/httpx deprecation warning and 100.00%
  coverage; `ruff check .` passed; `git diff --check` passed; frontend Vitest
  reported 127 tests passing; frontend coverage passed above configured
  thresholds; frontend production build passed with the existing large PDF
  worker chunk warning; Playwright e2e reported 2 tests passing.

## 2026-06-05 Retrieval Rank Fusion And Reranker Protocol

- Added reciprocal rank fusion to Familiar retrieval candidates before final
  reranking. Page FTS, source-object FTS, and fallback object scans remain
  candidate channels; they do not decide final prompt evidence on their own.
- Added the `Reranker` protocol and `DeterministicReranker` default in
  `wfrp_companion/assistant/reranking.py`, keeping provider-backed reranking
  out of the current phase while making the interface replaceable.
- Rank reasons for selected hits now include channel-rank contributions
  (`fusion_channel:*`), total RRF contribution (`fusion:rrf=*`), deterministic
  reranker acceptance, and deterministic reranker score. These are persisted in
  `retrieval_hits.rank_reasons_json`.
- The deterministic reranker now rejects weak lexical-only matches for
  multi-term queries while preserving exact object/table lookup signals,
  including cases where the only table/stat/profile cue is the source-object
  `object_type`.
- Independent review initially found two ranking issues: object-type table
  candidates could be rejected by the semantic gate, and same-channel duplicate
  candidates could inflate RRF rank positions. Both were fixed with regression
  tests; follow-up review reported no findings.
- Verification run for this pass: focused retrieval coverage reported 27 tests
  passing with 100.00% coverage; full Python tests reported 350 tests passing
  with one existing Starlette/httpx deprecation warning and 100.00% coverage;
  `ruff check .` passed; `git diff --check` passed; frontend Vitest reported
  127 tests passing; frontend coverage passed above configured thresholds;
  frontend production build passed with the existing large PDF worker chunk
  warning; Playwright e2e reported 2 tests passing.

## 2026-06-05 Source-Object Search Backfill

- Added `rebuild_source_object_search()` in
  `wfrp_companion/source_objects/store.py` to rebuild
  `source_object_search` and `source_object_search_fts` from existing
  `source_objects` without rerunning extraction.
- Added `tools/rebuild_source_object_fts.py` as a count-only local repair tool
  for missing or stale source-object search projections.
- The backfill uses `ingest_jobs(job_type='rebuild_source_object_fts')`,
  stale-running recovery, claim-conflict failure reporting, and
  `book_object_status` transitions to keep object-search readiness explicit.
- Review fixes strengthened idempotent skip behavior so stale FTS indexes and
  failed/stale `book_object_status` rows are repaired instead of reported as
  current.
- Verification run for this pass: focused store/tool coverage reported 27 tests
  passing with 100.00% coverage; post-review focused coverage reported 29
  tests passing with 100.00% coverage; final focused coverage reported 31 tests
  passing with 100.00% coverage after FTS vocabulary/rowid validation was
  added; object-type posting validation brought final focused coverage to 32
  tests passing with 100.00% coverage; full Python tests reported 345 tests
  passing with one existing
  Starlette/httpx deprecation warning and 100.00% coverage;
  `ruff check .` passed; frontend Vitest reported 127 tests passing; frontend
  coverage passed above configured thresholds; frontend production build passed
  with the existing large PDF worker chunk warning; Playwright e2e reported 2
  tests passing.

## 2026-06-05 Durable Source-Map Retrieval Ownership

- Added migration `0002_source_map_retrieval` for
  `book_retrieval_status`, `book_source_maps`, and
  `retrieval_run_source_books`.
- Added `wfrp_companion/source_objects/source_map_builder.py` and
  `tools/rebuild_source_maps.py` so source-map/profile metadata is rebuilt from
  current source objects with guarded jobs, stale-running recovery, count-only
  output, and deterministic freshness snapshots.
- Updated Familiar source-map loading so checked books use current durable
  `book_source_maps` when available and safely fall back to dynamic checked-book
  source maps when durable rows are missing, stale, or malformed.
- Updated retrieval-run persistence to snapshot checked books into
  `retrieval_run_source_books` as relational proof of Library checkbox scope.
- Addressed independent review findings around claim-conflict failure
  accounting, source-map freshness inputs, durable source-map loading, and
  malformed durable-map fallback.
- Verification run for this pass: focused changed-module coverage reported 61
  tests passing with 100.00% coverage; full Python tests reported 325 tests
  passing with one existing Starlette/httpx deprecation warning and 100.00%
  coverage; `ruff check .` passed; frontend Vitest reported 127 tests passing;
  frontend coverage passed above configured thresholds; frontend production
  build passed with the existing large PDF worker chunk warning; Playwright e2e
  reported 2 tests passing.

## 2026-06-05 Retrieval Module Split

- Split the Familiar retrieval implementation into focused modules while
  keeping `wfrp_companion/assistant/retrieval.py` as the public compatibility
  facade for `retrieve_context()` and existing tests/callers.
- Added `source_map.py`, `query_planner.py`, `candidates.py`, `evidence.py`,
  and `reranking.py` under `wfrp_companion/assistant/` so later retrieval
  phases can add durable source maps, rank fusion, vector candidates, and typed
  evidence without growing one monolithic module.
- Added `tests/assistant/test_retrieval_module_contracts.py` to lock facade
  re-exports to the focused module contracts.
- Completed independent code review for the split with no blocking findings.
- Verification run for this pass: focused retrieval/chat tests reported 39
  tests passing; full Python tests reported 300 tests passing with one
  existing Starlette/httpx deprecation warning; the backend coverage gate
  reported 300 tests passing with 100.00% coverage; `ruff check .` passed;
  frontend Vitest reported 127 tests passing; frontend coverage passed above
  configured thresholds; frontend production build passed with the existing
  large PDF worker chunk warning; Playwright e2e reported 2 tests passing.

## 2026-06-05 Source-Map-Aware Familiar Retrieval Slice

- Changed Familiar retrieval so new model runs resolve checked books from the
  thread's active source set at message time. `chat_thread_source_books` remains
  a historical thread-creation snapshot; `retrieval_runs.metadata_json` now
  stores the per-run checked-book snapshot, compact source map, and candidate
  list.
- Added source-object search projection population during extraction:
  `source_object_search`, `source_object_search_fts`, and
  `book_object_status.status='indexed'` now represent searchable extracted
  objects.
- Added broad page/object candidate generation, source-object span resolution,
  deterministic semantic reranking, rank-reason snapshots, source-map prompt
  injection, and printed page-range citation labels for Familiar.
- Verification for this pass: full Python tests reported 290 tests passing;
  the backend coverage gate reported 298 tests passing with 100.00% coverage;
  both Python runs had one existing Starlette/httpx deprecation warning;
  `ruff check .` passed; frontend Vitest reported 127 tests passing; frontend
  coverage passed above configured thresholds; frontend production build
  passed with the existing large PDF worker chunk warning; Playwright e2e
  reported 2 tests passing.

## 2026-06-05 Retrieval Architecture Handoff

- Added
  `docs/handoffs/2026-06-05-source-map-hybrid-retrieval-handoff.md` as the
  durable handoff for the next retrieval phase.
- Captured the target direction as source-map-aware hybrid retrieval with
  semantic reranking and section-aware evidence, combining exact FTS, future
  vector search, source-object search, glossary/index routing, query rewriting,
  rank fusion, and semantic relevance filtering.
- Preserved the key user-observed requirements: Library checkboxes must gate
  Familiar prompt/retrieval scope per message, lexical hits must be semantically
  judged before entering context, topics must resolve to multi-page
  source-object spans when needed, and UI citations/search results should show
  printed page labels rather than raw PDF page numbers.

## 2026-06-05 Library Bulk Toggle Refinement

- Removed per-book readiness words from the Library book selector so rows show
  the book title, source-set checkbox, and compact Grimoire open action without
  repeated `ready` noise.
- Added tri-state category-heading checkboxes to select or clear every visible
  book in a Library category. The bulk control persists changes through the
  same per-book source-set endpoint as individual checkboxes.
- Verification run for this pass: focused Library tests reported 9 tests
  passing, frontend coverage reported 127 Vitest tests passing above configured
  thresholds, frontend production build passed, and Playwright e2e reported 2
  tests passing.

## 2026-06-05 Search/Citation Page Drift And Familiar Rendering Fix

- Split search hits and chat citations into explicit PDF jump metadata:
  `pdf_page_number` plus optional `page_label`, while preserving the existing
  `page_number` compatibility field.
- Changed `/api/search/exact`, Familiar retrieval, stored chat citation read
  models, and frontend API types so Search and Familiar open Grimoire using the
  PDF page number instead of inferring from display text.
- Search result opens and Familiar citation opens now force Grimoire back to
  single-page mode so an existing two-page spread cannot make the reader appear
  one page behind the clicked citation.
- Updated search result labels and citation buttons to say `PDF page N`, with
  `(printed page X)` appended when a distinct `pages.page_label` is available.
- Added safe Familiar markdown rendering for headings, paragraphs, lists,
  tables, bold text, and inline code so streamed model output no longer appears
  as one unreadable text blob.
- Updated `tools/extract_page_text.py` and
  `wfrp_companion/library/page_text_importer.py` so page labels from JSON or
  managed PDFs are preserved in SQLite `pages.page_label`; label-only drift now
  causes page-text import freshness checks to fail rather than silently
  skipping stale rows.
- Verification run for this pass: backend coverage reported 286 tests passing
  with 100% coverage, `ruff check .` passed, frontend Vitest reported 125 tests
  passing with coverage above configured thresholds, frontend production build
  passed, Playwright e2e reported 2 tests passing, `git diff --check` passed,
  and a live browser smoke check opened an exact-search result into Grimoire at
  PDF page 134 in single-page mode.

## 2026-06-05 Phase 7 Deterministic Source Object Extraction Foundation

- Added `wfrp_companion/source_objects/layout.py`,
  `wfrp_companion/source_objects/store.py`,
  `wfrp_companion/source_objects/extractor.py`, and
  `tools/extract_source_objects.py`.
- Implemented deterministic source-object extraction over copied,
  text-imported, exact-search-indexed books.
- Added per-book text snapshot hashing, explicit `book_object_status`
  lifecycle updates, idempotent `extract_source_objects` ingest jobs,
  stale-running recovery, and failure recording.
- Added PyMuPDF layout metadata loading with safe fallback when managed PDFs
  are missing or unreadable.
- Added heading-derived `rule_section` extraction and lower-confidence
  `page_chunk` fallback extraction for pages/regions not covered by rule
  sections.
- Kept object IDs stable by using page-local title-bucket ordinals plus
  normalized text hashes, including a regression for unrelated earlier
  same-page heading insertion.
- Ran a live private smoke check for one indexed book: 738 source objects were
  written on the first run and the same book was skipped as current on rerun.
  No private extracted text was committed or logged in wiki output.
- Completed independent review, fixed the reported same-page ID churn issue,
  and reran verification.
- Verification run for this pass: focused source-object/tool tests reported 30
  tests passing, backend coverage reported 283 tests passing with 100%
  coverage, `ruff check .` passed, frontend Vitest reported 122 tests passing
  with coverage above configured thresholds, frontend production build passed,
  and Playwright e2e reported 2 tests passing.
- Important boundary: object FTS, table/stat/location extraction, and Familiar
  object-aware ranking remain later Phase 7 PRs.

## 2026-06-05 Phase 7 Typed Source Object Schema Foundation

- Added the Phase 7 implementation plan at
  `docs/plans/2026-06-05-phase-7-typed-source-object-retrieval-implementation-plan.md`.
- Added `schema_migrations` plus `wfrp_companion/db/migrations.py` and
  `tools/migrate_db.py` for explicit local SQLite migrations.
- Added the Phase 7 source-object schema foundation:
  `source_objects`, `source_object_links`, `book_object_status`,
  `book_query_profiles`, `source_object_search`, and
  `source_object_search_fts`.
- Updated `retrieval_hits` so future retrieval can cite typed source objects
  while preserving legacy page-level hits as `page_fallback` snapshots.
- Added `wfrp_companion/source_objects/models.py` with typed source-object
  contracts and deterministic IDs that hash normalized text rather than raw OCR
  whitespace.
- Hardened migration safety after independent review: missing/uninitialized DB
  paths are refused, duplicate legacy retrieval ranks are preflighted, DDL runs
  inside a rollbackable transaction, and `schema_migrations` is recorded only
  after all migration work succeeds.
- Added migration, rollback, CLI, schema, source-object, chat, retrieval, and
  frontend regression coverage.
- Verification run for this pass: backend coverage gate reported 253 tests
  passing with 100% coverage, `ruff check .` passed, frontend Vitest reported
  122 tests passing with coverage above configured thresholds, frontend
  production build passed, and Playwright e2e reported 2 tests passing.
- Important boundary: Phase 7 PR1 is schema/model/migration foundation only.
  It does not yet extract source objects or change Familiar retrieval ranking.

## 2026-06-05 Phase 6 Familiar Streaming RAG Chat

- Added the Phase 6 implementation plan at
  `docs/plans/2026-06-05-phase-6-familiar-rag-chat-implementation-plan.md`.
- Added `tools/dev.py` as a one-command local runner for FastAPI plus Vite,
  with readiness probes and cleanup behavior covered by tests.
- Added `chat_thread_source_books` and `model_runs` to the SQLite schema so
  chat retrieval scope and model lifecycle state are app-owned and explicit.
- Added `wfrp_companion/assistant/chat_store.py`,
  `retrieval.py`, `prompts.py`, `provider.py`, and `chat_service.py` for
  thread snapshots, exact-search retrieval, bounded prompt construction,
  OpenAI Responses API streaming, and model-run completion/failure handling.
- Added `/api/chat/*` routes, including
  `POST /api/chat/threads/{thread_id}/messages/stream`, which returns
  newline-delimited JSON events: `accepted`, `retrieval`, `delta`,
  `completed`, and `failed`.
- Updated the Familiar frontend panel to create a thread, stream assistant
  deltas, show failed provider runs, and open cited PDF pages in Grimoire.
- Added `openai` to `environment.yml`; the API key remains local in
  `OPENAI_API_KEY` and is never exposed to the browser or stored in the repo.
- Verification run for this pass: backend pytest reported 205 tests passing,
  frontend Vitest reported 109 tests passing, `ruff check .` passed,
  frontend production build passed, and targeted coverage gates reported 100%
  for `wfrp_companion.assistant.chat_service` and
  `wfrp_companion.assistant.provider`.
- Follow-up reconciliation on 2026-06-05 marked the Phase 6 plan checklist
  against live code. The remaining known Phase 6 gaps are the real Familiar
  chat-history selector UI and a successful live OpenAI rules-question QA pass;
  the attempted live rules question exposed the page-level retrieval weakness
  now being addressed by Phase 7 typed source-object retrieval.

## 2026-06-04 Phase 5 Browser GUI Refinement

- Refined the first browser GUI around the user-approved workspace language:
  `Library`, `Grimoire`, and `Familiar`.
- Moved Grimoire page/zoom/view controls into the panel header, centered them
  in the header, and kept previous/next page movement as minimal side controls
  beside the PDF viewport.
- Added single-page/two-page Grimoire view mode. Two-page mode shows pages 1
  and 2 alone, then pairs pages from 3/4 onward, with an unpaired final page
  shown alone.
- Changed Grimoire source tabs to show source titles only, placed close controls
  visually inside the tabs, and kept close controls outside the semantic
  `tablist` while sharing the tab strip scroll layer.
- Changed Library/Search open actions to compact book-icon buttons.
- Moved the Familiar history hamburger into the panel header, removed the
  duplicate internal chat header, and positioned the send action inside the
  lower-right corner of the message text field.
- Added tests for the refined panel labels, header controls, PDF tab labels,
  two-page spread math, clamped PDF page behavior, compact open actions, and
  Familiar composer layout.
- Completed independent review, fixed the reported tab-scroll and out-of-range
  PDF page consistency issues, then reran the frontend gate: 106 Vitest tests
  passed with 100% statements / branches / functions / lines coverage,
  production build passed, Playwright e2e passed, and `git diff --check` was
  clean.

## 2026-06-04 Phase 5 Browser GUI Shell

- Added the Phase 5 implementation plan at
  `docs/plans/2026-06-04-phase-5-browser-gui-shell-implementation-plan.md`.
- Added the first committed browser GUI under `frontend/` using React, Vite,
  TypeScript, Vitest, Playwright, PDF.js, and lucide icons.
- Added `GET /api/books/{book_id}/pages/{page_number}/text` so the GUI can
  lazily load full imported page text from SQLite without reading ignored JSON
  files or exposing local filesystem paths. The endpoint is guarded by
  `book_readiness.search_ready`.
- Added a dockable three-panel workspace with collapsible/resizable/maximizable
  Library/Search, PDF Reader, and Agent Chat panels.
- Added Library/Search tabs with grouped source-set book checkboxes, collapsible
  categories, exact-search results, full-page text expansion, and `Open PDF page`
  actions.
- Added multi-source PDF reader tabs over the existing managed PDF endpoint,
  with page navigation, zoom controls, PDF.js canvas rendering, retry handling,
  stale-render cancellation, and accessible tab/panel wiring.
- Added keyboard-resizable panel splitters with vertical separator ARIA
  metadata.
- Added a UI-only agent chat shell with scrollable transcript, controlled
  composer, and chat-history popover. Real AI/RAG behavior remains deferred to a
  later phase.
- Copied the current UI banner into the frontend public asset pipeline at
  `frontend/public/assets/buttlordxai-hero.png`.
- Added frontend unit, coverage, build, and Playwright e2e verification.
  Backend verification reported 181 tests passing with 100% coverage; frontend
  verification reported 74 Vitest tests passing, 100% statement/line/function
  coverage, a successful production build, and one browser e2e test passing.
- Completed independent implementation review, fixed the reported important
  workspace-storage/PDF/chat issues, then fixed the remaining ARIA tab/popover
  follow-ups before this wiki refresh.

## 2026-06-04 Phase 4 Local Backend API

- Added the Phase 4 implementation plan at
  `docs/plans/2026-06-04-phase-4-local-backend-api-implementation-plan.md`.
- Added the FastAPI app factory under `wfrp_companion/api/`, plus
  `tools/serve_api.py` for starting the local API with Conda-managed Python.
- Added `wfrp_companion/library/catalog.py` as the read model for book lists,
  book detail, page references, and guarded managed-PDF reader paths.
- Added `/api/books`, `/api/books/{book_id}`,
  `/api/books/{book_id}/pages/{page_number}`, and
  `/api/books/{book_id}/pdf`. The PDF endpoint serves managed local PDFs
  inline with HTTP range support and rejects unavailable, missing, or unsafe
  managed paths.
- Added `/api/source-sets`, `/api/source-sets/active`, and per-book
  source-set toggle routes over the existing SQLite-backed source-set service.
- Added `wfrp_companion/search/scope.py` so the CLI and API share active
  source-set, named source-set, per-book, and whole-library scope resolution.
- Added `/api/search/exact`, which returns query metadata, resolved scope,
  snippets, and book/page citations while preserving search-readiness gating.
- Added regression coverage for API startup, health, OpenAPI route presence,
  catalog routes, PDF range/path-safety responses, source-set routes,
  exact-search routes, shared scope resolution, API error mapping, and the
  `tools/serve_api.py` entrypoint.
- Ran the full coverage gate across `wfrp_companion` and tracked tool modules:
  178 tests passed with 100% coverage. `ruff check .` also passed.

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
