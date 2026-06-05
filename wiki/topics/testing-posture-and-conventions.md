# Testing Posture And Conventions

## Current State

[coverage: high]

Application tests now exist for the Phase 1 SQLite/config foundation, the Phase
2 managed PDF library importer, the page-text importer, the global exact-search
path, Phase 3 source-set management/search scoping, Phase 4 local FastAPI
backend API, Phase 5 browser GUI, Phase 6 Familiar chat loop, Phase 7 PR1
source-object migration/model foundation, and Phase 7 PR2 deterministic
source-object extraction foundation. Python testing runs through the
`wfrp-companion` Conda environment. Frontend testing runs through npm in
`frontend/`.

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
python -m pytest --cov=wfrp_companion --cov=tools.init_db --cov=tools.import_pdfs --cov=tools.import_page_text --cov=tools.rebuild_fts --cov=tools.search_text --cov=tools.source_sets --cov=tools.serve_api --cov=tools.dev --cov=tools.migrate_db --cov=tools.extract_source_objects --cov-report=term-missing --cov-fail-under=100
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
- `tests/db/test_schema.py`
- `tests/db/test_migrations.py`
- `tests/library/test_identity.py`
- `tests/library/test_discovery.py`
- `tests/library/test_storage.py`
- `tests/library/test_catalog.py`
- `tests/library/test_importer.py`
- `tests/library/test_page_text_importer.py`
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
- `tests/tools/test_source_sets_cli.py`
- `tests/source_objects/test_models.py`
- `tests/source_objects/test_extractor.py`
- `tests/source_objects/test_layout.py`
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
`tools/extract_source_objects.py` CLI entrypoint, the `tools/init_db.py` CLI
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

Frontend tests cover the API client, initial workspace loading, validated
workspace storage, pointer and keyboard panel resize/collapse/maximize
behavior, Library/Search tabs, grouped book sections, per-book source-set
toggles, search result full text expansion/error handling, Grimoire tab, page,
zoom, and view-mode behavior, two-page spread math, guarded PDF.js
rendering/retry and cancellation behavior, Familiar shell behavior, and browser
e2e flows for Library/Search/Grimoire/Familiar plus panel overflow.

The latest full backend verification command on 2026-06-05 reported 283 tests
passing with 100% coverage across `wfrp_companion` and the tracked tool
entrypoints. The latest frontend verification reported 122 Vitest tests
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

## Sources

- `wiki/topics/implementation-standards.md`
- `wiki/topics/local-tooling-and-packaging.md`
- `wiki/topics/pdf-library-and-ingestion.md`
- `wiki/topics/ai-rag-system.md`
