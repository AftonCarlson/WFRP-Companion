# AGENTS.md -- Agent Instructions

## Repo-Specific Context

- Read `CLAUDE.md` first for wiki, source-of-truth, conflict-rule, and private
  project boundary guidance.
- For code-changing tasks, read `wiki/topics/implementation-standards.md` before
  editing.
- Keep durable knowledge in the compiled wiki under `wiki/`, not in this file.

## Mandatory Rules For Development Work

### Grounding

- For wiki-covered areas, read the relevant topic before planning or editing.
- For spec-driven work, read the source plan/spec before implementation.
- Never claim something is implemented without checking the current repo.
- When the repo has live code, verify behavior against the code and tests before
  making precise technical claims.

### Copyright And Privacy

- Treat imported WFRP PDFs as private user-owned reference material.
- Do not design routes, exports, seed data, or fixtures that publicly reproduce
  book text.
- Prefer citations and short retrieved excerpts over large copied passages.
- Keep local-first storage as the default unless the user explicitly chooses a
  hosted deployment.

### Tool And Source Usage

- Use official docs or current documentation tools for version-sensitive
  libraries, APIs, or cloud services.
- Use hybrid retrieval for rules work: exact keyword/full-text search plus
  semantic/vector search.
- Do not call image-generation tools unless the user explicitly asks for image
  generation or image editing.
- Keep subagent usage sparse and explicit. If subagents are used, wait with a
  bounded `wait_agent` call, then close completed agents sequentially. Never
  close agents in parallel, never close running or unknown-status agents, and
  stop if cleanup itself becomes unreliable. If `spawn_agent` reports
  `agent thread limit reached`, diagnose attached agent status before choosing
  CodeRabbit, a Codex background thread, or another independent review path.

## Engineering Guidelines

### Simplicity First

- Build the smallest working slice that proves the product direction.
- Avoid speculative abstractions before there is real code pressure.
- Prefer boring local infrastructure for the MVP: file storage, SQLite, a small
  backend, and clear tests.

### Surgical Changes

- Touch only files relevant to the user request.
- Match existing repo patterns as they emerge.
- If you see unrelated cleanup, mention it instead of doing it.

### Verification

- For code changes, run the narrowest useful test or build command available.
- If no test infrastructure exists yet, say so and verify with static inspection.
- Add tests when behavior touches ingestion, retrieval ranking, citations,
  prompt construction, or user-facing workflows.

## User Experience Defaults

- Build the actual app surface first, not a marketing page.
- Prioritize a practical GM workflow: library, PDF reader, search, cited chat,
  campaign notes, and generated prep artifacts.
- Use calm, dense, readable UI for repeated table use.
