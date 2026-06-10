# Wiki Compile Log

## 2026-06-10 Structured Evidence Validation Phase

- Added the structured evidence validation plan at
  `docs/plans/2026-06-10-structured-evidence-validation-plan.md`.
- Added the reviewed structured-evidence schema: reader observations,
  untrusted candidates, active/stale/retired validated structured objects,
  source/alias tables, and append-only review events.
- Added deterministic reader/candidate/suspicion extraction plus
  `tools/extract_structured_evidence.py`; `tools/rebuild_retrieval_assets.py`
  now runs structured extraction after source-object search repair and before
  source maps/page labels/embeddings.
- Added manual review API routes and a Library review tab for approve, correct,
  reject, payload editing, suspicious flags, observations, and page-opening
  links.
- Added Familiar's intent-gated structured resolver. Statline requirements
  require active validated profile bundles; explicit table/rules requirements
  may allow active validated tables; scene prep may use profile support; lore
  and general lookup stay `not_primary`. Stale, retired, and unvalidated
  structured rows cannot satisfy evidence validation.
- `/api/retrieval/status` and the Library status text now report structured
  candidate counts, needs-review counts, and active validated structured
  object counts beside the legacy table/stat and vector readiness counts.
- Final verification: backend full coverage gate passed at 783 tests and
  100.00% coverage; ruff passed across `wfrp_companion`, `tests`, and `tools`;
  frontend Vitest passed 145 tests; frontend production build passed with the
  existing large-chunk warning; CodeRabbit review rerun raised 0 issues. The
  sub-agent review path was blocked by the platform thread limit, so CodeRabbit
  served as the independent AI review for this phase.

## 2026-06-10 Familiar Reliability Contract Phase

- Replaced provider-owned Familiar orchestration with an app-owned reliability
  contract. Turns are triaged before provider construction and stored in
  `familiar_turn_decisions`; direct/clarifying turns complete locally without
  research rows.
- App-owned requirement planning now builds the accepted research plan, while
  provider planning is advisory metadata only. The scheduler prioritizes
  required zero-attempt requirements before retries and suppresses exact
  duplicate actions.
- Added answer outcomes for full, partial, insufficient, direct, clarifying, and
  provider-error responses. Final prompts receive accepted evidence plus
  requirement/outcome summaries so partial answers can be cited honestly.
- Hardened retry and failure behavior: retry execution uses the persisted
  effective turn decision, advisory provider failures do not prevent local
  research state from being recorded, and public provider failure messages are
  bounded generic text rather than raw exception strings.
- Updated frontend/API chat traces with `turn_decision` handling and kept
  non-research decisions out of the visible research trace.
- Vector readiness was smoke-verified locally with the `local-hash` provider;
  operational readiness still depends on the running app's embedding provider,
  model, dimensions, and current local embedding rows matching.
- Verification completed: `ruff check wfrp_companion tests tools`; backend
  coverage gate with 721 tests at 100.00%; frontend Vitest coverage with 139
  tests passing; frontend production build. Independent agent review green-lit
  the PR after two rounds of fixes.

## 2026-06-09 Familiar Evidence-Gate Hardening Phase

- Implemented requirement-scoped evidence constraints for Familiar retrieval
  tools. Validation now checks checked-book scope, excluded subjects, subject
  identity, book/page hints, object-type hints, statline field sufficiency, and
  required terms before evidence can be accepted.
- Tightened structural evidence failure modes that caused wrong-source or
  wrong-entity answers: generic subjects such as `profile`/`stat block` fail
  closed, subjectless page evidence needs both book and page anchors,
  multi-word structural subjects must match as phrases, and object/book/page
  hints normalize common provider wording without becoming fuzzy matches.
- Kept rejected evidence out of final prompts and UI-facing citation payloads.
  Public traces now show candidate counts plus accepted/partial/rejected counts
  and reason counts, while accepted citations remain the only evidence list
  shown to the model and the UI.
- Added privacy-safe synthetic regressions for whole-library failure modes:
  career/profile false positives, wrong named entities, table/prose mentions
  without stat fields, heading-only matches, vector-only wrong-entity
  candidates, page/book hint mismatches, and scattered multi-word subjects.
- Independent reviewer follow-up found normalization and page-anchor edge
  cases; they were fixed and the final review green-lit the PR. Verification
  completed: backend 100% coverage gate with 680 tests at 100.00%; frontend
  Vitest coverage with 19 test files and 138 tests passing.

## 2026-06-09 Familiar Reasoning-Led Research Agent Phase

- Implemented provider-first Familiar research planning: no local retrieval
  tool runs until the provider returns one accepted strict public plan.
- Added durable `familiar_research_plans` storage plus plan/requirement links
  on tool calls and evidence judgments. Public trace reload now synthesizes
  research start, accepted plan, tool actions, evidence status, finalizing, and
  failures from persisted research rows.
- Replaced recovery-only behavior with a bounded provider-directed action loop.
  Every later tool action must name a known plan requirement, and
  `finish_research` can stop without another retrieval while preserving the
  accepted-evidence-only final answer contract. Review hardening now rejects
  multiple recovery tool calls, includes the accepted public plan/requirement
  ledger plus bounded requirement constraints in recovery prompts, and prevents
  `requirements_satisfied` from stopping a run when required plan requirements
  remain unsatisfied.
- Added requirement-aware evidence validation for included/excluded subject
  terms, statline evidence, broad topical/recommendation evidence, and
  requirement-linked judgment persistence. Required requirements are satisfied
  per requirement id and `min_accepted_hits`, not by aggregate evidence alone.
- Hardened hybrid diagnostics so vector status distinguishes `ran`,
  `ran_no_candidates`, `disabled`, `missing_embeddings`, `stale_embeddings`,
  and provider errors.
- Updated Familiar final prompts to include the public plan, requirement
  status, answer policy, accepted evidence, and insufficiency guidance without
  exposing hidden reasoning.
- Updated the Familiar UI/API surface so live streams and reloaded chat
  history show compact public research traces. Public metadata is now
  enum/count/id/status based before API/UI exposure, so resolved queries, plan
  summaries, tool purposes, local paths, PDF filenames, unknown raw tool
  arguments, and copied source text are not surfaced in trace metadata.
- Verification completed: `ruff check .`; backend 100% coverage gate with
  632 tests at 100.00%; frontend Vitest coverage above configured thresholds;
  frontend production build; Playwright e2e with 2 passing tests. Retrieval
  status curl against `127.0.0.1:8000` did not return JSON because no local API
  server was listening during verification.

