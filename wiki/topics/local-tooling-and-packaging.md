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

Phase 2 added the local managed-PDF library importer:

- `wfrp_companion/library/identity.py` for stable book and folder IDs.
- `wfrp_companion/library/discovery.py` for recursive PDF discovery.
- `wfrp_companion/library/storage.py` for SHA-256 hashing and atomic managed
  PDF copies.
- `wfrp_companion/library/importer.py` for SQLite-backed folder, book, and copy
  job state.
- `tools/import_pdfs.py` for importing all configured source PDFs into managed
  local storage.

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
are ignored by Git.

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
- `docs/adr/0001-conda-python-tooling.md`
- `docs/adr/0002-managed-local-pdf-storage.md`
- `environment.yml`
- `AGENTS.md`
