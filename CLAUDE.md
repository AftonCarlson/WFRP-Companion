# CLAUDE.md -- Agent Instructions

## Required First Actions

Before responding to development requests in this repo:

1. Read `wiki/CONTEXT.md` for navigation guidance.
2. Read `wiki/INDEX.md` to find the topic articles relevant to the task.
3. Read those topic articles before editing files or making architecture claims.
4. Verify against live code when code exists. The wiki is orientation, not proof.

Do not rely on memory from prior sessions. Keep durable project knowledge in the
wiki rather than expanding this file.

## Coverage Indicators

Wiki sections use coverage tags:

- `[coverage: high]` means the section is reliable orientation.
- `[coverage: medium]` means the section is a useful overview, but raw sources
  may be needed for implementation detail.
- `[coverage: low]` means read the listed sources directly before acting.

## Source Of Truth

Use this precedence order when reasoning about the repo:

1. Live code and tests in the repo
2. Current implementation plans and ADRs in `docs/`
3. Compiled wiki pages in `wiki/`
4. Historical notes, chats, and summaries

If docs conflict with code, trust code for current behavior and update docs when
the change is in scope.

## Project Boundary

WFRP Companion is a private family-table GM aid over legally owned PDFs. Design
for local/private use, citation back to source pages, and copyright-respectful
retrieval. Do not build public redistribution features for copyrighted book
content.

## Wiki Workflow

- Keep application facts, architecture notes, development decisions, and known
  gotchas in `wiki/`.
- Update the relevant wiki topic when a material design or implementation
  decision changes.
- Add implementation plans under `docs/plans/` when work spans multiple modules
  or has meaningful architectural risk.
- Keep this file short and workflow-only.

## AI/Media Workflow

- Do not call image-generation tools unless the user explicitly asks for image
  generation or image editing.
- Prefer text, code, and documentation changes for development scaffolding.
