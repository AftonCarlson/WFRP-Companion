I need an implementation plan for the following system:

\[SYSTEM NAME / SHORT DESCRIPTION\]

Additional context:  
\- repo / codebase: \[REPO OR PROJECT NAME\]  
\- primary module(s): \[FILES / MODULES / SUBSYSTEMS\]  
\- external systems involved: \[SHOTGRID / POSTGRES / STRIPE / INTERNAL SERVICES / NONE\]  
\- known pain points or user-reported failures: \[OPTIONAL\]  
\- platform / runtime constraints: \[OPTIONAL\]

Your job is to produce a plan with a deep level of detail, execution-readiness, and architectural rigor.

This is not a brainstorming doc. It is an execution plan for a live codebase.

\#\# Required Standards

1\. Base the plan on:  
\- current live code  
\- current compiled wiki / project docs  
\- relevant design docs / ADRs / specs  
\- official documentation for any third-party or external integration the system depends on

2\. Do NOT use earlier architectural plans or stale planning docs as architectural input unless I explicitly ask you to compare against them.

3\. Do NOT give generic advice. Tie every important claim to:  
\- a real live-code problem  
\- a real integration constraint  
\- or a real operational requirement

4\. Name concrete files, modules, endpoints, tables, fields, states, and integration entities where relevant.

5\. If the system involves workflow/lifecycle state, design an explicit app-owned source of truth. Do not leave ownership split across frontend inference, external systems, and incidental database fields.

6\. Prefer a simple explicit relational/stateful design over framework-heavy orchestration unless the complexity is truly necessary.

7\. Distinguish clearly between:  
\- target steady-state architecture  
\- temporary migration/compatibility scaffolding  
\- rollout-only operational steps

8\. Call out what should NOT be built.

9\. The plan must be detailed enough that an implementation agent could execute it phase by phase without inventing major missing decisions.

10\. Do not make subagent-driven execution mandatory by default. If the work needs independent review or parallel subagents, state why, define the acceptable review paths, and include lifecycle hygiene: bounded waits, sequential cleanup of completed agents, and a fallback such as CodeRabbit or a Codex background thread when subagent spawning is unavailable.

\#\# Output Format

Produce the plan with these sections.

\#\#\# 1\. Source Boundary  
State exactly what sources the plan is based on.  
Explicitly say what sources are intentionally excluded as architectural input.

\#\#\# 2\. Current Live-Code Diagnosis  
Diagnose the current implementation.  
List the most important live-code problems in concrete terms.  
Explain where ownership, concurrency, data modeling, integration, or UX behavior are currently wrong or fragile.

\#\#\# 3\. Architecture Decision  
State the recommended architecture clearly.  
Explain why it is the right fit for this codebase and problem.  
Also state what alternative approaches should be avoided and why.

\#\#\# 4\. Target State Model  
If this system has workflow/lifecycle state, provide a target state machine.  
Use a Mermaid state diagram when useful.  
If it does not need a formal state machine, say so explicitly and provide the equivalent lifecycle/ownership model instead.

\#\#\# 5\. Target Architecture Diagram  
Provide a Mermaid architecture diagram showing:  
\- frontend/user-facing surfaces  
\- API/backend responsibilities  
\- persistence/model ownership  
\- external systems/integrations  
\- async workers/outbox/orchestration if applicable

\#\#\# 6\. Proposed Data Model / Contracts  
Define the target persistence model and/or core contracts.  
If relevant, include:  
\- tables  
\- important columns/fields  
\- enums  
\- indexes  
\- uniqueness constraints  
\- partial unique constraints  
\- idempotency keys  
\- append-only event tables  
\- explicit relationship tables

Be clear about what is immutable snapshot data vs live workflow state vs explicit target/linkage data.

\#\#\# 7\. External Integration Design  
For every important external system:  
\- define the source of truth boundary  
\- define exactly what gets written/read/synchronized  
\- define idempotency strategy  
\- define retry behavior  
\- define what success/failure means  
\- define what should happen if the external system is down