## 2026-06-09 Familiar Tool-Calling Hybrid RAG

- Repaired a live Familiar follow-up failure where `give me there stats`
  could lose the active subject and, on weak evidence, surface a provider
  `previous_response_id` recovery error as generic research failure. Active
  stat follow-ups such as `give me the/their/there stats` now resolve to the
  current subject, and recovery planning stays stateless against OpenAI while
  carrying prior local tool outputs in the prompt. Verification for this repair:
  targeted regressions passed, assistant tests reported 161 passing, `ruff
  check .` passed, and the full backend coverage gate reported 563 passing with
  100.00% coverage.
- Overhauled Familiar from a one-shot retrieval answer path into a bounded
  tool-calling research agent. Runs now record research state, tool calls,
  retrieval attempts, diagnostics, evidence judgments, and accepted-evidence
  final citation runs.
- Familiar uses hybrid retrieval by default through backend tools: page FTS,
  source-object FTS, source-object fallback scan, current local vector
  candidates when embeddings are enabled, structured table/stat/source-object
  evidence, direct page lookup, direct source-object lookup, RRF fusion,
  deterministic reranking, and evidence validation.
- Added page-aware recovery for explicit page references, follow-up subject
  resolution through thread context, bounded retry/correction behavior when
  evidence is weak, and a final prompt contract that receives accepted
  evidence only.
- Added retrieval readiness visibility through `/api/retrieval/status` and
  `tools/rebuild_retrieval_assets.py`, keeping output count-only and avoiding
  raw book text, local model paths, or private PDF paths.
- Updated the wiki to reflect the current implementation and added a local
  process rule: do not use `multi_agent_v1.close_agent` while the agent
  lifecycle service is leaking completed threads. Fresh independent subagent
  review for this phase was blocked by that platform issue, so recovered prior
  reviewer findings were audited directly against the code with focused tests.
- Verification target for this phase: `ruff check .`, the full backend 100%
  coverage command including `tools.rebuild_retrieval_assets`, frontend
  Vitest, frontend coverage, frontend production build, and Playwright e2e.

## 2026-06-08 Stat-Line Retrieval Follow-Up

- Debugged the live `harpies stat line` failure. The previous sparse
  normalization fix handled `statblock` but not the common `stat line` wording.
- Root causes: `line` was counted as a content/entity term, page-level snippets
  could validate the wrong neighboring source object, wrong-titled sections
  could pass from incidental body overlap, and the actual Harpy Statistics
  fallback chunk carried only a tiny heading instead of nearby page context.
- Added `stat line`/`statline` query normalization that generates statistics,
  stat-block, and profile sparse candidates while only counting
  statistics/block as stat-line relevance terms.
- Tightened structural named-entity validation so titled source objects must
  match the requested entity through their own title/heading/object label;
  page chunks and table/table-row evidence can still use body context because
  their titles are often generic or row-local.
- Short `page_chunk` evidence now expands to a bounded page window around its
  stored character span, preserving prompt budgets while giving heading-only
  fallback chunks usable nearby context.
- Live QA now returns Old World Bestiary page 100 / Harpy Statistics as the
  only selected evidence item for `harpies stat line`. The local OCR text still
  appears incomplete for parts of the table, so Familiar should not invent
  missing stat cells.
- Verification run for this repair: retrieval tests reported 59 passing; the
  full backend coverage gate reported 503 tests passing with one existing
  Starlette/httpx deprecation warning and 100.00% coverage; `ruff check .`
  passed.

## 2026-06-08 Sparse Retrieval Query Normalization

- Repaired a live Familiar miss where `give me the statblock for gors` produced
  no retrieved evidence even though Old World Bestiary source objects contained
  the relevant Gor Statistics profile.
- Root cause: sparse retrieval searched literal compound/plural forms such as
  `statblock` and `gors`, while source-object FTS contained separated
  structural words and singular entity text such as `stat block` and `Gor`.
- Added bounded deterministic query normalization for sparse candidate
  generation: structural compounds such as `statblock` / `hit-location` are
  split, singular/plural alternatives are generated for FTS, and no
  creature-specific aliases are introduced.
- Added planner `match_terms` so deterministic reranking and page-to-object
  resolution use normalized structural intent without double-counting
  singular/plural variants as separate relevance concepts. Dense vector query
  text remains close to the user's original meaningful terms.
- Live QA against the latest thread's 13 checked books now returns Old World
  Bestiary page 84 / Gor Statistics as rank 1 for the original query.
- Verification run for this repair: retrieval tests reported 54 passing;
  the full backend coverage gate reported 496 tests passing with one existing
  Starlette/httpx deprecation warning and 100.00% coverage; `ruff check .`
  passed.

## 2026-06-08 Local Semantic Embeddings

- Upgraded the local vector retrieval channel from deterministic `local-hash`
  smoke vectors to a provider boundary with lazy Sentence Transformers support.
  The recommended real local semantic profile is
  `sentence-transformers` / `BAAI/bge-m3` / `1024` dimensions.
- Added migration `0006_embedding_provider_identity` so
  `book_retrieval_status` and `source_object_embeddings` are provider-aware.
  Rebuilds preserve other provider/model rows and only replace vectors for the
  active book/provider/model/dimensions.
- Added safe rebuild lifecycle behavior: jobs are claimed in short
  transactions, local inference runs outside write transactions, source-object
  snapshots are rechecked before final writes, source drift preserves existing
  rows and marks `needs_refresh`, and provider failures close the matching
  `ingest_jobs` row as failed with `completed_at`.
- Familiar now resolves the configured provider at query time, embeds queries
  locally, filters vector rows by checked-book currentness, uses resolved
  provider identity for SQL matching, and skips malformed vector rows or
  provider failures instead of failing the chat run.
- `/api/books` now exposes vector status, provider, and dimensions for Library
  status summaries, but intentionally does not expose `embedding_model` because
  user-configured Sentence Transformers models may be local filesystem paths.
- Independent review found and drove fixes for three high-risk failure paths:
  claimed rebuild jobs left running after provider inference failure,
  query-time provider failures bubbling into Familiar, and malformed vector
  blobs escaping scoring/currentness checks. CodeRabbit also caught raw config
  identity being used in vector SQL after provider resolution; this was fixed
  and covered.
