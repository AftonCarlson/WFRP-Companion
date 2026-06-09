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

Current Familiar implementation:

- Familiar is a bounded tool-calling research agent, not a single retrieval
  call chained directly to one model answer.
- Each run resolves the user's request, preserves active follow-up context
  such as the current subject, records a `familiar_research_runs` row, and
  starts with a backend-selected tool.
- Chat requests may include `reader_context` from the active Grimoire tab:
  active book id, active PDF page number, optional printed page label, and open
  book ids. Familiar treats this only as a routing hint for page-aware
  recovery; it is not evidence and cannot satisfy citations by itself.
- `search_library` is the default tool. It uses hybrid retrieval over the
  thread's checked source-book snapshot: page FTS, source-object FTS,
  source-object fallback scan, current local vector candidates when embeddings
  are enabled, structured table/stat/source-object signals, RRF fusion, and
  deterministic reranking.
- `open_page` is used when the request contains page evidence such as
  "it is on pg 99"; it resolves the checked book plus PDF/printed-page label
  directly instead of trying another broad text search.
- `lookup_source_object` can recover a complete structured evidence object
  from a selected source-object id while still enforcing the checked-book
  source scope.
- Evidence validation runs after every tool call. Only accepted evidence can
  feed the final answer prompt and final citation run; partial or rejected
  evidence remains in the research trace for debugging.
- Weak or empty evidence can trigger bounded recovery tool calls through the
  provider. The backend still validates tool names, arguments, scope, evidence
  status, and max tool rounds.
- Retrieval diagnostics record which channels ran, vector status/failures,
  selected candidates, reranker outcomes, page lookup attempts, table/stat
  lookups, skip reasons, and accepted/rejected evidence judgments.
- The UI can surface aggregate retrieval readiness through
  `/api/retrieval/status`: copied books, enabled books, page-text indexed
  books, source-object indexed books, table/stat indexed books, current
  vectorized books, vectorized enabled books, provider, dimensions, and
  aggregate vector status.
- Familiar chat turns surface a compact expandable research trace from stream
  events: research start, tool call, retrieval/candidate counts, vector status
  when reported, evidence validation status, and failures.

Historical phase notes below describe how the current system was assembled.

Phase 6 added deterministic local exact search first:

- New chat threads snapshot enabled books into `chat_thread_source_books`.
- Retrieved pages are recorded in `retrieval_runs` and `retrieval_hits` before
  the provider call.
- Streaming chat events include citations that can open the exact PDF page in
  Grimoire.
- Chat citation payloads carry `pdf_page_number` for the Grimoire jump target
  and optional `page_label` for printed-page context. Frontend code must not
  infer a PDF jump target from citation display text.

That Phase 6 vector boundary has been superseded. Current vector retrieval
layers onto the same explicit source-set and citation contract rather than
replacing it.

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

Historical boundary: Phase 7 PR1 did **not** yet extract source objects or
change Familiar ranking. Later phases and the current Familiar agent now use
source objects, rank fusion, vector candidates, and evidence validation.

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

- New Familiar model runs use the thread's checked-book snapshot in
  `chat_thread_source_books` as the authoritative source scope for research
  tools. `retrieval_run_source_books` then snapshots the exact books considered
  by each tool call or final accepted-evidence run.
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

The local semantic embeddings phase upgrades that vector path from a smoke
test to a real local provider boundary:

- Migration `0006_embedding_provider_identity` makes both
  `book_retrieval_status` and `source_object_embeddings` provider-aware, so
  `local-hash` and `sentence-transformers` rows cannot collide.
- `wfrp_companion/source_objects/embedding_providers.py` owns the provider
  protocol, deterministic `local-hash` provider, and lazy
  `sentence-transformers` provider.
- The recommended semantic profile is
  `WFRP_EMBEDDING_PROVIDER=sentence-transformers`,
  `WFRP_EMBEDDING_MODEL=BAAI/bge-m3`, and
  `WFRP_EMBEDDING_DIMENSIONS=1024`.
- Sentence Transformers model instances are cached by model, device, and
  local-files-only mode. Source-object text and query text are not cached.
- Embedding rebuilds claim the job and mark `indexing` in short SQLite
  transactions, compute vectors outside write transactions, recheck the
  source-object snapshot, and only then replace rows for the same
  book/provider/model/dimensions.
- Vector currentness also requires the stored vector blob byte length to match
  the configured dimensions, so malformed local rows cannot look current or
  crash query-time scoring.
- If source objects change during local inference, existing vector rows are
  preserved, the book becomes `needs_refresh`, and the job is failed with a
  bounded safe reason.
- If local embedding inference fails after a rebuild job is claimed, both
  `book_retrieval_status` and the matching `ingest_jobs` row are marked
  failed with a bounded error and `completed_at`, so normal retry behavior does
  not depend on stale-job recovery.
- Query-time vector search resolves the configured provider, embeds the query
  locally, filters by checked-book currentness, and records
  `vector_provider:*`, `vector_model:*`, and `vector_similarity:*` rank
  reasons before RRF/reranking.
