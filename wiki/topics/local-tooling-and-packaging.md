# Local Tooling And Packaging

## Current State

[coverage: high]

The repo has not chosen the full application stack yet, but Python tooling is
standardized on Conda. The canonical environment is `environment.yml` with the
environment name `wfrp-companion`.

Conda is used for PDF ingestion and backend/search prototypes. Do not install
Python project dependencies globally or through an untracked virtualenv.

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
- pytest for tests
- ruff for lint/format checks

## Environment

[coverage: medium]

Expected secrets/config:

- OpenAI API key.
- Local data directory.
- Optional OCR binary/config.
- Optional model overrides.

Do not commit real API keys, PDFs, extracted copyrighted text, or local vector
indexes. UI art assets intended for the app may be committed under `assets/ui/`.

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
- `docs/adr/0001-conda-python-tooling.md`
- `environment.yml`
- `AGENTS.md`
