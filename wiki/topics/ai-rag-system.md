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

Vector retrieval, glossary/index extraction, table/stat-block extraction, and
LLM/cross-encoder reranking remain later phases. The current reranker is a
deterministic local relevance filter over lexical/object candidates, not a
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
