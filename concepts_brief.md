# Concepts Brief — EGM integration for orchestra-tx

* Status: Draft for review
* Date: 2026-11-18
* Method: Elephant-Goldfish Model (EGM), `egm-brainstorm` stage

## The idea in one paragraph

orchestra-tx already carries the two things EGM says an AI needs and most
projects lose: a durable plan and a durable memory. EGM supplies the discipline
that uses them — draft a spec with full context, then let fresh-context
reviewers find what the draft assumes. Integrating the two means orchestra-tx
becomes the *artifact and session layer* for EGM on a phone: it scaffolds
`.orchestra/designs/`, seeds a brief from plan and memory, hands the design off to
whatever agent host can spawn fresh reviewers, then reads the review report
back into the plan and memory. orchestra-tx never claims to review anything
itself.

## Why now

* EGM is markdown + agent skills. On Termux the *artifacts* survive but the
  *workflow* is scattered across an agent app, a file browser and `cat`.
* orchestra-tx already has plan, memory, context, display, sessions and a
  Termux-safe installer. The missing piece is the design/review loop.
* Without an artifact index, a phone user cannot tell which documents are
  approved, in review, or drifting.

## The three surfaces worth designing

1. **Artifacts** — `.orchestra/designs/*.md`, `SITEMAP.md`, `concepts_brief.md`,
   `design_draft.md`, `goldfish_review_report.md`. Deterministic, testable,
   useful with no agent installed.
2. **Session** — plan steps become design phases; memory becomes the
   Elephant's long-term context; review findings become plan work.
3. **Handoff** — the only part that needs an agent host. Detect the harness,
   emit an exact prompt and file paths, never fake a review.

## Constraints that shape it

* Termux: 40-column screens, no browser, no compiled wheels, battery matters.
* EGM review isolation is a hard requirement: a same-context "review" is worse
  than no review because it manufactures false confidence.
* Zero runtime dependencies must survive. No TUI framework, no Rich, no curses.
* Human approval gates stay human: one question at a time, no default answer.

## Tensions surfaced

| Tension | Options | Notes |
| --- | --- | --- |
| Who reviews? | orchestra-tx | agent harness | Requires a host with fresh subagents; not delegable |
| Where do designs live? | `.orchestra/designs/` (decided) | public `docs/` | Hidden keeps the repo surface clean; the handoff passes explicit absolute paths |
| How much UI? | plain CLI | TUI / HTML report | Phone screens and screen readers favour plain, linear output |
| Ship EGM inside the plugin? | vendor | depend | Vendoring forks Google's text and goes stale; depend keeps one source of truth |

## Definition of done for the first slice

A phone user can scaffold a design directory, turn an active plan into a brief,
hand off to their agent, import the report, triage findings without a mouse,
and resume after the shell is killed — with `--json` and exit codes that a CI
job can use.
