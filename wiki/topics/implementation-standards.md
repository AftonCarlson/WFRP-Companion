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
- Familiar now has an app-owned reliability contract: `turn_contract.py`
  triages turns before provider construction, `requirement_planner.py` builds
  the accepted deterministic research plan, `familiar_agent.py` schedules local
  tool actions by unsatisfied requirement coverage, and `answer_contract.py`
  records whether the final response is full, partial, insufficient, direct,
  clarifying, or provider-error.
- `familiar_turn_decisions` stores the turn-level contract. Retry runs copy
  immutable triage fields from the original decision when available, and chat
  execution uses the persisted effective decision rather than a fresh
  classifier result.
- `tools/rebuild_embeddings.py` now rebuilds local source-object vectors when
  embeddings are explicitly enabled. `local-hash` remains the deterministic
  test/smoke provider; `sentence-transformers` is the real local semantic
  provider. The default provider is disabled.
- Source-object extraction now emits structured local evidence objects for
  simple tables/table rows, stat/profile blocks, index entries, glossary
  entries, and cross references, and persists deterministic
  `source_object_links` for parent/target relationships.
- `tools/backfill_page_labels.py` now rebuilds printed page-label calibration
  metadata from imported page labels plus optional offset anchors.

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

## Subagent Review And Lifecycle Tooling

[coverage: high]

The 2026-06-10 diagnosis found that this project had accumulated completed
subagents in the live Codex thread. Because the repo guidance banned
`close_agent` outright after an earlier cleanup hang, completed review agents
remained attached and later `spawn_agent` calls failed with
`agent thread limit reached`. Treat this as lifecycle hygiene for Codex work,
not as WFRP application behavior.

- Prefer serial `executing-plans` work by default. Use
  `subagent-driven-development` only when there are genuinely independent
  tasks and the user has authorized subagent/parallel work.
- Do not make subagent execution mandatory in new implementation plans. A plan
  may require independent review, but it should name acceptable paths such as a
  bounded subagent review, CodeRabbit, or a Codex background thread.
- Use `wait_agent` only with explicit bounded timeouts.
- After a subagent reaches a completed status, close it sequentially before
  spawning more agents. Never call `close_agent` in parallel, and never close a
  running, timed-out, or unknown-status agent.
- If cleanup becomes unreliable or `spawn_agent` reports
  `agent thread limit reached`, run one bounded status diagnostic, record the
  attached agent ids/statuses, stop spawning more subagents in that thread, and
  use CodeRabbit or a Codex background thread for the independent review gate.
- Do not downgrade the review requirement silently. If a required review path
  changes because of tooling lifecycle limits, say so explicitly in the PR
  notes or final status.

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
- Keep structural retrieval terms (`stat`, `block`, `table`, `chart`,
  `profile`, and close variants) authoritative as object-intent signals. Do
  not edit-distance expand them into unrelated source-map aliases.
- Use bounded deterministic sparse query normalization for retrieval recall:
  split common structural compounds such as `statblock`, `statline`, and
  `hit-location`, generate singular/plural FTS candidates, and keep reranker
  match terms concept-level so variants do not double-count relevance.
- Fix retrieval vocabulary gaps with general query/object/indexing rules, not
  entity-specific aliases for one creature, NPC, table, or book.
- For named stat/profile/table requests, validate the named entity against the
  selected source object itself. Do not let page snippets or incidental body
  mentions from neighboring objects prove that a titled object is the requested
  creature, NPC, or table.
- Short fallback `page_chunk` source objects may expand to a bounded page
  window around their source span, but should not dump whole pages into prompt
  context.
- Let inherited chapter headings and OCR running headers help candidate
  routing, but do not let heading-only matches admit multi-term entity evidence
  into Familiar prompt context.
- Treat vector search as another candidate channel. It must be scoped to
  checked books, validated against current local embedding snapshots, and fed
  through rank fusion plus reranking before prompt context.
- Keep vector storage provider-aware. Currentness checks must compare provider,
  model, dimensions, source-object snapshot, row count, row freshness, and
  vector blob byte length.
- Do not hold SQLite write transactions open during local transformer
  inference. Claim/update lifecycle state in short transactions, compute
  embeddings outside the write transaction, then do a guarded final write.
- After an embedding rebuild job is claimed, any provider/load/inference/commit
  failure must close the matching `ingest_jobs` row as `failed` with
  `completed_at`; do not leave retry behavior dependent on stale-job recovery.
- Query-time vector provider failures must fail closed to the non-vector
  retrieval channels. Missing local model files, dependency errors, runtime
  errors, or dimension mismatches should not fail Familiar chat.
- Query-time vector scoring must also fail closed for malformed local vector
  rows. Skip bad vector rows rather than surfacing blob/dimension errors as
  Familiar model-run failures.
