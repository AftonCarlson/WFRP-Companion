# Project Overview

## Purpose

[coverage: high]

WFRP Companion is a private AI Game Master aid for Warhammer Fantasy Roleplay
2nd edition. The intended user is a GM running sessions with family using
legally owned PDFs of published books.

The app should make the book library useful at the table without becoming a
public rules database. Core value comes from fast lookup, cited answers, PDF
reading, and campaign-aware prep assistance.

## Initial Product Goals

[coverage: high]

- Import and manage a local PDF library.
- Read PDFs inside a web GUI.
- Extract text with book/page metadata.
- Search books by exact terms and semantic meaning.
- Chat with an AI assistant that answers with citations.
- Store campaign/session notes that can be included in assistant context.
- Later, generate adventure modules, encounters, NPCs, handouts, and summaries.

## Non-Goals

[coverage: high]

- Public redistribution of WFRP book text.
- A hosted public SRD.
- Replacing the GM's judgment at the table.
- Building every future automation before the PDF/search/chat loop works.

## Current State

[coverage: high]

As of the initial scaffold, the repository contains development guidance and a
wiki, but no application code. Treat architecture pages as target direction
until implementation exists.

## Sources

- User project brief from the initial planning conversation.
- Root repo guidance in `CLAUDE.md` and `AGENTS.md`.