- Verification run for this phase: `ruff check .` passed; full backend
  coverage reported 494 tests passing with one existing Starlette/httpx
  deprecation warning and 100.00% coverage; frontend coverage reported 132
  Vitest tests passing above configured thresholds; frontend production build
  passed with the existing large PDF worker chunk warning; final narrow agent
  review reported no findings.

## 2026-06-06 Follow-Up Retrieval Hang Repair

- Debugged a live Familiar turn where `aucassin is his name` appeared to hang.
  The backend eventually completed, but retrieval spent about 50 seconds before
  the model call because the history-aware planner expanded the short
  correction into a long query containing the previous assistant's wrong
  Black Orc/Career Compendium detour.
- Changed follow-up retrieval planning to use compact salient chat terms and
  skip failure-style assistant answers as retrieval-query context. The raw
  user message is still preserved separately in retrieval metadata.
- Tightened structural stat/table reranking so lexical candidates must match
  the named entity terms, not just object words like `stat block`. Typed
  stat/profile objects now outrank phrase-only sections for explicit stat
  requests, while table-row and chart retrieval stay covered.
- Stream interruption during an active Familiar run now marks the model run
  `failed` with `stream_interrupted` instead of leaving a stale `retrieving`
  run behind.
- Live checks after the fix reduced the Aucassin follow-up retrieval shape to
  compact Barony-scoped candidates, put the Barony Black Knight profile ahead
  of Black Orc/generic career stats, kept Gor Statistics first for Gors, and
  kept the Core Rules Hit Location table first for hit-location chart queries.
- Verification: `ruff check .` passed; the full backend coverage gate reported
  469 tests passing with one existing Starlette/httpx deprecation warning and
  100.00% coverage.

## 2026-06-06 Stat/Table Retrieval Repair

- Repaired Familiar stat-block/table retrieval after live QA showed missing
  Gor stats, missing hit-location chart output, and wrong stat-ish Black
  Knight context.
- Blocked structural query terms such as `block`, `stat`, `table`, and
  `chart` from fuzzy source-map expansion, preventing `stat block` queries
  from drifting into `black` results.
- Expanded deterministic source-object extraction for WFRP-style OCR layouts:
  pipe/percent stat profiles with main/secondary rows, range charts such as
  hit-location tables, OCR-normalized `Hit Location` table titles, and
  chart-searchable table/table-row text. The extractor version is now
  `structured-evidence-v4`.
- Updated deterministic reranking so table/chart and stat/profile requests get
  typed-evidence boosts after semantic acceptance, and inherited chapter
  headings/running headers can route candidates but cannot be the only reason
  multi-term entity evidence enters prompt context.
- Local maintenance rebuilt source objects for all 26 books with zero failures,
  refreshed source-object FTS/source maps, and left all 26 books indexed with
  current source maps. Live retrieval now returns `Old World Bestiary` Gor
  Statistics first for `give me the stat block for gors`, returns the Core
  Rules `Hit Location` table first for `can you give me the hit location
  chart`, and no longer includes the p45/p47 unrelated Black Knight
  wrong-stat sections.
- Verification run for this repair: full Python tests reported 461 tests
  passing with one existing Starlette/httpx deprecation warning and 100.00%
  coverage; `ruff check .` passed.

## 2026-06-06 Familiar Conversation Context

- Added bounded app-owned conversation context for Familiar in
  `wfrp_companion/assistant/conversation_context.py`. Prompt history now uses
  only prior completed logical turns from the same thread, while failed,
  active, and current user messages are excluded.
- Added history-aware retrieval planning for follow-up/reference-resolution
  queries. Self-contained queries stay unchanged; follow-ups store the raw user
  message separately from the planned retrieval query and history metadata in
  `retrieval_runs.metadata_json`.
- Kept chat history out of the evidence layer. Recent chat can clarify user
  intent, but source maps, candidates, reranking, prompt evidence, metadata,
  and citations remain scoped to the current checked-book snapshot.
- Disabled provider-side persistence by sending OpenAI Responses API calls with
  `store=False` and no provider conversation chaining.
- Updated the chat read model and frontend history drawer so saved threads load
  logical turns, successful retries replace failed visible turns, and streaming
  updates target the correct `model_run.id`.
- Independent review found edge cases in prompt-history turn limits, retrieval
  history metadata, stale failed-run retryability after completed retries,
  frontend stream targeting, and over-broad follow-up detection. All were fixed
  with focused regressions before final verification.
- Follow-up live-data fix: source-object replacement now detaches and dedupes
  historical retrieval hits before old source objects are deleted, preventing
  same-run/page fallback uniqueness collisions during re-extraction. The
  extractor also gives overlapping equivalent rule sections unique stable IDs,
  fixing the Tome of Salvation duplicate-ID failure.
- Local maintenance after the fix extracted/indexed all 26 books, rebuilt
  source maps for all 26 books, and restored Children of the Horned Rat as the
  top source for live `skaven` retrieval.
- Verification run for this pass: full Python tests reported 454 tests passing
  with one existing Starlette/httpx deprecation warning and 100.00% coverage;
  `ruff check .` passed; frontend coverage reported 131 Vitest tests passing
  above configured thresholds; frontend production build passed with the
  existing large PDF worker chunk warning; Playwright e2e reported 2 tests
  passing with the existing `NO_COLOR`/`FORCE_COLOR` warnings.

## 2026-06-06 Printed Page-Label Calibration/Backfill

- Added migration `0005_page_label_calibration` to create
  `book_page_label_calibrations` and allow
  `ingest_jobs(job_type='backfill_page_labels')` in existing databases and the
  fresh schema.
- Added `wfrp_companion/library/page_labels.py` and
  `tools/backfill_page_labels.py` for count-only printed page-label
  calibration/backfill from imported page labels plus optional offset anchors.
  Anchors preserve roman/front-matter labels before the anchor, and plain
  reruns reuse stored anchors after page text/label snapshot drift unless
  `--force` or a new anchor is supplied.
- Exact search, Familiar source-object/page fallback candidates, prompt
  context, and stored/reloaded chat citations now use strict printed
  label/range helpers. Missing labels and conflicting manual-review pages do
  not become confident `printed page(s)` labels; `pdf_page_number` remains the
  reader jump coordinate.
- Independent review found three issues: anchored calibrations could still be
  overwritten by plain reruns after snapshot drift, source-object/linked-page
  evidence could invent printed ranges from PDF page numbers, and conflicting
  manual-review labels could still be returned as confident labels. All were
  fixed with regressions.
