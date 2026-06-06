# Testing Posture And Conventions

## Current State

[coverage: high]

Application tests now exist for the Phase 1 SQLite/config foundation, the Phase
2 managed PDF library importer, the page-text importer, the global exact-search
path, Phase 3 source-set management/search scoping, Phase 4 local FastAPI
backend API, Phase 5 browser GUI, Phase 6 Familiar chat loop, Phase 7 PR1
source-object migration/model foundation, Phase 7 PR2 deterministic
source-object extraction foundation, Phase 7 PR3 Familiar source-map/object
retrieval, Phase 7 PR4 retrieval-module split, and Phase 7 PR5 durable
source-map/profile ownership, Phase 7 PR6 source-object search backfill, and
Phase 7 PR7 retrieval rank fusion/reranker protocol, Phase 7 PR8 local
vector retrieval channel, Phase 7 PR9 structured source-object evidence, and
Phase 7 PR10 printed page-label calibration/backfill, and Phase 7 PR11
Familiar prompt history/history-aware retrieval planning.
Python testing runs through the `wfrp-companion` Conda environment. Frontend
testing runs through npm in `frontend/`.

## Expected Coverage

[coverage: medium]

Prioritize tests around places where silent errors would damage trust:

- PDF extraction preserves book/page metadata.
- Chunking keeps citations attached to source pages.
- Full-text search finds exact rules and names.
- Vector retrieval does not suppress exact matches.
- Prompt construction includes citations and respects context limits.
- Assistant responses handle missing context honestly.
- Citation links open the correct PDF page.

## Test Types

[coverage: medium]

- Unit tests for chunking, ranking, citation assembly, and prompt shaping.
- Integration tests for ingestion through search.
- UI tests for library, reader, search, and chat flows once the frontend exists.
- Regression fixtures using synthetic or public-domain sample PDFs, not WFRP
  book text.

## Commands

[coverage: medium]

Once Python tests exist:

```bash
conda activate wfrp-companion
python -m pytest
```

Run lint checks with:

```bash
conda activate wfrp-companion
ruff check .
```

Current coverage gate:

```bash
conda activate wfrp-companion
python -m pytest --cov=wfrp_companion --cov=tools.init_db --cov=tools.import_pdfs --cov=tools.import_page_text --cov=tools.rebuild_fts --cov=tools.rebuild_source_object_fts --cov=tools.rebuild_source_maps --cov=tools.rebuild_embeddings --cov=tools.backfill_page_labels --cov=tools.search_text --cov=tools.source_sets --cov=tools.serve_api --cov=tools.dev --cov=tools.migrate_db --cov=tools.extract_source_objects --cov-report=term-missing --cov-fail-under=100
```

Current frontend verification commands:

```bash
cd frontend
npm run test
npm run test:coverage
npm run build
npm run test:e2e
```

Frontend coverage thresholds are configured in `frontend/vitest.config.ts`:
90% statements, branches, functions, and lines. Playwright e2e specs live under
`frontend/e2e/` and are excluded from Vitest unit coverage.

Use `python -m pytest` rather than bare `pytest`; it reliably keeps the repo
root on `sys.path` for local package imports in this checkout.

Current focused test files:

