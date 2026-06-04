# Testing Posture And Conventions

## Current State

[coverage: high]

Application tests now exist for the Phase 1 SQLite/config foundation, the Phase
2 managed PDF library importer, the page-text importer, the global exact-search
path, Phase 3 source-set management/search scoping, and the Phase 4 local
FastAPI backend API. Python testing runs through the `wfrp-companion` Conda
environment. `pytest`, `pytest-cov`, and `ruff` are included in
`environment.yml`.

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
python -m pytest --cov=wfrp_companion --cov=tools.init_db --cov=tools.import_pdfs --cov=tools.import_page_text --cov=tools.rebuild_fts --cov=tools.search_text --cov=tools.source_sets --cov=tools.serve_api --cov-report=term-missing --cov-fail-under=100
```

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
- `tests/tools/test_source_sets_cli.py`

They cover configuration defaults/overrides, SQLite initialization, WAL/foreign
key settings, lifecycle constraints, source/asset boolean constraints, asset
page consistency, the `tools/init_db.py` CLI entrypoint, managed PDF identity,
recursive discovery, SHA/atomic-copy storage helpers, idempotent library import,
copy-job recovery, collision/failure reporting, the `tools/import_pdfs.py` CLI
entrypoint, page-text JSON validation, import idempotency, failed/stale import
repair, file-level quarantine jobs, global FTS rebuild idempotency, stale FTS
projection cleanup, FTS integrity checks, readiness-gated exact search,
source-set membership sync/idempotency/conflict handling, active source-set
selection, per-book source-set toggles, active source-set search defaults,
whole-library override behavior, per-book search filters, shared search scope
resolution, API startup/health, OpenAPI route presence, API error mapping,
book/page/PDF reader routes, PDF range/path-safety responses, source-set
routes, exact-search routes, and the page-text, source-set, search, and API CLI
entrypoints.

The latest full verification command on 2026-06-04 reported 178 tests passing
with 100% coverage across `wfrp_companion` and the tracked tool entrypoints.

## Manual QA

[coverage: medium]

For the MVP, manual QA should include:

- Import a PDF.
- Open it in the reader.
- Search for an exact term.
- Ask a rules question.
- Confirm the answer cites the right book/page.
- Click the citation and verify the reader lands on that page.

## Sources

- `wiki/topics/implementation-standards.md`
- `wiki/topics/local-tooling-and-packaging.md`
- `wiki/topics/pdf-library-and-ingestion.md`
- `wiki/topics/ai-rag-system.md`