- Verification run for this pass: focused page-label/retrieval/chat/search/tool
  tests reported 109 tests passing; full Python tests reported 436 tests
  passing with one existing Starlette/httpx deprecation warning and 100.00%
  coverage; `ruff check .` passed; `git diff --check` passed; frontend
  Vitest reported 127 tests passing; frontend coverage passed above configured
  thresholds; frontend production build passed with the existing large PDF
  worker chunk warning; Playwright e2e reported 2 tests passing with the
  existing `NO_COLOR`/`FORCE_COLOR` warnings.

## 2026-06-05 Structured Source-Object Evidence

- Added migration `0004_structured_evidence` to widen
  `source_objects.object_type` with `glossary_entry` and
  `source_object_links.link_type` with `glossary_definition`.
- Extended deterministic source-object extraction with conservative
  plain-text heuristics for pipe tables, table rows, stat/profile blocks,
  index entries, glossary entries, and cross references. Extractor output
  remains local/count-oriented and tests use synthetic non-WFRP fixtures.
- `replace_book_source_objects()` now persists derived
  `source_object_links` for table rows, stat/profile relationships, and
  deterministic same-book index/glossary/cross-reference targets, and records
  table/stat/location counts in `book_object_status`.
- Familiar evidence resolution now follows checked-scope links from table rows,
  stat blocks, and index/cross-reference entries to complete parent/target
  source objects. Glossary entries remain canonical glossary evidence and can
  include linked target context. Link traversal is constrained to the checked
  `source_book_ids` snapshot.
- Rank-fusion dedupe now preserves linked-evidence rank reasons so selected
  hits remain auditable after parent/target evidence is merged.
- Independent review found four issues: old extraction status needed a durable
  extractor-version invalidation path, duplicate same-page table-row text could
  collide on deterministic IDs, page-only reference links were not followed at
  runtime, and glossary linked context could create misleading disjoint page
  ranges. All were fixed with regressions; final follow-up review found no
  remaining code issues.
- Verification run for this pass: full Python tests reported 394 tests passing
  with one existing Starlette/httpx deprecation warning and 100.00% coverage;
  `ruff check .` passed; `git diff --check` passed; frontend Vitest reported
  127 tests passing; frontend coverage passed above configured thresholds;
  frontend production build passed with the existing large PDF worker chunk
  warning; Playwright e2e reported 2 tests passing.

## 2026-06-05 Local Vector Retrieval Channel

- Added migration `0003_vector_retrieval` and the
  `source_object_embeddings` table for SQLite-local source-object vectors.
- Added disabled-by-default embedding configuration:
  `WFRP_EMBEDDING_PROVIDER`, `WFRP_EMBEDDING_MODEL`, and
  `WFRP_EMBEDDING_DIMENSIONS`. The only implemented provider is local
  deterministic `local-hash`; no hosted vector service is called.
- Added `wfrp_companion/source_objects/embeddings.py` and
  `tools/rebuild_embeddings.py` to rebuild local vector blobs from current
  `source_objects` with `ingest_jobs(job_type='rebuild_embeddings')`,
  `book_retrieval_status.vector_status`, snapshot invalidation, stale-running
  recovery, and count-only CLI output.
- Added vector candidate generation in `wfrp_companion/assistant/candidates.py`
  as one more candidate channel before RRF and deterministic reranking. Vector
  candidates are filtered to the checked `book_id` snapshot and only used for
  books whose embedding snapshot is current.
- Independent review found three issues: malformed embedding rows could cross
  scope if `source_object_embeddings.book_id` disagreed with
  `source_objects.book_id`, existing `0002` databases needed pending
  migrations before the new job type was used, and vector query-time currentness
  needed to prove the embedding snapshot. All were fixed with regressions;
  follow-up review reported no findings, and CodeRabbit reported 0 issues.
- Verification run for this pass: focused changed-module coverage reported 73
  tests passing with 100.00% coverage; full Python tests reported 372 tests
  passing with one existing Starlette/httpx deprecation warning and 100.00%
  coverage; `ruff check .` passed; `git diff --check` passed; frontend Vitest
  reported 127 tests passing; frontend coverage passed above configured
  thresholds; frontend production build passed with the existing large PDF
  worker chunk warning; Playwright e2e reported 2 tests passing.

## 2026-06-05 Retrieval Rank Fusion And Reranker Protocol

- Added reciprocal rank fusion to Familiar retrieval candidates before final
  reranking. Page FTS, source-object FTS, and fallback object scans remain
  candidate channels; they do not decide final prompt evidence on their own.
- Added the `Reranker` protocol and `DeterministicReranker` default in
  `wfrp_companion/assistant/reranking.py`, keeping provider-backed reranking
  out of the current phase while making the interface replaceable.
- Rank reasons for selected hits now include channel-rank contributions
  (`fusion_channel:*`), total RRF contribution (`fusion:rrf=*`), deterministic
  reranker acceptance, and deterministic reranker score. These are persisted in
  `retrieval_hits.rank_reasons_json`.
- The deterministic reranker now rejects weak lexical-only matches for
  multi-term queries while preserving exact object/table lookup signals,
  including cases where the only table/stat/profile cue is the source-object
  `object_type`.
- Independent review initially found two ranking issues: object-type table
  candidates could be rejected by the semantic gate, and same-channel duplicate
  candidates could inflate RRF rank positions. Both were fixed with regression
  tests; follow-up review reported no findings.
- Verification run for this pass: focused retrieval coverage reported 27 tests
  passing with 100.00% coverage; full Python tests reported 350 tests passing
  with one existing Starlette/httpx deprecation warning and 100.00% coverage;
  `ruff check .` passed; `git diff --check` passed; frontend Vitest reported
  127 tests passing; frontend coverage passed above configured thresholds;
  frontend production build passed with the existing large PDF worker chunk
  warning; Playwright e2e reported 2 tests passing.

## 2026-06-05 Source-Object Search Backfill

- Added `rebuild_source_object_search()` in
  `wfrp_companion/source_objects/store.py` to rebuild
  `source_object_search` and `source_object_search_fts` from existing
  `source_objects` without rerunning extraction.
- Added `tools/rebuild_source_object_fts.py` as a count-only local repair tool
  for missing or stale source-object search projections.
- The backfill uses `ingest_jobs(job_type='rebuild_source_object_fts')`,
  stale-running recovery, claim-conflict failure reporting, and
  `book_object_status` transitions to keep object-search readiness explicit.
