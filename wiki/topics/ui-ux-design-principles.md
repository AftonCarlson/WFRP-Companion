# UI/UX Design Principles

## Product Posture

[coverage: high]

This should feel like a practical GM cockpit, not a landing page. The first
screen should help the GM read, search, ask, and prep.

## Core Views

[coverage: medium]

- Library: books, status, import actions, quick search.
- Reader: PDF view with page navigation and citation jump targets.
- Search: exact and semantic results with book/page provenance.
- Assistant: chat with cited answers and context controls.
- Campaign: notes, session summaries, NPC/location/adventure prep.

## Table-Use Defaults

[coverage: high]

- Optimize for fast scanning and low visual noise.
- Keep controls predictable and close to the work.
- Make citations clickable into the PDF reader.
- Make it obvious when the assistant is using book context, campaign notes, or
  general reasoning.
- Keep generated adventure content editable and saveable.

## Visual Direction

[coverage: medium]

Use a quiet, readable interface with restrained theme treatment suitable for
long sessions. WFRP flavor can come through in typography, icons, labels, and
art placement later, but the MVP should prioritize clarity and speed.

The current primary UI art asset is `assets/ui/buttlordxai-hero.png`, a
generated pixel-art banner intended for the initial app hero, banner, or
background treatment. When the web app is scaffolded, route it through that
frontend's normal public/static asset pipeline.

## Accessibility

[coverage: medium]

Support keyboard navigation, readable contrast, responsive layouts, and text
that does not overlap or truncate inside controls. The PDF reader and chat panel
should remain usable on laptop screens.

## Sources

- `wiki/topics/project-overview.md`
- `wiki/topics/ai-rag-system.md`
- `assets/ui/README.md`
