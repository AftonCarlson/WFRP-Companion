# AI RAG System

## Retrieval Strategy

[coverage: high]

WFRP rules lookup needs hybrid retrieval:

- Full-text search for exact rule names, talents, careers, spells, locations,
  NPC names, table labels, and page references.
- Vector search for natural-language questions and fuzzy conceptual lookup.
- Reranking or score blending so exact matches are not buried by semantic
  matches.

Vector search alone is not enough for rules-heavy material.

Phase 6 added deterministic local exact search first:

- New chat threads snapshot enabled books into `chat_thread_source_books`.
- Retrieved pages are recorded in `retrieval_runs` and `retrieval_hits` before
  the provider call.
- Streaming chat events include citations that can open the exact PDF page in
  Grimoire.
- Chat citation payloads carry `pdf_page_number` for the Grimoire jump target
  and optional `page_label` for printed-page context. Frontend code must not
  infer a PDF jump target from citation display text.

Vector retrieval remains future work and should layer onto this explicit
source-set and citation contract rather than replacing it.

Phase 7 PR1 adds the typed source-object storage foundation that later
retrieval phases will use:

- `source_objects` is the future canonical table for typed evidence such as
  `rule_section`, `table`, `table_row`, `stat_block`, `npc_profile`,
  `monster_profile`, `location_description`, `boxed_text`, `map_reference`,
  and `image_reference`.
- `source_object_links` is the future app-owned relationship table for index
  entries, cross references, table rows, stat/profile links, map/image
  references, and entity mentions.
- `book_object_status` will own the extraction/index lifecycle per book.
- `book_query_profiles` will store deterministic per-book query-type boosts
  such as rules, tables, NPCs, monsters, locations, adventure scenes, lore, and
  source navigation.
- `source_object_search` and `source_object_search_fts` are rebuildable
  projections, not canonical text storage.
- `retrieval_hits` now has its own `id`, optional `source_object_id`, and
  snapshot fields for object type, title, heading path, confidence, rank
  reasons, text snapshot hash, and metadata. Legacy page hits migrate as
  `page_fallback` rows.

Important current boundary: Phase 7 PR1 does **not** yet extract source objects
or change Familiar ranking. Until a later extractor/reranker phase lands,
Familiar still uses the Phase 6 page-level exact-search retrieval path.

Phase 7 PR2 adds deterministic source-object extraction:

- `tools/extract_source_objects.py` can populate `source_objects` with
  heading-derived `rule_section` objects and `page_chunk` fallback objects for
  all eligible copied/imported/indexed books or selected `--book-id` values.
- `book_object_status` now records per-book extraction state and the page-text
  snapshot hash used for idempotency.
- Extracted objects preserve book/page/character-span citations and confidence
  metadata.

Phase 7 PR3 integrates the first source-map-aware hybrid retrieval slice into
Familiar:

- New Familiar model runs resolve checked books from the thread's active source
  set at message time, so Library checkbox changes affect the next answer.
  `chat_thread_source_books` remains a historical thread-creation snapshot, but
  it is no longer the authoritative source for new retrieval runs.
- `retrieval_runs.metadata_json` stores the per-run checked-book snapshot,
  compact enabled-book source map, and candidate strings used for the run.
- `wfrp_companion/source_objects/store.py` now fills
  `source_object_search` and rebuilds `source_object_search_fts` when source
  objects are extracted; `book_object_status.status='indexed'` means the object
  projection was built.
- `wfrp_companion/assistant/retrieval.py` generates a broad candidate pool from
  page FTS and source-object evidence, expands close enabled-source vocabulary
  terms such as OCR/spelling variants, resolves page hits to owning
  source-object spans when available, and applies deterministic semantic
  reranking before prompt assembly.
- `retrieval_hits` snapshots object type, object title, heading path,
  confidence, rank reasons, text snapshot hash, and page-range metadata.
- Familiar prompt context now includes only the enabled-book source map and
  final reranked evidence packets. Citation buttons can display printed page
  ranges while retaining `pdf_page_number` as the hidden Grimoire jump target.

Local vector retrieval and deterministic table/stat/index/glossary extraction
now exist in later Phase 7 PRs. Hosted embeddings, richer OCR-layout table
reconstruction, and LLM/cross-encoder reranking remain future work. The current
reranker is a deterministic local relevance filter over fused candidates, not a
provider-backed semantic model.

Phase 7 PR4 splits Familiar retrieval into focused modules without changing
behavior:

- `wfrp_companion/assistant/retrieval.py` is now the compatibility facade and
  orchestration entrypoint for `retrieve_context()`.
- `wfrp_companion/assistant/source_map.py` owns current checked-source scope
  resolution and runtime enabled-book source-map construction.
- `wfrp_companion/assistant/query_planner.py` owns stopword filtering,
  candidate query construction, source-map term expansion, and fuzzy term
  helpers.