- Review fixes strengthened idempotent skip behavior so stale FTS indexes and
  failed/stale `book_object_status` rows are repaired instead of reported as
  current.
- Verification run for this pass: focused store/tool coverage reported 27 tests
  passing with 100.00% coverage; post-review focused coverage reported 29
  tests passing with 100.00% coverage; final focused coverage reported 31 tests
  passing with 100.00% coverage after FTS vocabulary/rowid validation was
  added; object-type posting validation brought final focused coverage to 32
  tests passing with 100.00% coverage; full Python tests reported 345 tests
  passing with one existing
  Starlette/httpx deprecation warning and 100.00% coverage;
  `ruff check .` passed; frontend Vitest reported 127 tests passing; frontend
  coverage passed above configured thresholds; frontend production build passed
  with the existing large PDF worker chunk warning; Playwright e2e reported 2
  tests passing.

## 2026-06-05 Durable Source-Map Retrieval Ownership

- Added migration `0002_source_map_retrieval` for
  `book_retrieval_status`, `book_source_maps`, and
  `retrieval_run_source_books`.
- Added `wfrp_companion/source_objects/source_map_builder.py` and
  `tools/rebuild_source_maps.py` so source-map/profile metadata is rebuilt from
  current source objects with guarded jobs, stale-running recovery, count-only
  output, and deterministic freshness snapshots.
- Updated Familiar source-map loading so checked books use current durable
  `book_source_maps` when available and safely fall back to dynamic checked-book
  source maps when durable rows are missing, stale, or malformed.
- Updated retrieval-run persistence to snapshot checked books into
  `retrieval_run_source_books` as relational proof of Library checkbox scope.
- Addressed independent review findings around claim-conflict failure
  accounting, source-map freshness inputs, durable source-map loading, and
  malformed durable-map fallback.
- Verification run for this pass: focused changed-module coverage reported 61
  tests passing with 100.00% coverage; full Python tests reported 325 tests
  passing with one existing Starlette/httpx deprecation warning and 100.00%
  coverage; `ruff check .` passed; frontend Vitest reported 127 tests passing;
  frontend coverage passed above configured thresholds; frontend production
  build passed with the existing large PDF worker chunk warning; Playwright e2e
  reported 2 tests passing.

## 2026-06-05 Retrieval Module Split

- Split the Familiar retrieval implementation into focused modules while
  keeping `wfrp_companion/assistant/retrieval.py` as the public compatibility
  facade for `retrieve_context()` and existing tests/callers.
- Added `source_map.py`, `query_planner.py`, `candidates.py`, `evidence.py`,
  and `reranking.py` under `wfrp_companion/assistant/` so later retrieval
  phases can add durable source maps, rank fusion, vector candidates, and typed
  evidence without growing one monolithic module.
- Added `tests/assistant/test_retrieval_module_contracts.py` to lock facade
  re-exports to the focused module contracts.
- Completed independent code review for the split with no blocking findings.
- Verification run for this pass: focused retrieval/chat tests reported 39
  tests passing; full Python tests reported 300 tests passing with one
  existing Starlette/httpx deprecation warning; the backend coverage gate
  reported 300 tests passing with 100.00% coverage; `ruff check .` passed;
  frontend Vitest reported 127 tests passing; frontend coverage passed above
  configured thresholds; frontend production build passed with the existing
  large PDF worker chunk warning; Playwright e2e reported 2 tests passing.

## 2026-06-05 Source-Map-Aware Familiar Retrieval Slice

- Changed Familiar retrieval so new model runs resolve checked books from the
  thread's active source set at message time. `chat_thread_source_books` remains
  a historical thread-creation snapshot; `retrieval_runs.metadata_json` now
  stores the per-run checked-book snapshot, compact source map, and candidate
  list.
- Added source-object search projection population during extraction:
  `source_object_search`, `source_object_search_fts`, and
  `book_object_status.status='indexed'` now represent searchable extracted
  objects.
- Added broad page/object candidate generation, source-object span resolution,
  deterministic semantic reranking, rank-reason snapshots, source-map prompt
  injection, and printed page-range citation labels for Familiar.
- Verification for this pass: full Python tests reported 290 tests passing;
  the backend coverage gate reported 298 tests passing with 100.00% coverage;
  both Python runs had one existing Starlette/httpx deprecation warning;
  `ruff check .` passed; frontend Vitest reported 127 tests passing; frontend
  coverage passed above configured thresholds; frontend production build
  passed with the existing large PDF worker chunk warning; Playwright e2e
  reported 2 tests passing.

## 2026-06-05 Retrieval Architecture Handoff

- Added
  `docs/handoffs/2026-06-05-source-map-hybrid-retrieval-handoff.md` as the
  durable handoff for the next retrieval phase.
- Captured the target direction as source-map-aware hybrid retrieval with
  semantic reranking and section-aware evidence, combining exact FTS, future
  vector search, source-object search, glossary/index routing, query rewriting,
  rank fusion, and semantic relevance filtering.
- Preserved the key user-observed requirements: Library checkboxes must gate
  Familiar prompt/retrieval scope per message, lexical hits must be semantically
  judged before entering context, topics must resolve to multi-page
  source-object spans when needed, and UI citations/search results should show
  printed page labels rather than raw PDF page numbers.

## 2026-06-05 Library Bulk Toggle Refinement

- Removed per-book readiness words from the Library book selector so rows show
  the book title, source-set checkbox, and compact Grimoire open action without
  repeated `ready` noise.
- Added tri-state category-heading checkboxes to select or clear every visible
  book in a Library category. The bulk control persists changes through the
  same per-book source-set endpoint as individual checkboxes.
- Verification run for this pass: focused Library tests reported 9 tests
  passing, frontend coverage reported 127 Vitest tests passing above configured
  thresholds, frontend production build passed, and Playwright e2e reported 2
  tests passing.

## 2026-06-05 Search/Citation Page Drift And Familiar Rendering Fix

- Split search hits and chat citations into explicit PDF jump metadata:
  `pdf_page_number` plus optional `page_label`, while preserving the existing
  `page_number` compatibility field.
- Changed `/api/search/exact`, Familiar retrieval, stored chat citation read
  models, and frontend API types so Search and Familiar open Grimoire using the
  PDF page number instead of inferring from display text.
- Search result opens and Familiar citation opens now force Grimoire back to
  single-page mode so an existing two-page spread cannot make the reader appear
  one page behind the clicked citation.
