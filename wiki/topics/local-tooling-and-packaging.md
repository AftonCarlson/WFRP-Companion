# Local Tooling And Packaging

## Current State

[coverage: high]

Python tooling is standardized on Conda. The canonical environment is
`environment.yml` with the environment name `wfrp-companion`.

Conda is used for PDF ingestion, backend/search prototypes, local API
dependencies, image tooling, and tests. Do not install Python project
dependencies globally or through an untracked virtualenv.

The first application package now exists under `wfrp_companion/`. Phase 1 added
configuration loading, SQLite connection/schema initialization, and
`tools/init_db.py`.

Phase 2 added the local managed-PDF library importer, page-text importer, and
global exact-search tools:

- `wfrp_companion/library/identity.py` for stable book and folder IDs.
- `wfrp_companion/library/discovery.py` for recursive PDF discovery.
- `wfrp_companion/library/storage.py` for SHA-256 hashing and atomic managed
  PDF copies.
- `wfrp_companion/library/importer.py` for SQLite-backed folder, book, and copy
  job state.
- `wfrp_companion/library/page_text_importer.py` for importing private
  page-level OCR/text JSON into SQLite.
- `wfrp_companion/search/fts.py` for rebuilding and querying the global SQLite
  FTS5 exact-search index.
- `tools/import_pdfs.py` for importing all configured source PDFs into managed
  local storage.
- `tools/import_page_text.py` for importing all configured page-text JSON into
  `pages` and `page_text`.
- `tools/rebuild_fts.py` for rebuilding `page_search` and `page_search_fts`.
- `tools/search_text.py` for local exact-search smoke checks.

## Expected Development Shape

[coverage: medium]

Once implementation begins, prefer a simple layout:

- `assets/ui/` for repo-owned UI source assets before a frontend asset pipeline
  exists.
- `apps/web/` or `frontend/` for the web GUI.
- `apps/api/` or `backend/` for ingestion, search, and AI endpoints.
- `data/` ignored by Git for local PDFs, indexes, and generated state.
- `docs/plans/` for multi-step implementation plans.
- `docs/adr/` for durable architecture decisions.
- `docs/audits/` for committed audit summaries that avoid private extracted
  text.

Use one package/workspace system only after the stack is chosen. For Python,
Conda is already chosen; add Python dependencies to `environment.yml`.

## Conda Workflow

[coverage: high]

Create the environment once:

```bash
conda env create -f environment.yml
```

Activate it before running Python project commands:

```bash
conda activate wfrp-companion
```

Update it after dependency changes:

```bash
conda env update -f environment.yml --prune
```

Initial Python tooling includes:

- Python 3.12
- PyMuPDF for PDF inspection and extraction
- Poppler for `pdfinfo` / `pdftotext` cross-checks
- Tesseract for OCR
- FastAPI and Uvicorn for the upcoming local API
- Pillow, OpenCV, and ImageHash for upcoming visual asset detection
- pytest for tests
- pytest-cov for coverage gates
- ruff for lint/format checks

Initialize the local SQLite database with:

```bash
conda activate wfrp-companion
python tools/init_db.py
```

The default database path is `data/wfrp_companion.sqlite`, unless
`WFRP_DB_PATH` is set.

Import all owned PDFs from the configured source root with:

```bash
conda activate wfrp-companion
python tools/import_pdfs.py
```

The default PDF root is `/Users/aftoncarlson/TTRPGs/WFRP 2e`, unless
`WFRP_PDF_ROOT` is set. The importer also accepts explicit overrides:

```bash
python tools/import_pdfs.py --pdf-root "/Users/aftoncarlson/TTRPGs/WFRP 2e"
python tools/import_pdfs.py --data-dir "/path/to/private-data"
python tools/import_pdfs.py --db-path "/path/to/wfrp.sqlite"
python tools/import_pdfs.py --retry-running
```

`--data-dir` without `--db-path` stores the database at
`<data-dir>/wfrp_companion.sqlite`. The importer validates the PDF root before
initializing SQLite, so a typo in `--pdf-root` does not create a misleading
database.

Import private page-level OCR/text JSON into SQLite with:

```bash
conda activate wfrp-companion
python tools/import_page_text.py
```

The default input directory is `data/page_text`, unless `--input-dir` is set.
The importer also accepts the common local storage overrides and recovery flags:

```bash
python tools/import_page_text.py --input-dir "/path/to/page_text"
python tools/import_page_text.py --data-dir "/path/to/private-data"
python tools/import_page_text.py --db-path "/path/to/wfrp.sqlite"
python tools/import_page_text.py --force
python tools/import_page_text.py --retry-running
python tools/import_page_text.py --stale-running-minutes 30
```

Rebuild the global exact-search index after page text changes:

```bash
conda activate wfrp-companion
python tools/rebuild_fts.py
```

The FTS rebuild accepts:

```bash
python tools/rebuild_fts.py --data-dir "/path/to/private-data"
python tools/rebuild_fts.py --db-path "/path/to/wfrp.sqlite"
python tools/rebuild_fts.py --force
python tools/rebuild_fts.py --retry-running
python tools/rebuild_fts.py --stale-running-minutes 30
```

Run a local exact-search smoke check with:

```bash
conda activate wfrp-companion
python tools/search_text.py "critical hit"
python tools/search_text.py "critical hit" --book-id core-rules --limit 5
```

`tools/search_text.py` clamps `--limit` to 100 and supports multiple
`--book-id` filters. Search only returns hits from books that are copied,
text-imported, and indexed.

## Environment

[coverage: medium]

Expected secrets/config:

- OpenAI API key.
- Local data directory.
- Optional OCR binary/config.
- Optional model overrides.

Current local config variables:

- `WFRP_PDF_ROOT`
- `WFRP_DATA_DIR`
- `WFRP_DB_PATH`
- `WFRP_ASSET_DIR`

Do not commit real API keys, PDFs, extracted copyrighted text, or local vector
indexes. SQLite databases, managed PDFs, generated assets, and coverage output
are ignored by Git. UI art assets intended for the app may be committed under
`assets/ui/`.

Managed PDFs live under ignored `data/library/pdfs/<book_id>/` with versioned
filenames like `source-<original_sha256>.pdf`. SQLite stores the active managed
PDF path as an absolute path in `books.managed_pdf_path`.

Local page-level OCR/text extraction outputs live under `data/page_text/` and
are ignored by Git. After import, SQLite `pages` and `page_text` are the
runtime source of truth; the JSON files remain private compatibility input.

## Documentation Updates

[coverage: high]

When implementation decisions become real, update:

- This topic for commands and repo layout.
- `wiki/topics/target-architecture.md` for module boundaries.
- `wiki/topics/testing-posture-and-conventions.md` for test commands.
- `wiki/log.md` for major milestones.

## Sources

- `wiki/topics/target-architecture.md`
- `assets/ui/README.md`
- `docs/audits/2026-06-03-pdf-extraction-audit.md`
- `docs/audits/2026-06-03-page-text-ocr-extraction.md`
- `docs/plans/2026-06-04-page-text-import-global-fts-implementation-plan.md`
- `docs/adr/0001-conda-python-tooling.md`
- `docs/adr/0002-managed-local-pdf-storage.md`
- `environment.yml`
- `AGENTS.md`
