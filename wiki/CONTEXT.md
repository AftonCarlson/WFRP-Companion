# Codebase Wiki -- Navigation Guide

This project has a lightweight development wiki. Use it to orient before
scanning raw files or making architecture decisions.

## How To Use This Wiki

1. Start at [INDEX.md](INDEX.md) and choose 1-3 relevant topic pages.
2. Read the selected topics before editing files.
3. Check coverage tags inside topic sections:
   - `[coverage: high]` -- reliable orientation
   - `[coverage: medium]` -- useful overview, verify details before coding
   - `[coverage: low]` -- read raw source or plans directly
4. Check `concepts/` for cross-cutting patterns that affect many modules.
5. Update the wiki when a material decision changes.

## When Not To Rely On The Wiki Alone

- Writing or debugging exact code
- Confirming dependency versions, APIs, env vars, or command syntax
- Resolving a conflict between docs and live implementation
- Making claims about behavior that should be testable

## Project Context

WFRP Companion is intended as a private, local-first AI Game Master aid for
Warhammer Fantasy Roleplay 2nd edition sessions with family. The app should
reference user-owned PDFs, support in-app reading, provide cited rules answers,
and eventually help generate adventure material.

When topics conflict, trust live code first, then current plans/ADRs, then the
wiki, then historical notes.
