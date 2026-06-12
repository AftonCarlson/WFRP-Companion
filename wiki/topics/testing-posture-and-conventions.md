# Testing Posture And Conventions

## Current State

[coverage: high]

Application tests now exist for the Phase 1 SQLite/config foundation, the Phase
2 managed PDF library importer, the page-text importer, the global exact-search
path, Phase 3 source-set management/search scoping, Phase 4 local FastAPI
backend API, Phase 5 browser GUI, Phase 6 Familiar chat loop, Phase 7 PR1
source-object migration/model foundation, Phase 7 PR2 deterministic
source-object extraction foundation, Phase 7 PR3 Familiar source-map/object
retrieval, Phase 7 PR4 retrieval-module split, and Phase 7 PR5 durable
source-map/profile ownership, Phase 7 PR6 source-object search backfill, and
Phase 7 PR7 retrieval rank fusion/reranker protocol, Phase 7 PR8 local
vector retrieval channel, Phase 7 PR9 structured source-object evidence, Phase
7 PR10 printed page-label calibration/backfill, Phase 7 PR11 Familiar prompt
history/history-aware retrieval planning, the local semantic embeddings phase,
the Familiar tool-calling hybrid RAG research-agent phase, the Familiar
evidence-gate hardening phase, the Familiar reliability-contract phase, and
the structured evidence validation phase.
Structured evidence validation tests now cover the reviewed table/profile
layer, the v2 contract registry, synthetic-only contract fixtures, the manual
review API/UI, intent-gated resolver integration, and retrieval-status counts.
Contract tests cover label-identity rejection, group profile identity with
race/career fields, stat-grid-only profile acceptance, profile provenance,
career-entry advance schemes, scoped unnumbered tables, embedded-child table
parents, empty-cell table rejection, rules-entry bodies, and unknown contract
shape handling. Follow-up regressions cover PyMuPDF layout metadata not
creating missing-table candidates, force rebuilds after unreviewed, approved,
corrected, and rejected candidates preserving review history without
unique-index collisions, reviewed observation snapshots surviving rebuilds,
active validated objects being filtered from retrieval immediately on source
snapshot drift, and singular/plural evidence identity matching.
Python testing runs through the `wfrp-companion` Conda environment. Frontend
testing runs through npm in `frontend/`.

## Expected Coverage

[coverage: medium]

Prioritize tests around places where silent errors would damage trust:

- PDF extraction preserves book/page metadata.
- Chunking keeps citations attached to source pages.
- Full-text search finds exact rules and names.
- Vector retrieval does not suppress exact matches.
- Prompt construction includes citations and respects context limits.
- Assistant responses handle missing context honestly.
- Citation links open the correct PDF page.
- Turn triage keeps direct/clarifying turns out of research and provider
  construction.
- App-owned requirement plans cover every required part of multi-part rules and
  statline requests before retries.
- Retry runs execute the persisted turn decision contract rather than a fresh
  classifier result.
- Public provider failures use bounded safe messages and do not persist raw
  exception strings.

## Test Types

[coverage: medium]

- Unit tests for chunking, ranking, citation assembly, and prompt shaping.
- Integration tests for ingestion through search.
- UI tests for library, reader, search, and chat flows once the frontend exists.
- Regression fixtures using synthetic or public-domain sample PDFs, not WFRP
  book text.

## Commands

[coverage: medium]

Once Python tests exist:

```bash
conda activate wfrp-companion
python -m pytest
```

Run lint checks with:

```bash
conda activate wfrp-companion
ruff check .
```

Current coverage gate:

```bash
conda activate wfrp-companion
python -m pytest --cov=wfrp_companion --cov=tools.init_db --cov=tools.import_pdfs --cov=tools.import_page_text --cov=tools.rebuild_fts --cov=tools.rebuild_source_object_fts --cov=tools.rebuild_source_maps --cov=tools.rebuild_embeddings --cov=tools.rebuild_retrieval_assets --cov=tools.backfill_page_labels --cov=tools.search_text --cov=tools.source_sets --cov=tools.serve_api --cov=tools.dev --cov=tools.migrate_db --cov=tools.extract_source_objects --cov=tools.extract_structured_evidence --cov-report=term-missing --cov-fail-under=100
```

Current frontend verification commands:

```bash
cd frontend
npm run test
npm run test:coverage
npm run build
npm run test:e2e
```