- Query-time provider dependency, runtime, or dimension failures are treated as
  a missing vector channel for that retrieval run. Familiar still uses exact
  page/object candidates rather than failing the model run.
- `/api/books` exposes vector status, provider, and dimensions only; it does
  not expose `embedding_model` because that user-configurable value can be a
  local filesystem path. The Library UI shows one compact semantic-search
  status summary. It does not expose raw vector errors, local paths, source
  text, or per-book semantic badges.

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

Phase 7 PR10 adds printed page-label calibration/backfill:

- Migration `0005_page_label_calibration` adds
  `book_page_label_calibrations` and
  `ingest_jobs(job_type='backfill_page_labels')` for existing databases and
  fresh schemas.
- `wfrp_companion/library/page_labels.py` owns calibrated printed-label
  snapshots, offset-anchor metadata, currentness checks, stale-running
  recovery, and count-only failure state under
  `book_retrieval_status.page_label_status`.
- `tools/backfill_page_labels.py` can backfill all eligible copied/imported
  books or selected `--book-id` values. Optional
  `--anchor book_id:pdf_page_number:printed_label` values calibrate offsets
  while preserving roman/front-matter labels before the anchor. Plain reruns
  preserve current anchored calibrations and reuse stored anchors after page
  text/label snapshot drift unless `--force` or a new anchor is supplied.
- Exact search, Familiar prompt evidence, and stored/reloaded chat citations
  prefer current calibrated printed labels/ranges. The hidden
  `pdf_page_number` remains the reader jump coordinate.
- Missing/conflicting/manual-review labels are not promoted to confident
  printed labels: page-fallback evidence, source-object evidence, linked page
  evidence, and reloaded citations leave printed label/range metadata absent
  when calibration cannot prove a printed label.
- CLI output remains count-oriented and prints safe failure categories rather
  than raw exception payloads that could contain private extracted text.
- Label lookup is a display/citation layer after retrieval selection; it does
  not expand source scope and cannot introduce unchecked-book evidence.

Phase 7 PR11 adds Familiar prompt history and history-aware retrieval planning:

- `wfrp_companion/assistant/conversation_context.py` builds the app-owned
  conversation context for each Familiar run. It loads only prior completed
  logical turns in the same thread, applies configurable turn/character
  limits, and returns separate prompt-history and retrieval-query views.
- Provider-side memory remains disabled. `OpenAIProvider` sends Responses API
  requests with `store=False` and does not use provider conversation IDs or
  `previous_response_id`; SQLite chat messages/model runs remain the durable
  source of truth.
- Chat history is **not evidence**. It may resolve pronouns or follow-up intent,
  but factual WFRP claims still have to come from the current checked-book
  retrieved evidence and citations.
- Self-contained retrieval queries stay unchanged. Only follow-up/reference
  queries add compact salient chat terms to the retrieval query, and the raw
  user query is still stored separately from the planned retrieval query in
  `retrieval_runs.metadata_json`. Familiar does not copy full prior assistant
  answers into retrieval planning; failure-style answers that say retrieved
  evidence was missing are skipped as retrieval-query context so wrong-source
  detours do not snowball.
- Familiar still resolves enabled books from the thread's
  `chat_thread_source_books` snapshot at run time. Source maps, candidate
  generation, reranking, prompt context, retrieval metadata, and citations
  remain constrained to that checked-book snapshot.
- The chat read model now collapses retries into one visible logical turn:
  completed retries win, active retries are visible over failed attempts, and
  otherwise the newest failed run is shown.
- The browser history drawer loads saved threads, restores logical turns, and
  disables thread switching while a stream is active.

Follow-up stat/table retrieval repair on 2026-06-06 tightened the current
structured-evidence path:

- Structural query words such as `stat`, `block`, `table`, and `chart` are no
  longer edit-distance expanded into unrelated source-map aliases. This keeps
  `stat block` from matching `black` while preserving ordinary plural/OCR
  variants for non-structural terms.
- Source-object extraction now recognizes WFRP-style OCR stat profiles with
  pipe/percent main and secondary profile rows, plus range charts such as the
  Core Rules hit-location table. Range charts get chart-searchable table and
  table-row text, and the hit-location OCR title is normalized for retrieval.
- The extractor version is `structured-evidence-v4`; existing local databases
  must rerun `tools/extract_source_objects.py`, then rebuild source-object FTS
  and source maps, to pick up the repaired table/stat objects.
- Deterministic reranking now gives accepted typed table/chart and stat/profile
  evidence a structural-intent boost, so complete source objects outrank prose
  that merely mentions the requested table or stat block. Structural stat/table
  requests must still match the named entity terms: if the user asks for the
  `Black Knight` stat block, `Black Orc Statistics` is rejected even though it
  matches `black` and has a stat profile.
- Inherited chapter headings and repeated running headers can still help route
  lexical candidates, but they cannot be the only match that admits a
  multi-term entity result into prompt context. This prevents unrelated
  subsections in a chapter from supplying wrong stat-like evidence.

