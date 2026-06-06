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

The current codebase has working local implementations for steps 1 through 6:

- PDF registration/import is owned by `wfrp_companion/library/importer.py` and
  `tools/import_pdfs.py`.
- Page-level text import is owned by
  `wfrp_companion/library/page_text_importer.py` and
  `tools/import_page_text.py`.
- Exact full-text search is owned by `wfrp_companion/search/fts.py`,
  `tools/rebuild_fts.py`, and `tools/search_text.py`.
- Source-set scope selection is owned by
  `wfrp_companion/library/source_sets.py` and `tools/source_sets.py`; the search
  CLI uses the active source set by default.
- The local API in `wfrp_companion/api/` exposes health, book catalog, guarded
  PDF reader, source-set, and exact-search routes over the same SQLite state.
- `wfrp_companion/search/scope.py` owns shared CLI/API scope resolution for
  active source-set, named source-set, explicit book, and whole-library search.
- `wfrp_companion/assistant/` owns the first Familiar chat loop: thread
  creation, source-set snapshot retrieval, bounded prompt construction,
  OpenAI provider streaming, retrieval/model-run persistence, and cited
  responses.
- `frontend/src/components/chat/AgentChatPanel.tsx` streams Familiar output and
  opens citations in Grimoire.
- `wfrp_companion/db/migrations.py`, `tools/migrate_db.py`, and
  `wfrp_companion/source_objects/` now provide the Phase 7 source-object
  foundation: explicit migrations, typed model contracts, deterministic
  `rule_section` and `page_chunk` extraction, and object extraction lifecycle
  state for future object-aware retrieval.
- `tools/rebuild_source_maps.py` now rebuilds durable checked-book
  source-map/profile metadata after source objects are current. Familiar uses
  current durable source maps when available and falls back safely when they are
  stale, missing, or malformed.
- `tools/rebuild_source_object_fts.py` now repairs source-object search and
  FTS projections from existing `source_objects` without rerunning extraction.
- Familiar retrieval now fuses candidate-channel ranks and applies a
  replaceable reranker protocol. The default reranker is deterministic and
  local; provider-backed reranking is not part of the current codebase.
- `tools/rebuild_embeddings.py` now rebuilds local source-object vectors when
  `WFRP_EMBEDDING_PROVIDER=local-hash`; the default provider is disabled.

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
- Treat lexical/page/object search as candidate generation. A reranker must
  decide whether a candidate is relevant enough to enter Familiar prompt
  context.
- Treat vector search as another candidate channel. It must be scoped to
  checked books, validated against current local embedding snapshots, and fed
  through rank fusion plus reranking before prompt context.

## PDF/Search Rules

[coverage: medium]

- Preserve page metadata through every ingestion and chunking step.
- Preserve the existing source-relative book-id convention when moving behavior
  out of tools and into package code; page-text JSON compatibility depends on
  it.
- Keep managed PDF copies versioned by source SHA and store the active absolute
  path in SQLite.
- Use full-text search for exact matches.
- Preserve exact object-type lookup signals such as tables and stat blocks in
  reranker relevance text, even when private body text does not repeat the type
  label.
- Rebuild global FTS through `tools/rebuild_fts.py` after page text changes.
- Run `tools/source_sets.py init` after importing books so built-in source sets
  include all current books.
- Run `tools/extract_source_objects.py` after page text import and global FTS
  rebuild when typed source-object rows need to be refreshed.
- Run `tools/rebuild_source_object_fts.py` when existing `source_objects` need
  their `source_object_search` / `source_object_search_fts` projection repaired
  without rerunning extraction.
- Run `tools/rebuild_source_maps.py` after source-object extraction when
  durable Familiar source-map/profile metadata needs to be refreshed.
- Run `tools/rebuild_embeddings.py` after source-object extraction when local
  vector candidates are explicitly enabled. The command is count-only and must
  not print private source-object text.
- Treat `source_set_books.enabled` as scope membership only. Do not use it as a
  replacement for readiness state.
- Keep exact-search readiness gating in `search_exact()` and the `books`
  lifecycle columns.
- Keep CLI and API search scope behavior in
  `wfrp_companion/search/scope.py`; do not duplicate active-source-set or
  conflict rules in route handlers.
- API search should validate explicit unknown `book_id` values as `404`; CLI
  direct book filters may continue to return zero hits for unknown IDs.
- Keep managed filesystem paths out of JSON API responses. Serve PDFs through
  guarded reader routes that validate the path remains under
  `data/library/pdfs/<book_id>/` and has a `.pdf` suffix.
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
- Treat ignored `data/page_text/*.json` as import input only. Runtime text
  ownership belongs to SQLite `pages` and `page_text`.
- Treat `page_search` and `page_search_fts` as rebuildable search projections,
  not canonical text storage.
- Do not let exact search return pages unless `books.copy_status='copied'`,
  `books.text_status='imported'`, and `books.search_status='indexed'`.
- Use `source_sets` for named book groups, `source_set_books.enabled` for
  individual book toggles, and `app_settings.active_source_set_id` for the
  default search/retrieval scope.
- Keep source-set membership separate from the `book_readiness` view; readiness
  is derived from lifecycle state, not from user scope selection.
- Use explicit migrations in `wfrp_companion/db/migrations.py` for existing
  SQLite databases when a change cannot be handled by replaying
  `schema.sql`.
- Migration tools must refuse typo/missing DB paths and uninitialized SQLite
  files rather than creating partial application state.
- Keep typed source-object extraction state explicit in
  `book_object_status`; do not infer readiness from frontend state or incidental
  FTS projection rows.
- Treat `source_objects` as canonical private local structured evidence and
  `source_object_search` / `source_object_search_fts` as rebuildable
  projections.
- Object-search repair tools must rebuild projections from `source_objects` and
  report only counts and bounded failure reasons, never extracted private text.
- Keep source-object extractor output count-oriented. Do not log or commit
  extracted book text.
- Keep retrieval-asset lifecycle state explicit in `book_retrieval_status`;
  do not infer source-map/vector/table/page-label readiness from projection row
  presence alone.
- Treat `book_source_maps` as the owner of compact source-map routing metadata.
  `book_query_profiles` is a derived boost table and should be rebuilt from the
  current source map.
- Source-map snapshots must include every input that can affect routing:
  relevant book metadata plus source-object ids, types, titles, heading paths,
  page ranges, and text snapshots.
- Retrieval runs must snapshot checked books into `retrieval_run_source_books`
  as queryable proof of Library checkbox scope. JSON metadata can remain for
  compatibility, but should not be the only audit trail.

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
- Run `ruff check .`.
- Run the 100% coverage gate from
  `wiki/topics/testing-posture-and-conventions.md` when Python behavior
  changes.
- Verify ingestion/search/citation behavior with a small sample document when
  relevant.
- Check that no private PDFs, extracted book text, API keys, or indexes were
  committed.
- Update wiki/docs if the work changed architecture or workflow.

## Sources

- `AGENTS.md`
- `docs/adr/0001-conda-python-tooling.md`
- `docs/plans/2026-06-04-page-text-import-global-fts-implementation-plan.md`
- `docs/plans/2026-06-04-phase-3-source-sets-implementation-plan.md`
- `docs/plans/2026-06-04-phase-4-local-backend-api-implementation-plan.md`
- `wiki/topics/ai-rag-system.md`
- `wiki/topics/pdf-library-and-ingestion.md`
