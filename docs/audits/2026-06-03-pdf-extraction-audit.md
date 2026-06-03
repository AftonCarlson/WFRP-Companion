# PDF Extraction Audit

Date: 2026-06-03

Root audited: `/Users/aftoncarlson/TTRPGs/WFRP 2e`

## Summary

The first extraction audit scanned 26 PDFs and 3,736 total pages using PyMuPDF
inside the `wfrp-companion` Conda environment.

No extracted book text is stored in this report. The detailed JSON/CSV audit
outputs are local-only under `data/audits/`, which is ignored by Git.

## Results

| Health | Count |
|--------|-------|
| good | 2 |
| needs-review | 24 |

The two PDFs with useful embedded text are:

| Book | Pages | Avg chars/page | Low-text pages | Likely OCR pages |
|------|-------|----------------|----------------|------------------|
| Tome of Salvation | 258 | 4513.94 | 5 | 5 |
| Nights Dark Masters | 144 | 3726.85 | 6 | 6 |

The remaining 24 PDFs returned zero extracted text on every page and should be
treated as image/scanned PDFs until OCR proves otherwise.

## Implications

- OCR is likely required for most of the library, including the Core Rules.
- The ingestion pipeline should support mixed extraction methods per page.
- The app should keep extraction method and confidence metadata with every page
  and chunk.
- Exact search and RAG work should start only after OCR strategy is decided for
  the image-only PDFs.

## Local Outputs

- `data/audits/pdf_extraction_audit.json`
- `data/audits/pdf_extraction_audit.csv`

These files contain numeric extraction metadata only, but remain local because
they describe the user's private PDF library.
