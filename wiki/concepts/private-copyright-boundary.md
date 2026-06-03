# Private Copyright Boundary

## Pattern

[coverage: high]

The app is for private family-session use over PDFs the user owns. That boundary
should influence storage, retrieval, UI, tests, and deployment decisions.

## What This Means

[coverage: high]

- Keep PDFs and extracted text local by default.
- Do not commit PDFs, extracted book text, vector indexes, or large excerpts.
- Do not build public browsing/export features for book contents.
- Prefer cited summaries and short excerpts in assistant answers.
- Make hosted deployment an explicit later decision with auth, storage, and
  copyright implications reviewed.

## Design Implications

[coverage: medium]

The app can still be powerful: it may search, cite, summarize, and help the GM
apply rules. The boundary is about preventing accidental redistribution, not
about making the private tool timid or useless.

## Sources

- User clarification: private only, family session use.
- `wiki/topics/project-overview.md`
- `wiki/topics/ai-rag-system.md`