- Updated search result labels and citation buttons to say `PDF page N`, with
  `(printed page X)` appended when a distinct `pages.page_label` is available.
- Added safe Familiar markdown rendering for headings, paragraphs, lists,
  tables, bold text, and inline code so streamed model output no longer appears
  as one unreadable text blob.
- Updated `tools/extract_page_text.py` and
  `wfrp_companion/library/page_text_importer.py` so page labels from JSON or
  managed PDFs are preserved in SQLite `pages.page_label`; label-only drift now
  causes page-text import freshness checks to fail rather than silently
  skipping stale rows.
- Verification run for this pass: backend coverage reported 286 tests passing
  with 100% coverage, `ruff check .` passed, frontend Vitest reported 125 tests
  passing with coverage above configured thresholds, frontend production build
  passed, Playwright e2e reported 2 tests passing, `git diff --check` passed,
  and a live browser smoke check opened an exact-search result into Grimoire at
  PDF page 134 in single-page mode.

## 2026-06-05 Phase 7 Deterministic Source Object Extraction Foundation

- Added `wfrp_companion/source_objects/layout.py`,
  `wfrp_companion/source_objects/store.py`,
  `wfrp_companion/source_objects/extractor.py`, and
  `tools/extract_source_objects.py`.
- Implemented deterministic source-object extraction over copied,
  text-imported, exact-search-indexed books.
- Added per-book text snapshot hashing, explicit `book_object_status`
  lifecycle updates, idempotent `extract_source_objects` ingest jobs,
  stale-running recovery, and failure recording.
- Added PyMuPDF layout metadata loading with safe fallback when managed PDFs
  are missing or unreadable.
- Added heading-derived `rule_section` extraction and lower-confidence
  `page_chunk` fallback extraction for pages/regions not covered by rule
  sections.
- Kept object IDs stable by using page-local title-bucket ordinals plus
  normalized text hashes, including a regression for unrelated earlier
  same-page heading insertion.
- Ran a live private smoke check for one indexed book: 738 source objects were
  written on the first run and the same book was skipped as current on rerun.
  No private extracted text was committed or logged in wiki output.
- Completed independent review, fixed the reported same-page ID churn issue,
  and reran verification.
- Verification run for this pass: focused source-object/tool tests reported 30
  tests passing, backend coverage reported 283 tests passing with 100%
  coverage, `ruff check .` passed, frontend Vitest reported 122 tests passing
  with coverage above configured thresholds, frontend production build passed,
  and Playwright e2e reported 2 tests passing.
- Important boundary: object FTS, table/stat/location extraction, and Familiar
  object-aware ranking remain later Phase 7 PRs.

## 2026-06-05 Phase 7 Typed Source Object Schema Foundation

- Added the Phase 7 implementation plan at
  `docs/plans/2026-06-05-phase-7-typed-source-object-retrieval-implementation-plan.md`.
- Added `schema_migrations` plus `wfrp_companion/db/migrations.py` and
  `tools/migrate_db.py` for explicit local SQLite migrations.
- Added the Phase 7 source-object schema foundation:
  `source_objects`, `source_object_links`, `book_object_status`,
  `book_query_profiles`, `source_object_search`, and
  `source_object_search_fts`.
- Updated `retrieval_hits` so future retrieval can cite typed source objects
  while preserving legacy page-level hits as `page_fallback` snapshots.
- Added `wfrp_companion/source_objects/models.py` with typed source-object
  contracts and deterministic IDs that hash normalized text rather than raw OCR
  whitespace.
- Hardened migration safety after independent review: missing/uninitialized DB
  paths are refused, duplicate legacy retrieval ranks are preflighted, DDL runs
  inside a rollbackable transaction, and `schema_migrations` is recorded only
  after all migration work succeeds.
- Added migration, rollback, CLI, schema, source-object, chat, retrieval, and
  frontend regression coverage.
- Verification run for this pass: backend coverage gate reported 253 tests
  passing with 100% coverage, `ruff check .` passed, frontend Vitest reported
  122 tests passing with coverage above configured thresholds, frontend
  production build passed, and Playwright e2e reported 2 tests passing.
- Important boundary: Phase 7 PR1 is schema/model/migration foundation only.
  It does not yet extract source objects or change Familiar retrieval ranking.

## 2026-06-05 Phase 6 Familiar Streaming RAG Chat

- Added the Phase 6 implementation plan at
  `docs/plans/2026-06-05-phase-6-familiar-rag-chat-implementation-plan.md`.
- Added `tools/dev.py` as a one-command local runner for FastAPI plus Vite,
  with readiness probes and cleanup behavior covered by tests.
- Added `chat_thread_source_books` and `model_runs` to the SQLite schema so
  chat retrieval scope and model lifecycle state are app-owned and explicit.
- Added `wfrp_companion/assistant/chat_store.py`,
  `retrieval.py`, `prompts.py`, `provider.py`, and `chat_service.py` for
  thread snapshots, exact-search retrieval, bounded prompt construction,
  OpenAI Responses API streaming, and model-run completion/failure handling.
- Added `/api/chat/*` routes, including
  `POST /api/chat/threads/{thread_id}/messages/stream`, which returns
  newline-delimited JSON events: `accepted`, `retrieval`, `delta`,
  `completed`, and `failed`.
- Updated the Familiar frontend panel to create a thread, stream assistant
  deltas, show failed provider runs, and open cited PDF pages in Grimoire.
- Added `openai` to `environment.yml`; the API key remains local in
  `OPENAI_API_KEY` and is never exposed to the browser or stored in the repo.
- Verification run for this pass: backend pytest reported 205 tests passing,
  frontend Vitest reported 109 tests passing, `ruff check .` passed,
  frontend production build passed, and targeted coverage gates reported 100%
  for `wfrp_companion.assistant.chat_service` and
  `wfrp_companion.assistant.provider`.
- Follow-up reconciliation on 2026-06-05 marked the Phase 6 plan checklist
  against live code. The remaining known Phase 6 gaps are the real Familiar
  chat-history selector UI and a successful live OpenAI rules-question QA pass;
  the attempted live rules question exposed the page-level retrieval weakness
  now being addressed by Phase 7 typed source-object retrieval.

## 2026-06-04 Phase 5 Browser GUI Refinement

- Refined the first browser GUI around the user-approved workspace language:
  `Library`, `Grimoire`, and `Familiar`.
- Moved Grimoire page/zoom/view controls into the panel header, centered them
  in the header, and kept previous/next page movement as minimal side controls
  beside the PDF viewport.