- `tests/api/test_app.py`
- `tests/api/test_errors.py`
- `tests/api/test_library_routes.py`
- `tests/api/test_openapi.py`
- `tests/api/test_search_routes.py`
- `tests/api/test_source_set_routes.py`
- `tests/assistant/test_chat_service.py`
- `tests/assistant/test_chat_store.py`
- `tests/assistant/test_conversation_context.py`
- `tests/assistant/test_prompts.py`
- `tests/assistant/test_provider.py`
- `tests/assistant/test_retrieval.py`
- `tests/assistant/test_retrieval_module_contracts.py`
- `tests/db/test_schema.py`
- `tests/db/test_migrations.py`
- `tests/library/test_identity.py`
- `tests/library/test_discovery.py`
- `tests/library/test_storage.py`
- `tests/library/test_catalog.py`
- `tests/library/test_importer.py`
- `tests/library/test_page_text_importer.py`
- `tests/library/test_page_labels.py`
- `tests/library/test_source_sets.py`
- `tests/search/test_fts.py`
- `tests/search/test_scope.py`
- `tests/tools/test_import_pdfs.py`
- `tests/tools/test_import_page_text.py`
- `tests/tools/test_rebuild_fts.py`
- `tests/tools/test_search_text.py`
- `tests/tools/test_serve_api.py`
- `tests/tools/test_dev.py`
- `tests/tools/test_migrate_db.py`
- `tests/tools/test_extract_source_objects.py`
- `tests/tools/test_rebuild_embeddings.py`
- `tests/tools/test_rebuild_source_object_fts.py`
- `tests/tools/test_rebuild_source_maps.py`
- `tests/tools/test_backfill_page_labels.py`
- `tests/tools/test_source_sets_cli.py`
- `tests/source_objects/test_models.py`
- `tests/source_objects/test_extractor.py`
- `tests/source_objects/test_layout.py`
- `tests/source_objects/test_embeddings.py`
- `tests/source_objects/test_object_search_backfill.py`
- `tests/source_objects/test_source_map_builder.py`
- `tests/source_objects/test_store.py`
- `frontend/src/**/*.test.ts`
- `frontend/src/**/*.test.tsx`
- `frontend/e2e/workspace.spec.ts`

They cover configuration defaults/overrides, SQLite initialization, WAL/foreign
key settings, lifecycle constraints, source/asset boolean constraints, asset
page consistency, explicit schema migrations, migration rollback behavior,
missing/uninitialized DB refusal, duplicate legacy retrieval-rank preflights,
source-object constraints and deterministic normalized IDs, the
source-object constraints and deterministic normalized IDs, source-object
extraction lifecycle/status/job behavior, text snapshot hashing, layout
fallback, OCR confidence metadata, heading-derived rule sections, page-chunk
fallback, same-page/same-title object ID stability, the
`tools/extract_source_objects.py` CLI entrypoint, source-object search/FTS
backfill from existing `source_objects`, stale projection/FTS-index repair,
FTS vocabulary and rowid validation, idempotent object-search rebuild skips,
object-type posting validation, stale status repair,
`tools/rebuild_source_object_fts.py` count-only CLI output, source-map rebuild
lifecycle, book retrieval status backfill,
durable source-map freshness/fallback behavior, source-map query-profile
rebuilds, `retrieval_run_source_books` snapshots, the
`tools/rebuild_source_maps.py` CLI entrypoint, local source-object embedding
rebuilds, vector snapshot invalidation, stale embedding job recovery,
checked-book vector candidate filtering, malformed embedding-row scope
protection, `tools/rebuild_embeddings.py` count-only CLI output, the
`tools/init_db.py` CLI
entrypoint, managed PDF identity, recursive discovery, SHA/atomic-copy storage
helpers, idempotent library import, copy-job recovery, collision/failure
reporting, the `tools/import_pdfs.py` CLI entrypoint,
page-text JSON validation, import idempotency, failed/stale import repair,
file-level quarantine jobs, global FTS rebuild idempotency, stale FTS
projection cleanup, FTS integrity checks, readiness-gated exact search,
source-set membership sync/idempotency/conflict handling, active source-set
selection, per-book source-set toggles, active source-set search defaults,
whole-library override behavior, per-book search filters, shared search scope
resolution, API startup/health, OpenAPI route presence, API error mapping,
book/page/page-text/PDF reader routes, PDF range/path-safety responses,
source-set routes, exact-search routes, chat routes, and the page-text,
source-set, search, API, dev, migration, and source-object extraction CLI
entrypoints.

