# Hybrid Search For Rules

## Pattern

[coverage: high]

Rules-heavy RPG books need both exact search and semantic search. A vector
database is useful, but it should not be the only retrieval mechanism.

## Why Exact Search Matters

[coverage: high]

GMs often search for precise terms:

- Talent names
- Spell names
- Career names
- Conditions
- Tables
- Location names
- NPC names
- Page references

Full-text search is usually better than vectors for these cases.

## Why Vector Search Matters

[coverage: high]

GMs also ask fuzzy questions:

- "How do I handle fear in combat?"
- "What rules cover disease recovery?"
- "Give me setting context for a corrupt town magistrate."

Semantic search can find relevant passages even when the question does not use
the exact book phrasing.

## Implementation Implication

[coverage: high]

Retrieval should combine:

- Exact page full-text search for literal terms and page-level fallback.
- Source-object full-text search for headings, table labels, stat/profile
  titles, glossary entries, index entries, and linked evidence.
- Source-object fallback scan for typed objects when FTS misses the relevant
  structure.
- Vector search over current local source-object embeddings when embeddings are
  enabled and the book snapshot is current.
- Direct page lookup for explicit PDF page or printed page references.
- Direct source-object lookup for complete table/stat/source-object recovery.
- Metadata filters by the thread's checked source-book snapshot, page range,
  object type, and source-object links.
- Rank fusion plus deterministic reranking so exact structured hits are not
  buried by fuzzy semantic matches.
- Evidence validation before prompt construction.
- Structured citations passed to the assistant only for accepted evidence.

The backend owns this policy. Familiar can request bounded research tools, but
it does not decide whether vector search runs and it does not query raw PDF
files directly. The final assistant prompt receives accepted evidence packets,
not the whole library.

Operational vector search means the imported/enabled books have source objects
and current embeddings in the local SQLite vector store. A useful retrieval
trace should show whether the vector channel ran, which candidates it produced
or why it was skipped, how candidates were reranked, and why the final evidence
was accepted or rejected.

Current diagnostics distinguish a ready vector channel that found no selected
candidate (`ran_no_candidates`) from disabled embeddings, missing embeddings,
**stale embeddings**, and provider errors. Staleness includes non-indexed
status, source snapshot mismatch, provider/model mismatch, or embedding
dimension mismatch. This matters because a no-candidate result is different
from a broken or stale semantic index: lexical/source-object channels can still
complete the run, but the trace should say exactly what happened.

## Sources

- `wiki/topics/ai-rag-system.md`
- `wiki/topics/pdf-library-and-ingestion.md`