Frontend coverage thresholds are configured in `frontend/vitest.config.ts`:
90% statements, branches, functions, and lines. Playwright e2e specs live under
`frontend/e2e/` and are excluded from Vitest unit coverage.

Use `python -m pytest` rather than bare `pytest`; it reliably keeps the repo
root on `sys.path` for local package imports in this checkout.

Current focused test files:

- `tests/api/test_app.py`
- `tests/api/test_errors.py`
- `tests/api/test_library_routes.py`
- `tests/api/test_openapi.py`
- `tests/api/test_search_routes.py`
- `tests/api/test_source_set_routes.py`
- `tests/assistant/test_chat_service.py`
- `tests/assistant/test_chat_store.py`
- `tests/assistant/test_answer_contract.py`
- `tests/assistant/test_conversation_context.py`
- `tests/assistant/test_context_resolution.py`
- `tests/assistant/test_evidence_policy.py`
- `tests/assistant/test_evidence_validation.py`
- `tests/assistant/test_familiar_agent.py`
- `tests/assistant/test_familiar_golden_contract.py`
- `tests/assistant/test_prompt_diagnostics.py`
- `tests/assistant/test_prompts.py`
- `tests/assistant/test_provider.py`
- `tests/assistant/test_requirement_planner.py`
- `tests/assistant/test_research.py`
- `tests/assistant/test_research_tools.py`
- `tests/assistant/test_retrieval.py`
- `tests/assistant/test_retrieval_module_contracts.py`
- `tests/assistant/test_structured_evidence_integration.py`
- `tests/assistant/test_turn_contract.py`
- `tests/db/test_schema.py`
- `tests/db/test_migrations.py`
- `tests/library/test_identity.py`
- `tests/library/test_discovery.py`
- `tests/library/test_storage.py`
- `tests/library/test_catalog.py`
- `tests/library/test_importer.py`
- `tests/library/test_page_text_importer.py`
- `tests/library/test_page_labels.py`
- `tests/library/test_retrieval_status.py`
- `tests/library/test_source_sets.py`
- `tests/search/test_fts.py`
- `tests/search/test_scope.py`
- `tests/tools/test_import_pdfs.py`
- `tests/tools/test_import_page_text.py`
- `tests/tools/test_rebuild_fts.py`
- `tests/tools/test_search_text.py`
- `tests/tools/test_serve_api.py`
- `tests/tools/test_dev.py`
- `tests/tools/test_migrate_db.py`
- `tests/tools/test_extract_source_objects.py`
- `tests/tools/test_rebuild_embeddings.py`
- `tests/tools/test_rebuild_retrieval_assets.py`
- `tests/tools/test_rebuild_source_object_fts.py`
- `tests/tools/test_rebuild_source_maps.py`
- `tests/tools/test_backfill_page_labels.py`
- `tests/tools/test_source_sets_cli.py`
- `tests/source_objects/test_models.py`
- `tests/source_objects/test_extractor.py`
- `tests/source_objects/test_layout.py`
- `tests/source_objects/test_embeddings.py`
- `tests/source_objects/test_object_search_backfill.py`
- `tests/source_objects/test_source_map_builder.py`
- `tests/source_objects/test_store.py`
- `tests/structured_evidence/test_candidates.py`
- `tests/structured_evidence/test_contract_registry.py`
- `tests/structured_evidence/test_contracts_career_entry.py`
- `tests/structured_evidence/test_contracts_profile_card.py`
- `tests/structured_evidence/test_contracts_rules_entry.py`
- `tests/structured_evidence/test_contracts_structured_table.py`
- `tests/structured_evidence/test_failure_fixtures.py`
- `tests/structured_evidence/test_structured_evidence_models.py`
- `tests/structured_evidence/test_readers.py`
- `tests/structured_evidence/test_structured_evidence_store.py`
- `tests/structured_evidence/test_suspicion.py`
- `tests/tools/test_extract_structured_evidence.py`
- `frontend/src/**/*.test.ts`
- `frontend/src/**/*.test.tsx`
- `frontend/e2e/workspace.spec.ts`