Follow-up sparse query normalization repair on 2026-06-08 tightened the current
hybrid retrieval path:

- Query planning now produces bounded sparse alternatives for common structural
  compounds and inflections. For example, `statblocks for harpies` can search
  `stat block harpy`, and `statblock for gors` can search `stat block gor`,
  without adding creature-specific aliases.
- Planner `match_terms` are intentionally narrower than FTS candidates. They
  split structural compounds such as `statblock` into `stat` and `block`, but
  they do not add every plural/singular variant as a separate relevance term.
  This prevents the deterministic reranker from double-counting one concept
  such as `critical` plus `criticals`.
- Exact page resolution and deterministic reranking use `match_terms`, so page
  hits, object hits, and source-object link resolution apply the same
  normalized structural intent. Dense vector query text stays close to the
  user's original meaningful terms, keeping semantic embeddings from being
  polluted by synthetic sparse variants.
- Research grounding: this follows established hybrid IR/RAG practice: sparse
  lexical search preserves exact term evidence, query expansion improves
  candidate recall, and two-stage retrieval/reranking protects the prompt
  budget. See SQLite FTS5 tokenizers, SPLADE sparse lexical retrieval,
  Query2doc query expansion, and recent hybrid/two-stage RAG papers. The app
  keeps this expansion deterministic and bounded because private rules lookup
  needs auditable evidence rather than generated pseudo-book text.
- Live QA after the repair confirmed that the original query
  `give me the statblock for gors` retrieves Old World Bestiary page 84 / Gor
  Statistics as the first evidence item under the checked 13-book source set.

Follow-up stat-line retrieval repair on 2026-06-08 tightened the same path:

- Query planning now treats `stat line` and `statline` as structural stat
  requests. It generates sparse candidates such as `harpy statistics`,
  `harpy stat block`, and `harpy profile`, while reranker match terms count
  `statistics`/`block` rather than treating `line` or generic `profile` as
  proof of stat evidence.
- Structural named-entity validation now uses source-object-local entity text.
  Page snippets and incidental body mentions from neighboring source objects do
  not prove that a titled object is the requested creature/NPC/table. This
  prevents a Harpy page snippet from validating a neighboring Hippogriff
  profile, and prevents unrelated sections that mention Harpies from outranking
  Harpy Statistics evidence.
- Very short fallback `page_chunk` source objects expand to a bounded window
  around their `char_start`/`char_end` page span. This lets a heading-only
  fallback such as `Harpy Statistics` carry nearby local page context without
  copying an entire page into the prompt.
- Live QA after the repair confirmed that `harpies stat line` retrieves Old
  World Bestiary page 100 / Harpy Statistics as the only selected evidence
  item. The retrieved local text still reflects OCR quality; if a stat table
  header or cell is absent from extracted text, Familiar should cite the page
  and say the retrieved text is incomplete rather than inventing missing values.

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

Phase 7 PR11 prompt construction can include bounded prior chat messages before
the current question. The system prompt explicitly says that recent chat is
only for conversational references and user intent; it is not retrieved
rules/evidence. Current retrieved context remains the only basis for cited WFRP
claims.

The current Familiar agent has two prompt surfaces:

- A research prompt that exposes only bounded tools:
  `search_library`, `open_page`, and `lookup_source_object`. It instructs the
  model to use tools only for retrieval correction and to keep factual claims
  out of tool planning.
- A final answer prompt that receives accepted evidence only. It instructs
  Familiar to cite book/page references for factual WFRP claims, say when
  evidence is insufficient, distinguish rules from GM interpretation, and avoid
  long copyrighted excerpts.

## Streaming Provider Loop

[coverage: high]

Familiar streams output through the backend-owned endpoint
`POST /api/chat/threads/{thread_id}/messages/stream`. The browser uses
`fetch()` with a request body and reads newline-delimited JSON events:

- `accepted` after the user message and `model_runs` row are persisted.
- `research_started` after the Familiar research run is created and the
  request has a resolved intent/query.
- `tool_call` before each backend research tool is executed.
- `retrieval` after a tool retrieval run or final accepted-evidence retrieval
  run is written.
- `tool_result` after each backend research tool returns count-only result
  metadata.
- `evidence_validation` after retrieved hits are judged accepted, partial, or
  rejected for the current request.
- `delta` for each streamed assistant text chunk.
- `completed` after one assistant `chat_messages` row is persisted and linked.
- `failed` when the provider is unavailable or returns an error.

`wfrp_companion/assistant/provider.py` wraps the OpenAI Responses API and maps
OpenAI text delta/completed events into app-owned events. The API key is read
from `OPENAI_API_KEY` on the backend only.

If a client disconnects after a run has been accepted but before completion,
the backend marks the active `model_runs` row as `failed` with
`stream_interrupted` instead of leaving it stuck in `queued`, `retrieving`, or
`calling_model`.

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