- Added single-page/two-page Grimoire view mode. Two-page mode shows pages 1
  and 2 alone, then pairs pages from 3/4 onward, with an unpaired final page
  shown alone.
- Changed Grimoire source tabs to show source titles only, placed close controls
  visually inside the tabs, and kept close controls outside the semantic
  `tablist` while sharing the tab strip scroll layer.
- Changed Library/Search open actions to compact book-icon buttons.
- Moved the Familiar history hamburger into the panel header, removed the
  duplicate internal chat header, and positioned the send action inside the
  lower-right corner of the message text field.
- Added tests for the refined panel labels, header controls, PDF tab labels,
  two-page spread math, clamped PDF page behavior, compact open actions, and
  Familiar composer layout.
- Completed independent review, fixed the reported tab-scroll and out-of-range
  PDF page consistency issues, then reran the frontend gate: 106 Vitest tests
  passed with 100% statements / branches / functions / lines coverage,
  production build passed, Playwright e2e passed, and `git diff --check` was
  clean.

## 2026-06-04 Phase 5 Browser GUI Shell

- Added the Phase 5 implementation plan at
  `docs/plans/2026-06-04-phase-5-browser-gui-shell-implementation-plan.md`.
- Added the first committed browser GUI under `frontend/` using React, Vite,
  TypeScript, Vitest, Playwright, PDF.js, and lucide icons.
- Added `GET /api/books/{book_id}/pages/{page_number}/text` so the GUI can
  lazily load full imported page text from SQLite without reading ignored JSON
  files or exposing local filesystem paths. The endpoint is guarded by
  `book_readiness.search_ready`.
- Added a dockable three-panel workspace with collapsible/resizable/maximizable
  Library/Search, PDF Reader, and Agent Chat panels.
- Added Library/Search tabs with grouped source-set book checkboxes, collapsible
  categories, exact-search results, full-page text expansion, and `Open PDF page`
  actions.
- Added multi-source PDF reader tabs over the existing managed PDF endpoint,
  with page navigation, zoom controls, PDF.js canvas rendering, retry handling,
  stale-render cancellation, and accessible tab/panel wiring.
- Added keyboard-resizable panel splitters with vertical separator ARIA
  metadata.
- Added a UI-only agent chat shell with scrollable transcript, controlled
  composer, and chat-history popover. Real AI/RAG behavior remains deferred to a
  later phase.
- Copied the current UI banner into the frontend public asset pipeline at
  `frontend/public/assets/buttlordxai-hero.png`.
- Added frontend unit, coverage, build, and Playwright e2e verification.
  Backend verification reported 181 tests passing with 100% coverage; frontend
  verification reported 74 Vitest tests passing, 100% statement/line/function
  coverage, a successful production build, and one browser e2e test passing.
- Completed independent implementation review, fixed the reported important
  workspace-storage/PDF/chat issues, then fixed the remaining ARIA tab/popover
  follow-ups before this wiki refresh.

## 2026-06-04 Phase 4 Local Backend API

- Added the Phase 4 implementation plan at
  `docs/plans/2026-06-04-phase-4-local-backend-api-implementation-plan.md`.
- Added the FastAPI app factory under `wfrp_companion/api/`, plus
  `tools/serve_api.py` for starting the local API with Conda-managed Python.
- Added `wfrp_companion/library/catalog.py` as the read model for book lists,
  book detail, page references, and guarded managed-PDF reader paths.
- Added `/api/books`, `/api/books/{book_id}`,
  `/api/books/{book_id}/pages/{page_number}`, and
  `/api/books/{book_id}/pdf`. The PDF endpoint serves managed local PDFs
  inline with HTTP range support and rejects unavailable, missing, or unsafe
  managed paths.
- Added `/api/source-sets`, `/api/source-sets/active`, and per-book
  source-set toggle routes over the existing SQLite-backed source-set service.
- Added `wfrp_companion/search/scope.py` so the CLI and API share active
  source-set, named source-set, per-book, and whole-library scope resolution.
- Added `/api/search/exact`, which returns query metadata, resolved scope,
  snippets, and book/page citations while preserving search-readiness gating.
- Added regression coverage for API startup, health, OpenAPI route presence,
  catalog routes, PDF range/path-safety responses, source-set routes,
  exact-search routes, shared scope resolution, API error mapping, and the
  `tools/serve_api.py` entrypoint.
- Ran the full coverage gate across `wfrp_companion` and tracked tool modules:
  178 tests passed with 100% coverage. `ruff check .` also passed.

## 2026-06-04 Phase 3 Source Sets And Search Scoping

- Added the Phase 3 implementation plan at
  `docs/plans/2026-06-04-phase-3-source-sets-implementation-plan.md`.
- Added `wfrp_companion/library/source_sets.py` as the SQLite-backed owner for
  source-set sync, active source-set selection, and per-book enablement.
- Added `tools/source_sets.py` with `init`, `list`, `books`, `activate`,
  `enable`, and `disable` commands.
- Created the built-in `rules-core` / `Rules/Core` source set over the real
  local library: 26 book rows were inserted, the source set was made active,
  core/GM essentials and rules/mechanics books were enabled by default, and
  adventure/world books were left disabled.
- Updated `tools/search_text.py` so exact search uses the active source set by
  default, supports `--source-set`, keeps direct `--book-id` filters, and uses
  `--all-books` as the explicit whole-library override.
- Kept the ownership boundary explicit: `source_set_books.enabled` controls
  scope membership, while `books.copy_status`, `books.text_status`,
  `books.search_status`, `book_readiness`, and `search_exact()` control search
  readiness.
- Added regression coverage for source-set bootstrap/idempotency/conflicts,
  malformed active settings, per-book toggles, source-set CLI behavior, active
  source-set search defaults, whole-library override behavior, and enabled but
  not-indexed books being suppressed by search readiness.
- Ran the full coverage gate across `wfrp_companion` and tracked tool modules:
  146 tests passed with 100% coverage. `ruff check .` also passed.
- Completed independent implementation review, fixed the reported source-set
  membership/readiness boundary issue, and received code green-light pending
  this wiki refresh.

## 2026-06-04 Page Text Import And Global FTS Search

- Added the execution plan at
  `docs/plans/2026-06-04-page-text-import-global-fts-implementation-plan.md`.
- Added `wfrp_companion/library/page_text_importer.py` and
  `tools/import_page_text.py` to import ignored private
  `data/page_text/<book_id>.json` files into SQLite `pages` and `page_text`.