- `wfrp_companion/assistant/candidates.py` owns page FTS, source-object FTS,
  source-object fallback scans, page-hit-to-object resolution, and candidate
  deduplication.
- `wfrp_companion/assistant/evidence.py` owns retrieval/evidence dataclasses,
  page text loading, context windows, heading-path parsing, and printed page
  range labels.
- `wfrp_companion/assistant/reranking.py` owns deterministic semantic-overlap
  reranking and rank-reason helpers.
- `tests/assistant/test_retrieval_module_contracts.py` locks the facade to the
  focused module contracts so future phases can move behavior without breaking
  existing callers.

The next retrieval architecture decision is captured in
`docs/handoffs/2026-06-05-source-map-hybrid-retrieval-handoff.md`: Familiar
should move toward source-map-aware hybrid retrieval with semantic reranking
and section-aware evidence. That handoff preserves the user-observed Bretonnia
retrieval failure, Library checkbox source-scope requirement, printed-page
label issue, multi-page evidence requirement, and the research basis for using
lexical search, vector search, source-object search, query rewriting, rank
fusion, and semantic reranking together.

Phase 7 PR5 adds durable source-map/profile ownership for the checked-book
retrieval path:

- Migration `0002_source_map_retrieval` adds `book_retrieval_status`,
  `book_source_maps`, and `retrieval_run_source_books`.
- `tools/rebuild_source_maps.py` builds local source maps for books that have
  current source objects. It reports counts and failure reasons only; it must
  not print private extracted book text.
- `book_source_maps` owns compact per-book summaries, aliases, chapters, and
  query-profile routing metadata. `book_query_profiles` is now repopulated as a
  derived boost table during source-map rebuilds.
- Source-map freshness is based on the source-map inputs that affect routing:
  book title/category plus source-object ids, types, titles, heading paths,
  page ranges, and text snapshots.
- Familiar loads durable source maps only for the current checked-book
  snapshot. Missing, stale, or malformed durable rows fall back to the dynamic
  checked-book source-map builder rather than leaking unchecked source metadata
  or weakening query planning.
- `retrieval_run_source_books` snapshots the exact books considered by each
  retrieval run in queryable relational form, while
  `retrieval_runs.metadata_json.source_book_ids` remains a compatibility
  snapshot.

Phase 7 PR6 adds a repair/backfill path for source-object search projections:

- `wfrp_companion/source_objects/store.py` now has
  `rebuild_source_object_search()` to rebuild `source_object_search` and
  `source_object_search_fts` from existing `source_objects`.
- `tools/rebuild_source_object_fts.py` repairs databases where typed
  source-object rows exist but their lexical object-search projection is
  missing or stale.
- The tool uses `ingest_jobs(job_type='rebuild_source_object_fts')`, updates
  `book_object_status.status='indexed'` after successful projection rebuilds,
  validates FTS rowids, object-type postings, and vocabulary against the
  current projection before skipping, and reports only counts plus bounded
  failure reasons.
- This remains a lexical/object candidate maintenance tool. It does not add
  vector retrieval, new extraction heuristics, or public/private text exports.

Phase 7 PR7 adds rank fusion and an explicit reranker protocol:

- `wfrp_companion/assistant/candidates.py` now collects raw page/object
  channel candidates and sends them through reciprocal rank fusion before final
  reranking.
- `wfrp_companion/assistant/reranking.py` owns `ReciprocalRankFusion`, the
  `Reranker` protocol, and the default `DeterministicReranker`.
- Lexical channels remain candidate generators only. The deterministic
  reranker is the final local semantic gate and can reject weak lexical-only
  hits before they enter prompt context.
- RRF deduplicates candidates within each channel before assigning channel
  ranks, then combines independent channel contributions by evidence key.
- Source-object type text such as `table` and `stat block` participates in the
  reranker relevance text, so exact object-type queries can survive the
  semantic gate even when the private body text does not repeat the type label.
- Selected `retrieval_hits.rank_reasons_json` snapshots now include
  `fusion_channel:*`, `fusion:rrf=*`,
  `reranker:deterministic:accepted:*`, and
  `reranker_score:deterministic=*` entries for ranking auditability.
- This phase does **not** add vector candidates, embeddings, a provider-backed
  reranker, new extraction heuristics, or any public/private text export.

Phase 7 PR8 adds a local vector candidate channel:

- Migration `0003_vector_retrieval` adds `source_object_embeddings` for
  SQLite-local source-object vectors.
- `tools/rebuild_embeddings.py` can rebuild embeddings from current
  `source_objects` using the deterministic local `local-hash` provider. The
  default embedding provider is `disabled`, so vectors are opt-in.
- `book_retrieval_status.vector_status`, `vector_snapshot_sha256`,
  `embedding_model`, and `embedding_dimensions` own vector readiness and
  currentness per book.
- Familiar vector candidates are generated only for the checked `book_id`
  snapshot, only when the configured provider is `local-hash`, and only when
  the book's embedding snapshot is current.
