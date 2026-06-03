# Page Text OCR Extraction

Date: 2026-06-03

Root extracted: `/Users/aftoncarlson/TTRPGs/WFRP 2e`

## Summary

Page-level text references were generated for the full 26-PDF WFRP 2e library.
The extraction used embedded PDF text where available and Tesseract OCR where
embedded text was missing or too short.

The extracted text itself is private derived data and is stored only under
ignored `data/page_text/`. No extracted book text is committed in this report.

## Local Output

- Directory: `data/page_text/`
- Files: 26 JSON files, one per source PDF
- Size: approximately 16 MB

Each JSON file contains:

- `book_id`
- `title`
- `category`
- `source_path`
- `source_sha256`
- `page_count`
- `pages[]`

Each page record contains:

- `page_number`
- `text`
- `extraction_method`
- `embedded_text_chars`
- `text_chars`
- `word_count`
- `image_count`
- `ocr_attempted`
- `ocr_error`

## Results

| Metric | Value |
|--------|-------|
| Books processed | 26 |
| Pages written | 3,736 |
| Characters written | 15,612,529 |
| Words written | 2,668,305 |
| Empty OCR pages | 131 |
| OCR errors | 0 |

## Extraction Methods

| Method | Page count |
|--------|------------|
| embedded | 391 |
| ocr | 3,214 |
| ocr-empty | 131 |

## Notes

- `ocr-empty` pages still have page records and source references, but produced
  no text. These are likely covers, full-page art, maps, blank pages, or
  pages where OCR could not detect text.
- PyMuPDF's installed Conda build does not include built-in OCR support, so the
  tool renders temporary page images and calls the local `tesseract` command.
  Temporary images are deleted after each page.
- This output is ready to feed the next local indexing step: SQLite metadata,
  exact full-text search, and later vector chunks.
