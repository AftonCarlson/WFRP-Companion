# UI/UX Design Principles

## Product Posture

[coverage: high]

This should feel like a practical GM cockpit, not a landing page. The first
screen should help the GM read, search, ask, and prep.

## Core Views

[coverage: high]

- Library: grouped book selector with per-book checkboxes, section-level bulk
  checkboxes, compact book-icon open actions, and a separate Search tab.
- Grimoire: PDF.js view with source tabs, Chrome-style close controls, page
  navigation, single-page/two-page view toggles, zoom, retry-on-error, and
  citation jump targets.
- Search: exact results grouped by book with snippets, full-page text expansion,
  and compact book-icon open actions labelled with explicit PDF page targets.
- Familiar: chat-shaped shell with transcript, composer, in-header history
  control, and history popover.
  The assistant streams model output during the AI/RAG phase and renders common
  markdown structures as readable UI.
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
  `tabpanel`; close buttons are visually inside each tab while remaining
  outside the semantic `tablist`, and the tab strip scrolls as one layer so tab
  labels and close controls do not desynchronize.
- The View control is a plain popover trigger with `aria-expanded` and
  `aria-controls`, not a fake menu.
- Panel splitters expose vertical separator metadata and support keyboard
  resizing with arrow/Home/End keys.
- Chat history uses a dynamic open/close label and plain popover semantics.
- Saved workspace layout is treated as untrusted data and validated before use.

## Phase 5 Current UI Contract

[coverage: high]

- The three workspace panels are titled `Library`, `Grimoire`, and `Familiar`.
- Panel content must remain height-bounded inside the viewport; page-level
  scrolling should not be required to reach library/search results or the
  Familiar composer.
- Library category headings include a tri-state checkbox for selecting or
  clearing every visible book in that category. Per-book readiness words such
  as `ready` are intentionally not rendered in the list to keep the selector
  scan-friendly.
- Grimoire header controls own page number, single-page/two-page view mode,
  zoom out/in, and fit-width reset. Previous/next page controls live beside the
  PDF canvas as minimal `<` and `>` side buttons.
- Grimoire tabs show book/source titles only, not page-number suffixes.
- Two-page mode keeps pages 1 and 2 as single pages, then displays page pairs
  starting at 3/4, 5/6, and so on. An unpaired final page is shown alone.
- The Familiar header owns the chat-history hamburger. The chat panel itself
  contains only the transcript/history overlay and message composer.
- The Familiar send action is positioned inside the lower-right corner of the
  message text field.
- Search result opens and Familiar citation opens use `pdf_page_number` as the
  Grimoire jump target and force single-page mode. When `page_label` differs
  from the PDF page number, labels should show both values, for example
  `PDF page 133 (printed page 132)`.
- Familiar answer text should render headings, lists, tables, bold text, and
  inline code safely instead of displaying markdown as one flat paragraph.

## Sources

- `wiki/topics/project-overview.md`
- `wiki/topics/ai-rag-system.md`
- `assets/ui/README.md`