- Added `wfrp_companion/search/fts.py`, `tools/rebuild_fts.py`, and
  `tools/search_text.py` for a whole-library SQLite FTS5 projection over
  copied, text-imported books.
- Kept per-book lifecycle ownership explicit through `books.text_status`,
  `books.search_status`, and idempotent `ingest_jobs` keys for
  `import_page_text` and `rebuild_fts`.
- Ran the real local import and search pipeline: 26 books imported from
  page-text JSON, 3,736 pages imported, 26 books indexed, 3,736 pages indexed,
  and exact search returned cited book/page hits.
- Added regression coverage for idempotent import, failed import repair,
  malformed JSON quarantine, same-key running job protection, stale job
  recovery, stale FTS projection cleanup, readiness-gated search, per-book
  filters, and CLI entrypoints.
- Ran the full coverage gate across `wfrp_companion` and tool modules: 120
  tests passed with 100% coverage. `ruff check .` also passed.
- Completed independent implementation review and fixed the reported P1/P2
  issues before this wiki refresh.

## 2026-06-04 Phase 2 Managed PDF Library Import

- Added the Phase 2 implementation plan at
  `docs/plans/2026-06-04-phase-2-managed-pdf-library-import-implementation-plan.md`.
- Accepted ADR `docs/adr/0002-managed-local-pdf-storage.md` for local managed
  PDF copies, absolute `books.managed_pdf_path`, and versioned
  `source-<original_sha256>.pdf` filenames.
- Added `wfrp_companion/library/` with identity, discovery, storage, and
  importer modules for local managed PDF import.
- Added `tools/import_pdfs.py`, which imports all readable PDFs from the
  configured source root, validates the root before initializing SQLite, and
  reports copy/failure summaries without printing book text.
- Ran the importer against `/Users/aftoncarlson/TTRPGs/WFRP 2e`: 26 candidates,
  26 copied, 0 failed. A rerun reported 26 skipped current, confirming
  idempotency.
- Added tests for book/folder identity, recursive PDF discovery, atomic managed
  copy storage, SQLite import state, collision/failure reporting, stale job
  recovery, and CLI behavior.
- Updated `.gitignore` to scope local data ignores to repo-root paths so
  `wfrp_companion/library/` and `tests/library/` can be tracked while generated
  `data/` remains ignored.

## 2026-06-03 Phase 1 SQLite Foundation

- Added the durable implementation plan at
  `docs/plans/2026-06-03-local-reference-library-implementation-plan.md`.
- Added the first app package under `wfrp_companion/`.
- Added config loading in `wfrp_companion/config.py` for `WFRP_PDF_ROOT`,
  `WFRP_DATA_DIR`, `WFRP_DB_PATH`, and `WFRP_ASSET_DIR`.
- Added SQLite connection/schema initialization in
  `wfrp_companion/db/connection.py` and `wfrp_companion/db/schema.sql`.
- Added `tools/init_db.py`, which works both as `python tools/init_db.py` and
  as an imported CLI main.
- Expanded `environment.yml` with FastAPI, Uvicorn, Pillow, OpenCV, ImageHash,
  and pytest-cov for planned API/image work and coverage enforcement.
- Added `tests/db/test_schema.py` with 100% coverage over the new Python
  package and init CLI.
- Updated `.gitignore` to keep `.coverage*` out of Git.

## 2026-06-03 Page Text OCR Extraction

- Added `tools/extract_page_text.py` to produce private local page-level text
  references under ignored `data/page_text/`.
- Added Tesseract to `environment.yml` and updated the Conda environment.
- Ran full extraction for `/Users/aftoncarlson/TTRPGs/WFRP 2e`: 26 books,
  3,736 page records, 15,612,529 characters, 2,668,305 words, 391 embedded-text
  pages, 3,214 OCR pages, 131 empty OCR pages, and 0 OCR errors.
- Recorded the count-only run summary in
  `docs/audits/2026-06-03-page-text-ocr-extraction.md`.

## 2026-06-03 PDF Extraction Audit

- Added `tools/pdf_audit.py` to audit PDF extraction quality without saving
  extracted book text.
- Ran the audit against `/Users/aftoncarlson/TTRPGs/WFRP 2e`.
- Recorded summary findings in
  `docs/audits/2026-06-03-pdf-extraction-audit.md`: 26 PDFs, 3,736 pages, 2
  PDFs with useful embedded text, and 24 likely image/scanned PDFs that need
  OCR strategy before reliable search/RAG ingestion.

## 2026-06-03 UI Hero Asset

- Added the generated pixel-art UI banner at `assets/ui/buttlordxai-hero.png`.
- Replaced the initial banner source with
  `/Users/aftoncarlson/Downloads/Gemini_Generated_Image_4dky2p4dky2p4dky (1).png`
  while keeping the app-facing asset path stable.
- Replaced the banner again with
  `/Users/aftoncarlson/Downloads/Gemini_Generated_Image_yu4cwbyu4cwbyu4c.png`,
  still keeping the same app-facing path.
- Replaced the banner again with
  `/Users/aftoncarlson/Downloads/Gemini_Generated_Image_xipclexipclexipc-clean.png`,
  still keeping the same app-facing path.
- Added `assets/ui/README.md` to record source path, dimensions, format, and
  intended usage.
- Updated UI/UX and local tooling wiki topics to treat `assets/ui/` as the
  repo-owned source asset location until a frontend asset pipeline exists.

## 2026-06-03 Conda Python Tooling

- Accepted Conda as the canonical Python package manager for the project.
- Added `environment.yml` with Python 3.12, PyMuPDF, Poppler, pytest, and ruff.
- Added ADR `docs/adr/0001-conda-python-tooling.md`.
- Updated local tooling, target architecture, PDF ingestion, implementation
  standards, and testing topics to use the `wfrp-companion` Conda environment.

## 2026-06-03 Initial Development Scaffold

- Created root agent guidance in `CLAUDE.md` and `AGENTS.md`.
- Added the initial wiki navigation layer: `CONTEXT.md`, `INDEX.md`,
  `schema.md`, and this log.
- Added initial topic pages for project overview, target architecture, PDF
  ingestion, AI/RAG, UI/UX, local tooling, implementation standards, and tests.
- Added concepts for the private copyright boundary and hybrid search strategy.
- No application code exists yet; these pages describe the intended development
  system and MVP architecture.
