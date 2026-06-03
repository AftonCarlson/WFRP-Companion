# ADR 0001: Use Conda For Python Tooling

## Status

Accepted

## Context

WFRP Companion needs local Python tooling for PDF inspection, text extraction,
ingestion experiments, search prototypes, and later backend services. The user
has Conda installed locally and wants it to be the Python package manager for
this project.

## Decision

Use Conda as the canonical Python package manager for this repo. Keep the
project environment in `environment.yml` and prefer Conda packages from
`conda-forge` for Python runtime dependencies and native utilities.

The initial environment supports the PDF ingestion spike:

- Python 3.12
- PyMuPDF for PDF inspection and extraction
- Poppler tools for independent PDF metadata/text checks
- Tesseract for OCR through PyMuPDF's OCR text-page path
- pytest for tests
- ruff for linting/format checks

## Consequences

- Python commands should be run inside the `wfrp-companion` Conda environment.
- Add Python dependencies to `environment.yml`, not ad hoc global installs.
- Use `conda env update -f environment.yml --prune` to keep local environments
  aligned.
- Do not commit local Conda environment directories.

## Commands

```bash
conda env create -f environment.yml
conda activate wfrp-companion
conda env update -f environment.yml --prune
```
