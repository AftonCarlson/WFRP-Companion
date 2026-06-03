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

[coverage: medium]

Retrieval should combine:

- Full-text search candidate set.
- Vector search candidate set.
- Metadata filters by book, page range, or content type.
- A ranking/reranking step.
- Structured citations passed to the assistant.

The assistant should receive the final selected context, not query the raw PDF
library directly.

## Sources

- `wiki/topics/ai-rag-system.md`
- `wiki/topics/pdf-library-and-ingestion.md`