If there are external entity types, field names, statuses, or relationship structures, verify them against official docs and use the real terms.

\#\#\# 8\. Core Flow Design  
Spell out the important flows step by step.  
Examples:  
\- create flow  
\- classification/decision flow  
\- approval flow  
\- assignment flow  
\- review flow  
\- completion flow  
\- retry/reopen flow  
\- migration/backfill flow

For each important flow, call out:  
\- transaction boundaries  
\- concurrency/atomicity guards  
\- where external side effects happen  
\- what gets written first  
\- what gets deferred to outbox/worker logic  
\- how race conditions are prevented

Use SQL-style conditional-update examples when that helps clarify guarded transitions.

\#\#\# 9\. UX / Surface Behavior  
Define how the system should appear across surfaces.  
If relevant, include:  
\- dashboard behavior  
\- banners/notices  
\- queues  
\- history surfaces  
\- assignee views  
\- reviewer views  
\- admin/ops surfaces

If there are state-to-surface rules, provide a table.  
Be explicit about what should be visible where, and what should not.

\#\#\# 10\. Implementation Sequence  
Break the refactor into PR-sized phases.  
Each phase should have:  
\- scope  
\- what changes  
\- what intentionally does not change yet  
\- required tests  
\- rollout/compatibility notes

Make the phases realistic and ordered so they can land safely.

\#\#\# 11\. Testing Requirements  
Define testing as part of implementation, not follow-up cleanup.  
Specify the minimum required categories, such as:  
\- backend state-machine/transition tests  
\- validation/auth tests  
\- integration tests  
\- frontend/read-model tests  
\- migration/backfill tests  
\- worker/outbox tests  
\- concurrency tests

If a PR changes behavior, require tests in that PR.

\#\#\# 12\. Verification Matrix  
Provide a concrete checklist of scenarios that must pass.  
These should be end-to-end enough that someone can verify the refactor actually matches the intended behavior.

\#\#\# 13\. Migration / Compatibility / Cleanup Strategy  
If the system needs migration or compatibility code:  
\- define what temporary scaffolding is needed  
\- define how long it should live  
\- define how to know when it is safe to remove  
\- define what should be removed later in a cleanup pass  
\- distinguish code cleanup from schema deletion

If migration/backfill is needed, define:  
\- safe cases  
\- ambiguous cases  
\- quarantine/manual-review cases  
\- how those cases surface operationally

\#\#\# 14\. Operational Rollout Notes  
If deployment needs operational care, include it.  
Examples:  
\- DB rollout order  
\- manual SQL apply vs migration tool  
\- firewall/networking considerations  
\- outbox worker enablement  
\- feature flags  
\- environment cutover sequencing  
\- replay/recovery mechanics

\#\#\# 15\. ADR / Platform Alignment  
Explain how the plan fits the broader platform/ADR direction.  
Call out any tensions explicitly.  
If something is a transitional compromise because the current platform is not at the target ADR shape yet, say so.

\#\#\# 16\. Non-Goals / Guardrails / Open Questions  
Include:  
\- what this refactor should not try to solve  
\- what future work it should not accidentally absorb  
\- any open questions that genuinely need decision-making  
\- any assumptions that are being made

\#\# Quality Bar

The plan is not done unless it:  
\- identifies the live-code ownership problems concretely  
\- defines a single clear source of truth  
\- removes inference where explicit relationships/state are needed  
\- handles concurrency and retries intentionally  
\- defines external integration behavior precisely  
\- maps state to user-facing surfaces clearly  
\- sequences implementation in safe PR-sized phases  
\- includes testing and rollout requirements  
\- distinguishes steady-state architecture from temporary migration scaffolding

If any part is ambiguous, resolve it or explicitly call it out. Do not hand-wave.

Use direct engineering prose. Optimize for clarity, specificity, and execution-readiness.