- Vector rows join back to `source_objects` by both `source_object_id` and
  `book_id`, so malformed embedding rows cannot turn checked-book scope into
  unchecked-book evidence.
- Vector results enter the same candidate pool as page/source-object lexical
  hits, then go through RRF and the deterministic reranker. They do **not**
  bypass semantic relevance filtering or selected-evidence citation rules.
- This phase does not add hosted embeddings, a hosted vector database, or a
  provider-backed/cross-encoder reranker.

Phase 7 PR9 adds structured source-object evidence and link-aware evidence
resolution:

- Migration `0004_structured_evidence` widens typed source-object storage for
  canonical `glossary_entry` objects and `glossary_definition` links.
- `wfrp_companion/source_objects/extractor.py` now emits deterministic
  structured objects from conservative text patterns: `table`, `table_row`,
  `stat_block`, `npc_profile`, `index_entry`, `glossary_entry`, and
  `cross_reference`, while keeping existing `rule_section` and `page_chunk`
  coverage as fallbacks.
- `wfrp_companion/source_objects/store.py` persists derived
  `source_object_links` for table rows, stat/profile relationships, and
  deterministic same-book index/glossary/cross-reference targets when the
  target page/object can be resolved.
- Familiar evidence resolution follows selected-scope links so row/stat/index
  candidates resolve to complete parent or target source objects before prompt
  assembly. Glossary entries remain the canonical glossary evidence but may
  include linked target context.
- Page-only reference links resolve to the best checked target-page source
  object, preferring link-label/title matches, then fall back to checked target
  page text if no source object exists. Glossary linked context does not rewrite
  the canonical glossary citation/page range.
- Link traversal is constrained to the checked `source_book_ids` snapshot.
  A link pointing at an unchecked book is not followed and cannot become prompt
  context or a citation.
- Rank-fusion dedupe now preserves linked-evidence rank reasons, keeping
  selected `retrieval_hits.rank_reasons_json` useful for auditing how complete
  parent/target evidence was selected.
- This phase does not add OCR-layout table reconstruction, hosted reranking,
  or public/private text exports.

## Answer Contract

[coverage: high]

The assistant should:

- Answer from retrieved context when possible.
- Cite book and page for factual/rules claims.
- Say when the retrieved context is insufficient.
- Distinguish rules text from GM interpretation.
- Avoid dumping large passages of copyrighted text.
- Offer practical table guidance when the GM asks for help applying a rule.

## Prompt Context

[coverage: medium]

Prompt construction should include:

- User question.
- Retrieved book snippets with book/page metadata.
- Relevant campaign/session notes when enabled.
- A system instruction that enforces citations and private-use boundaries.

Keep prompts short enough to be fast and affordable. Log retrieval metadata for
debugging without logging unnecessary copyrighted text.

Phase 6 prompt construction lives in `wfrp_companion/assistant/prompts.py`.
It sends only bounded retrieved context plus the user question to OpenAI, scrubs
private local paths, and instructs Familiar to cite book/page references and say
when context is insufficient.

Phase 7 PR3 prompt construction also includes a compact source map for checked
books and section-aware evidence labels such as object title, heading path, and
printed page/page-range labels. Unchecked books are explicitly out of scope in
the system prompt.

## Streaming Provider Loop

[coverage: high]

Familiar streams output through the backend-owned endpoint
`POST /api/chat/threads/{thread_id}/messages/stream`. The browser uses
`fetch()` with a request body and reads newline-delimited JSON events:

- `accepted` after the user message and `model_runs` row are persisted.
- `retrieval` after local retrieval metadata is written.
- `delta` for each streamed assistant text chunk.
- `completed` after one assistant `chat_messages` row is persisted and linked.
- `failed` when the provider is unavailable or returns an error.

`wfrp_companion/assistant/provider.py` wraps the OpenAI Responses API and maps
OpenAI text delta/completed events into app-owned events. The API key is read
from `OPENAI_API_KEY` on the backend only.

The Familiar frontend renders streamed assistant text through a safe local
markdown renderer for common model output structures: headings, paragraphs,
lists, tables, bold text, and inline code. It does not use raw HTML injection.

## Adventure Generation

[coverage: medium]

Adventure generation should be a later workflow that uses:

- WFRP setting/rules context from retrieval.
- Campaign notes and prior session summaries.
- Structured outputs for scenes, NPCs, clues, encounters, locations, and
  handouts.

Generated material should cite sources when it relies on specific canon or
rules, and should label original invention clearly.

## Voice And Session Context

[coverage: low]

TTS and speech-to-text are future enhancements. The likely progression is:

- TTS for reading boxed text or generated narration.
- Manual session notes.
- Audio transcription or live note capture.
- Session summaries added to campaign memory.

## Sources

- `wiki/concepts/hybrid-search-for-rules.md`
- `wiki/topics/pdf-library-and-ingestion.md`
- `wiki/concepts/private-copyright-boundary.md`