They cover configuration defaults/overrides, SQLite initialization, WAL/foreign
key settings, lifecycle constraints, source/asset boolean constraints, asset
page consistency, explicit schema migrations, migration rollback behavior,
missing/uninitialized DB refusal, duplicate legacy retrieval-rank preflights,
source-object constraints and deterministic normalized IDs, the
source-object constraints and deterministic normalized IDs, source-object
extraction lifecycle/status/job behavior, text snapshot hashing, layout
fallback, OCR confidence metadata, heading-derived rule sections, page-chunk
fallback, same-page/same-title object ID stability, the
`tools/extract_source_objects.py` CLI entrypoint, source-object search/FTS
backfill from existing `source_objects`, stale projection/FTS-index repair,
FTS vocabulary and rowid validation, idempotent object-search rebuild skips,
object-type posting validation, stale status repair,
`tools/rebuild_source_object_fts.py` count-only CLI output, source-map rebuild
lifecycle, book retrieval status backfill,
durable source-map freshness/fallback behavior, source-map query-profile
rebuilds, `retrieval_run_source_books` snapshots, the
`tools/rebuild_source_maps.py` CLI entrypoint, local source-object embedding
rebuilds, vector snapshot invalidation, stale embedding job recovery,
checked-book vector candidate filtering, malformed embedding-row scope
protection, `tools/rebuild_embeddings.py` count-only CLI output,
`tools/rebuild_retrieval_assets.py` orchestration, retrieval-status aggregate
counts, vector readiness summaries, model-name redaction, the
`tools/init_db.py` CLI entrypoint, managed PDF identity, recursive discovery,
SHA/atomic-copy storage
helpers, idempotent library import, copy-job recovery, collision/failure
reporting, the `tools/import_pdfs.py` CLI entrypoint,
page-text JSON validation, import idempotency, failed/stale import repair,
file-level quarantine jobs, global FTS rebuild idempotency, stale FTS
projection cleanup, FTS integrity checks, readiness-gated exact search,
source-set membership sync/idempotency/conflict handling, active source-set
selection, per-book source-set toggles, active source-set search defaults,
whole-library override behavior, per-book search filters, shared search scope
resolution, API startup/health, OpenAPI route presence, API error mapping,
book/page/page-text/PDF reader routes, PDF range/path-safety responses,
source-set routes, exact-search routes, chat routes, and the page-text,
source-set, search, API, dev, migration, and source-object extraction CLI
entrypoints.

Familiar research-agent regressions also cover provider-shaped short
requirement ids such as `r1`, matching parser validation against published tool
schemas and persisted `familiar_research_plans` / `familiar_tool_calls` /
`familiar_evidence_judgments` rows, published parser bounds such as term-list
limits in provider tool schemas, and deduplication of repeated accepted
evidence before requirement-ledger counting or final `retrieval_hits`
persistence. Migration regressions include a schema sentinel that fails if
rebuilt SQLite tables retain temporary `_before_` or `_bad_fk` foreign-key
references.

Retrieval-specific tests now also cover RRF deterministic ordering,
same-channel dedupe before fusion-rank assignment, weak lexical-only
rejection, exact table/object-type query preservation, deterministic reranker
protocol exports, and persisted rank reasons that include channel
contribution, fusion score, and reranker judgment. Vector-channel tests cover
disabled-by-default behavior, provider-aware schema and migrations, provider
factory behavior, Sentence Transformers lazy loading and fake-module encode
options, dependency/runtime/dimension failures, query-time provider failure
fallback to non-vector retrieval, checked-book filtering, current-snapshot
gating, malformed row scope protection, malformed vector blob currentness and
query-time scoring fallback, safe source-object drift handling during
inference, failed rebuild job closeout after provider failure, no write
transaction during embedding inference, fake semantic recall without exact term
overlap, provider rank reasons, Library/API vector readiness fields with model
names redacted from API responses, and exact lexical/object hits staying ahead
of vector-only candidates.
Structured-evidence tests cover `glossary_entry` and `glossary_definition`
schema/migration support, table/table-row extraction and parent links,
stat/profile extraction and links, index/glossary/cross-reference extraction,
extractor-version invalidation, duplicate same-page table-row ID prevention,
WFRP-style pipe/percent stat profiles, range-chart table extraction with OCR
title normalization, derived source-object links and count updates, table-row
citations resolving to parent table page ranges, stat-block retrieval resolving
to complete profiles, compound/plural structural queries retrieving singular
stat evidence through generalized sparse alternatives, `stat line`/`statline`
queries routing to statistics evidence instead of movement/profile prose,
source-object-local entity validation that rejects neighboring-object snippets
and wrong-titled body overlaps, short page-chunk context expansion around
source spans, structural query terms refusing unsafe fuzzy expansion,
typed chart/table evidence outranking prose mentions, heading/running-header
only entity matches being rejected, index routing to deterministic target
sections or page-only target pages, glossary evidence retaining definition
context without fake disjoint page ranges, link traversal refusing unchecked-book
targets, duplicate equivalent rule-section ID avoidance, and safe historical
retrieval-hit detachment when source objects are replaced. Page-label tests
cover offset-anchor calibration,
roman/front-matter preservation, snapshot drift anchor reuse, manual-review
conflict suppression, exact/search source-object/linked-page citation labels,
safe count-only CLI failure output, and reloaded chat citation labels/ranges.
Conversation-context tests cover
bounded prior completed-turn selection, failed/active/current-message
exclusion, retry anchoring before the original user message, prompt-history
budgeting, self-contained retrieval queries staying unchanged, follow-up
retrieval-query contextualization and caps, compact salient history terms,
assistant failure-answer filtering for retrieval planning, disabled history
limits, provider `store=False`, prompt history/evidence separation, retrieval
metadata for planned queries, stream-interruption cleanup, and logical retry
collapse in chat API/frontend read models.

