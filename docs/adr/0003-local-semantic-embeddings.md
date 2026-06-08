# ADR 0003: Use Local Sentence Transformers For Semantic Embeddings

## Status

Accepted

## Context

Familiar already uses checked-book scope, SQLite FTS, source objects, reciprocal
rank fusion, deterministic reranking, and citations. The current `local-hash`
embedding path is useful as a deterministic smoke test, but it is not semantic
search.

The project is private and local-first. Imported WFRP PDFs, extracted text,
source objects, vector rows, and generated indexes are user-owned runtime data
and must not be sent to hosted embedding APIs by default.

## Decision

Use `sentence-transformers` as the first real local embedding provider, with
`BAAI/bge-m3` as the recommended dense model profile. Keep SQLite
`source_object_embeddings` as the MVP vector store and scan vectors in-process
for the current local corpus size.

Keep `local-hash` as a deterministic test and smoke provider. The real provider
is opt-in through config:

```bash
WFRP_EMBEDDING_PROVIDER=sentence-transformers
WFRP_EMBEDDING_MODEL=BAAI/bge-m3
WFRP_EMBEDDING_DIMENSIONS=1024
```

The provider loads model weights lazily, caches model instances by model,
device, and offline mode, and never caches source text or query text.

## Consequences

- Semantic retrieval remains local and private by default.
- The Conda environment now includes larger ML dependencies.
- First model use may download Hugging Face assets unless local-files-only mode
  is enabled.
- SQLite remains the app-owned source of truth for vector lifecycle state.
- Hosted embeddings and a separate vector database are deferred until there is
  a clear privacy, quality, or scale reason to add them.
