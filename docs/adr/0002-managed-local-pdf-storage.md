# ADR 0002: Use Managed Local PDF Storage

## Status

Accepted

## Context

WFRP Companion needs stable runtime access to user-owned PDFs for later reading,
search citation jumps, page-text import, and visual asset detection. The source
library lives outside the repository at `/Users/aftoncarlson/TTRPGs/WFRP 2e`
and is user-owned, not app-owned runtime storage.

The application is private and local-first. Generated runtime files, copied
PDFs, indexes, and SQLite databases are ignored by Git.

## Decision

Copy every readable imported PDF into app-managed local storage under:

```text
data/library/pdfs/<book_id>/source-<original_sha256>.pdf
```

Store the active managed file as an absolute path in `books.managed_pdf_path`.
Store the source and managed hashes in `books.original_sha256` and
`books.managed_sha256`.

SQLite remains the source of truth for metadata and lifecycle state. Managed
PDF files are runtime artifacts whose validity is represented by the database.

## Consequences

- The local app duplicates the PDF library on disk by design.
- Runtime PDF paths remain stable even if the original source folder later moves.
- Source refreshes are safer because each managed file is versioned by source
  hash before SQLite points `books.managed_pdf_path` at it.
- Interrupted imports can be retried or repaired from database state.
- The original PDF source folder is never mutated by the importer.
- No cloud storage, hosted database, or service account is required for this
  phase.
