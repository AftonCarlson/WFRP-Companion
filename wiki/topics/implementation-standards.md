# Implementation Standards

## Development Contract

[coverage: high]

Build in small, verified slices. For this project, the first durable slice
should prove the loop:

1. Register/import a PDF.
2. Extract page-level text.
3. Search by exact term.
4. Ask a question.
5. Return a cited answer.
6. Jump from citation to PDF page.

## Rules For New Code

[coverage: high]

- Prefer existing local patterns once they exist.
- Keep modules small and named by responsibility.
- Avoid speculative abstractions.
- Separate storage, retrieval, AI prompting, and UI rendering.
- Use the `wfrp-companion` Conda environment for Python project commands.
- Add Python dependencies to `environment.yml`.
- Keep copyrighted content out of committed fixtures.
- Keep generated/cached local data out of Git.

## AI-Specific Rules

[coverage: high]

- All rules answers should be grounded in retrieved context when possible.
- Include citations for book/page-backed claims.
- Distinguish retrieved text, summarized interpretation, and generated content.
- Fail gracefully when context is missing.
- Log enough retrieval metadata to debug ranking, not enough to create an
  accidental copy of the books.

## PDF/Search Rules

[coverage: medium]

- Preserve page metadata through every ingestion and chunking step.
- Preserve the existing source-relative book-id convention when moving behavior
  out of tools and into package code; page-text JSON compatibility depends on
  it.
- Keep managed PDF copies versioned by source SHA and store the active absolute
  path in SQLite.
- Use full-text search for exact matches.
- Use vector search for semantic matches.
- Keep citation objects structured rather than parsing them out of prose.

## Database Rules

[coverage: high]

The Phase 1 SQLite schema is the app-owned source-of-truth foundation. New
database behavior should preserve these constraints:

- Keep lifecycle state explicit on `books`.
- Use the `book_readiness` view for derived readiness rather than adding a
  second mutable readiness flag.
- Keep boolean-like state constrained to `0` or `1`.
- Keep `page_assets` consistent with `pages` through the composite page foreign
  key.
- Keep generated SQLite files, managed PDFs, generated assets, and coverage
  files out of Git.
- Keep SQLite transactions short around managed-file work. Hashing and copying
  large PDFs should happen outside long write transactions, with short guarded
  transitions before and after filesystem side effects.

## Documentation Rules

[coverage: high]

- Update the relevant wiki page when a material behavior or decision changes.
- Add a plan under `docs/plans/` for multi-module work.
- Add an ADR under `docs/adr/` when a technology choice creates long-lived
  consequences.

## Verification Checklist

[coverage: high]

Before calling code work complete:

- Run focused tests or explain why tests do not exist yet.
- Verify ingestion/search/citation behavior with a small sample document when
  relevant.
- Check that no private PDFs, extracted book text, API keys, or indexes were
  committed.
- Update wiki/docs if the work changed architecture or workflow.

## Sources

- `AGENTS.md`
- `docs/adr/0001-conda-python-tooling.md`
- `wiki/topics/ai-rag-system.md`
- `wiki/topics/pdf-library-and-ingestion.md`