- Treat provider planning as advisory metadata. The app must own turn triage,
  accepted requirement plans, scheduler control, evidence validation, answer
  outcomes, and retry decision execution.
- Do not let raw provider or generic exception strings enter public chat
  streams, `model_runs.error_message`, or `familiar_turn_decisions.outcome_json`.
  Use bounded public messages and private diagnostics that expose counts,
  enums, ids, and statuses rather than local paths, provider payloads, PDF
  filenames, or copied source text.
- For multi-requirement research, schedule required zero-attempt requirements
  before retrying an already-attempted unsatisfied requirement. Exact duplicate
  tool actions should still be suppressed.
- Treat linked source-object traversal as evidence resolution, not scope
  expansion. Links may resolve row/stat/index/cross-reference candidates to
  complete parent or target objects only when the target book is in the checked
  `source_book_ids` snapshot. Glossary entries remain canonical glossary
  evidence and can include linked target context.
- Treat structured evidence extraction as candidate generation, not trusted
  truth. `structured_reader_observations` and `structured_evidence_candidates`
  are untrusted until a review action writes an active
  `validated_structured_objects` row.
- Familiar may use validated structured objects only through the requirement
  policy contract. Statline requests can require active profile bundles;
  explicit table/rules requests can allow active structured tables; scene prep
  can use profiles as support; lore/general lookup should remain
  `not_primary`.
- Validated structured hits must carry the validated object id, payload schema
  version, payload hash, validation status, source snapshot, and structured
  lookup policy into retrieval hit metadata. Stale, retired, or unvalidated
  structured rows must not satisfy evidence validation.

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
- Keep deterministic table/stat/index/glossary/cross-reference extraction
  conservative, but preserve common WFRP OCR table shapes already supported by
  the extractor: pipe/percent main and secondary profile rows, simple pipe
  tables, and range charts such as hit-location tables. Prefer missing an
  ambiguous structure over creating a confident wrong link; richer OCR-layout
  table reconstruction belongs in a later phase.
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
  vector candidates are explicitly enabled. Use `local-hash` for deterministic
  smoke tests and `sentence-transformers` with `BAAI/bge-m3` for real local
  semantic retrieval. The command is count-only and must not print private
  source-object text.
- Run `tools/backfill_page_labels.py` after page-text import when printed
  labels need to be calibrated or repaired. Use repeatable
  `--anchor book_id:pdf_page_number:printed_label` values for books whose
  printed page 1 starts after roman/front-matter pages.
- Page-label backfill output must stay count-only and must not print page text
  or raw exception details. Failure summaries should be safe categories.
- Do not display raw PDF page numbers as confident printed labels. If
  calibration is missing or a book needs manual review, keep printed label
  fields absent while retaining `pdf_page_number` for reader jumps.
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
- Keep source-object extraction currentness versioned. When deterministic
  extraction heuristics change, bump the extractor version or otherwise mark
  old extracted/indexed rows stale so normal extraction refreshes object/link
  output.
- Treat `source_objects` as canonical private local structured evidence and
  `source_object_search` / `source_object_search_fts` as rebuildable
  projections.
- Object-search repair tools must rebuild projections from `source_objects` and
  report only counts and bounded failure reasons, never extracted private text.
- Keep source-object extractor output count-oriented. Do not log or commit
  extracted book text.
- Keep `source_object_links` local and derived. Parent/child links and
  index/glossary/cross-reference targets must not bypass Library checkbox
  scope during retrieval.
- Keep retrieval-asset lifecycle state explicit in `book_retrieval_status`;
  do not infer source-map/vector/table/page-label readiness from projection row
  presence alone.
- Keep structured-evidence review history append-only. Correcting or approving
  candidates should create review events and active validated objects rather
  than mutating historical review rows.
- Keep `book_retrieval_status.embedding_provider` and
  `source_object_embeddings.embedding_provider` authoritative for vector cache
  ownership. Rebuilds must delete/replace only rows for the same
  book/provider/model/dimensions and must preserve other provider/model rows.
- Keep embedding model names internal to storage, tooling, and rank audit
  reasons. Do not expose `/api/books` model strings because local Sentence
  Transformers model identifiers can be filesystem paths.
- Keep rebuild job state and vector lifecycle state in sync. A failed local
  provider load or inference attempt must mark both the book vector status and
  the claimed rebuild job failed.
- Keep printed-page calibration details in `book_page_label_calibrations`.
  `book_retrieval_status.page_label_status` is only the summary lifecycle
  state.
- Plain page-label backfill reruns should preserve current anchored
  calibrations and reuse stored anchors after page text/label snapshot drift.
  Use `--force` or a new `--anchor` when replacing an anchored calibration
  intentionally.
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
