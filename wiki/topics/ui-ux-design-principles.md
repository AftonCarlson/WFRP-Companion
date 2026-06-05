# UI/UX Design Principles

## Product Posture

[coverage: high]

This should feel like a practical GM cockpit, not a landing page. The first
screen should help the GM read, search, ask, and prep.

## Core Views

[coverage: high]

- Library: grouped book selector with per-book checkboxes, status text, and
  open-reader actions.
- Reader: PDF.js view with source tabs, page navigation, zoom, retry-on-error,
  and citation jump targets.
- Search: exact results grouped by book with snippets, full-page text expansion,
  and `Open PDF page` actions.
- Assistant: chat-shaped shell with transcript, composer, and history popover.
  The assistant is intentionally offline until the AI/RAG phase.
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

Phase 5 copies that asset to
`frontend/public/assets/buttlordxai-hero.png`. The first committed GUI keeps
the visual treatment restrained so later custom graphics, animation, and layout
polish can be layered onto stable panels and state boundaries.

## Accessibility

[coverage: medium]

Support keyboard navigation, readable contrast, responsive layouts, and text
that does not overlap or truncate inside controls. The PDF reader and chat panel
should remain usable on laptop screens.

Implemented Phase 5 accessibility rules:

- Library/Search uses proper `tablist`, `tab`, and `tabpanel` wiring.
- PDF source tabs use `aria-controls`, `aria-selected`, and a paired
  `tabpanel`; close buttons are outside the `tablist`.
- The View control is a plain popover trigger with `aria-expanded` and
  `aria-controls`, not a fake menu.
- Panel splitters expose vertical separator metadata and support keyboard
  resizing with arrow/Home/End keys.
- Chat history uses a dynamic open/close label and plain popover semantics.
- Saved workspace layout is treated as untrusted data and validated before use.

## Sources

- `wiki/topics/project-overview.md`
- `wiki/topics/ai-rag-system.md`
- `assets/ui/README.md`
