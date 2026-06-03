# Testing Posture And Conventions

## Current State

[coverage: high]

Application tests now exist for the Phase 1 SQLite/config foundation. Python
testing runs through the `wfrp-companion` Conda environment. `pytest`,
`pytest-cov`, and `ruff` are included in `environment.yml`.

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

Phase 1 coverage gate:

```bash
conda activate wfrp-companion
python -m pytest --cov=wfrp_companion --cov=tools.init_db --cov-report=term-missing --cov-fail-under=100
```

Use `python -m pytest` rather than bare `pytest`; it reliably keeps the repo
root on `sys.path` for local package imports in this checkout.

Current focused test file:

- `tests/db/test_schema.py`

It covers configuration defaults/overrides, SQLite initialization, WAL/foreign
key settings, lifecycle constraints, source/asset boolean constraints, asset
page consistency, and the `tools/init_db.py` CLI entrypoint.

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