Retrieval-specific tests now also cover RRF deterministic ordering,
same-channel dedupe before fusion-rank assignment, weak lexical-only
rejection, exact table/object-type query preservation, deterministic reranker
protocol exports, and persisted rank reasons that include channel
contribution, fusion score, and reranker judgment. Vector-channel tests cover
disabled-by-default behavior, checked-book filtering, current-snapshot gating,
and exact lexical/object hits staying ahead of vector-only candidates.
Structured-evidence tests cover `glossary_entry` and `glossary_definition`
schema/migration support, table/table-row extraction and parent links,
stat/profile extraction and links, index/glossary/cross-reference extraction,
extractor-version invalidation, duplicate same-page table-row ID prevention,
WFRP-style pipe/percent stat profiles, range-chart table extraction with OCR
title normalization, derived source-object links and count updates, table-row
citations resolving to parent table page ranges, stat-block retrieval resolving
to complete profiles, structural query terms refusing unsafe fuzzy expansion,
typed chart/table evidence outranking prose mentions, heading/running-header
only entity matches being rejected, index routing to deterministic target
sections or page-only target pages, glossary evidence retaining definition
context without fake disjoint page ranges, link traversal refusing unchecked-book
targets, duplicate equivalent rule-section ID avoidance, and safe historical
retrieval-hit detachment when source objects are replaced. Page-label tests
cover offset-anchor calibration,
roman/front-matter preservation, snapshot drift anchor reuse, manual-review
conflict suppression, exact/search source-object/linked-page citation labels,
safe count-only CLI failure output, and reloaded chat citation labels/ranges.
Conversation-context tests cover
bounded prior completed-turn selection, failed/active/current-message
exclusion, retry anchoring before the original user message, prompt-history
budgeting, self-contained retrieval queries staying unchanged, follow-up
retrieval-query contextualization and caps, compact salient history terms,
assistant failure-answer filtering for retrieval planning, disabled history
limits, provider `store=False`, prompt history/evidence separation, retrieval
metadata for planned queries, stream-interruption cleanup, and logical retry
collapse in chat API/frontend read models.

Frontend tests cover the API client, initial workspace loading, validated
workspace storage, pointer and keyboard panel resize/collapse/maximize
behavior, Library/Search tabs, grouped book sections, per-book source-set
toggles, section-level Library bulk toggles, absence of noisy per-book
readiness labels, search result full text expansion/error handling, Grimoire
tab, page, zoom, and view-mode behavior, two-page spread math, guarded PDF.js
rendering/retry and cancellation behavior, Familiar shell behavior, safe
Familiar markdown rendering, explicit PDF-page citation/search opens, and
browser e2e flows for Library/Search/Grimoire/Familiar plus panel overflow.

The latest full backend verification command on 2026-06-06 reported 469 tests
passing with 100% coverage across `wfrp_companion` and the tracked tool
entrypoints. The latest frontend verification reported 131 Vitest tests
passing with coverage above the configured 90% thresholds, a successful
production build, and two Playwright browser e2e tests passing.

## Manual QA

[coverage: medium]

For the MVP, manual QA should include:

- Import a PDF.
- Open it in the reader.
- Search for an exact term.
- Ask a rules question.
- Confirm the answer cites the right book/page.
- Click the citation and verify the reader lands on that page.

Phase 5 browser QA also included a live local API check: load the real library,
search for `critical hit`, verify grouped results, open a result into a
Grimoire tab at page 134, confirm source tabs omit page-number suffixes, confirm
two-page view can be toggled, and confirm the Familiar composer remains
reachable without page-level scrolling.

The 2026-06-05 page-drift regression pass added a live local check that search
results display explicit `PDF page` labels and that opening a search hit lands
Grimoire on the same PDF page in single-page mode. Automated coverage also
checks `pdf_page_number`/`page_label` API fields, search and Familiar citation
open behavior, page-label import freshness, and markdown table rendering in
Familiar output.

## Sources

- `wiki/topics/implementation-standards.md`
- `wiki/topics/local-tooling-and-packaging.md`
- `wiki/topics/pdf-library-and-ingestion.md`
- `wiki/topics/ai-rag-system.md`
