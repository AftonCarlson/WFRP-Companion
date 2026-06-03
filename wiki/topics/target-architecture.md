# Target Architecture

## MVP Shape

[coverage: medium]

The first useful version should be a local-first web app with:

- A browser GUI for library/search/chat.
- A small backend API for PDF ingestion, indexing, retrieval, and AI calls.
- Local storage for PDFs, extracted text, indexes, and campaign notes.
- OpenAI API integration for assistant responses.

The recommended default is a practical split:

- Frontend: React with Vite or Next.js.
- Backend: Python FastAPI or Node/TypeScript. Python dependencies are managed
  with Conda via `environment.yml`.
- PDF viewing: PDF.js.
- PDF extraction: PyMuPDF in the Conda environment for the initial ingestion
  spike; add OCR later only if extraction stats show it is needed.
- Database: SQLite for app metadata and campaign state.
- Search: SQLite FTS or Tantivy-style full-text index plus a vector store.
- Vector store: LanceDB, Chroma, or pgvector depending on chosen backend.

Pick exact dependencies when implementation starts and verify current docs.
The first Python dependency decision is recorded in
`docs/adr/0001-conda-python-tooling.md`.

## Major Modules

[coverage: medium]

- Library: PDF registration, book metadata, file paths, cover thumbnails.
- Reader: in-browser PDF rendering, page navigation, citation links.
- Ingestion: text extraction, page segmentation, OCR fallback, chunking.
- Retrieval: full-text search, vector search, ranking, citation assembly.
- Assistant: prompt construction, model calls, streamed responses, refusal when
  context is insufficient.
- Campaign: notes, session summaries, NPCs, locations, adventure prep artifacts.

## Local-First Boundary

[coverage: high]

Default to keeping PDFs, extracted text, indexes, and notes on the user's
machine. Only send the minimum retrieved context and user prompt to the model
provider for an answer.

## Future Hosted Option

[coverage: medium]

A hosted option can exist later, but it should be explicit. Hosting changes the
privacy, copyright, backup, auth, and cost profile enough that it should be an
intentional decision rather than an accidental architecture drift.

## Sources

- `wiki/topics/project-overview.md`
- `wiki/topics/local-tooling-and-packaging.md`
- `docs/adr/0001-conda-python-tooling.md`
- `wiki/concepts/private-copyright-boundary.md`
- `wiki/concepts/hybrid-search-for-rules.md`
