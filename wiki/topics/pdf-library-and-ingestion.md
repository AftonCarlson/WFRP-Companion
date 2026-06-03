# PDF Library And Ingestion

## Library Responsibilities

[coverage: medium]

The library should track each owned PDF with:

- Stable book id.
- Display title.
- File path or managed storage path.
- Page count.
- Extraction status.
- Optional cover image or first-page thumbnail.
- Optional edition/source metadata.

Avoid storing large copied text in fixtures or docs. Keep extracted text local.

## Reader Responsibilities

[coverage: medium]

The GUI should allow a GM to open a book, navigate pages, search within the
book, and jump from a chat citation directly to the cited page. PDF.js is the
likely browser-side renderer.

## Extraction Pipeline

[coverage: medium]

Ingestion should run through the repo Conda environment and preserve page-level
provenance:

- Extract text page by page.
- Keep book id, page number, and extraction method.
- Detect low-text pages that may need OCR.
- Normalize whitespace enough for search without destroying table/list meaning.
- Chunk text with overlap, but keep every chunk tied back to page spans.

The initial extraction spike should use PyMuPDF from `environment.yml`, with
Poppler tools available for independent metadata/text-density cross-checks.

## OCR

[coverage: low]

Some PDFs may be scanned, image-heavy, or have maps/tables with poor text
layers. Add OCR as a second phase after basic text extraction works. OCR output
should be labeled so lower-confidence text can be treated carefully.

## Maps And Images

[coverage: low]

Maps and visual references should stay linked to PDF pages at first. Do not try
to solve map extraction before the reader plus citation loop works.

## Sources

- `wiki/topics/target-architecture.md`
- `wiki/topics/local-tooling-and-packaging.md`
- `wiki/concepts/private-copyright-boundary.md`