Familiar research-agent tests cover thread-context subject preservation,
follow-up resolution, page-aware recovery, reader-context page hints, bounded
tool rounds, provider tool call planning, tool argument validation,
accepted-only final retrieval runs, partial/rejected evidence traces,
evidence-status transitions, research run and tool-call persistence, retrieval
diagnostics metadata, stream event mapping, and final prompt construction from
accepted evidence only.
Evidence-gate regressions also cover generic structural subjects failing
closed, subjectless page evidence requiring both book and page anchors,
included/excluded subject terms, multi-word structural subject phrase matching,
object-type/book/page hint normalization, statline field sufficiency,
checked-scope link hydration, accepted-only UI/tool payloads, and synthetic
whole-library failure modes such as career/profile false positives, wrong
named entities, table/prose mentions without stat fields, heading-only matches,
vector-only wrong-entity candidates, and scattered multi-word subjects.

Familiar reliability-contract tests cover direct/clarifying turn triage,
provider-unavailable direct responses, advisory provider planning fallback,
deterministic app-owned requirement planning, zero-attempt requirement
scheduling before retries, corrective evidence policy, partial/insufficient
answer outcomes, retry decision immutability, safe public provider error
messages, `turn_decision` stream events, and golden user-level failures such as
hit-location plus armor-by-location lookup.

Frontend tests cover the API client, initial workspace loading, validated
workspace storage, pointer and keyboard panel resize/collapse/maximize
behavior, Library/Search tabs, grouped book sections, per-book source-set
toggles, section-level Library bulk toggles, absence of noisy per-book
readiness labels, search result full text expansion/error handling, Grimoire
tab, page, zoom, and view-mode behavior, two-page spread math, guarded PDF.js
rendering/retry and cancellation behavior, Familiar shell behavior,
`turn_decision` event handling, Familiar reader-context request payloads,
expandable research trace rendering including accepted/partial/rejected
evidence counts and reason counts, safe Familiar markdown rendering, explicit
PDF-page citation/search opens, and browser e2e flows for
Library/Search/Grimoire/Familiar page-aware chat plus panel overflow.

The latest full backend verification command on 2026-06-10 reported 799 tests
passing with 100.00% coverage for `wfrp_companion` plus tracked tool modules.
The latest frontend verification reported 148 Vitest tests passing with
coverage above the configured 90% thresholds and a successful production build.

## Manual QA

[coverage: medium]

For the MVP, manual QA should include:

- Import a PDF.
- Open it in the reader.
- Search for an exact term.
- Ask a rules question.
- Confirm the answer cites the right book/page.
- Click the citation and verify the reader lands on that page.

Phase 5 browser QA also included a live local API check: load the real library,
search for `critical hit`, verify grouped results, open a result into a
Grimoire tab at page 134, confirm source tabs omit page-number suffixes, confirm
two-page view can be toggled, and confirm the Familiar composer remains
reachable without page-level scrolling.

The 2026-06-05 page-drift regression pass added a live local check that search
results display explicit `PDF page` labels and that opening a search hit lands
Grimoire on the same PDF page in single-page mode. Automated coverage also
checks `pdf_page_number`/`page_label` API fields, search and Familiar citation
open behavior, page-label import freshness, and markdown table rendering in
Familiar output.

## Sources

- `wiki/topics/implementation-standards.md`
- `wiki/topics/local-tooling-and-packaging.md`
- `wiki/topics/pdf-library-and-ingestion.md`
- `wiki/topics/ai-rag-system.md`
