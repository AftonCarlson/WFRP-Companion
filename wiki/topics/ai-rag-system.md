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

The current Phase 6 implementation uses deterministic local exact search first:

- New chat threads snapshot enabled books into `chat_thread_source_books`.
- `wfrp_companion/assistant/retrieval.py` resolves retrieval scope from that
  snapshot, not from mutable live Library toggles.
- Retrieved pages are recorded in `retrieval_runs` and `retrieval_hits` before
  the provider call.
- Streaming chat events include citations that can open the exact PDF page in
  Grimoire.

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
