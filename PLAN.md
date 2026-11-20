# Plan — orchestra-tx: orchestraCLI plugin for Termux

Goal: give orchestraCLI a Termux-safe companion that carries a session plan, a
persistent memory across shell sessions, and a readable text-file display.

## Steps

- [x] 1. Inspect the workspace and the existing orchestraCLI ecosystem
- [x] 2. Define the plugin surface (`init`, `plan`, `memory`, `session`, `display`, `run`, `doctor`, `usage`)
- [x] 3. Implement storage: per-project store, atomic writes, advisory lock, JSONL memory
- [x] 4. Implement the persistent session plan (single active step, notes, progress)
- [x] 5. Implement persistent memory (project + global scopes, tag search, pin, export)
- [x] 6. Implement session lifecycle and `.orchestra/context.md` generation
- [x] 7. Implement the text-file display (line numbers, ranges, wrap, pager, binary guard)
- [x] 8. Wire the CLI, Termux doctor checks and the bundled `USAGE.txt` reference
- [x] 9. Add the Termux installer and verify every command runs on Python 3.9+
- [x] 10. Record the result in memory so the next session starts where this one ended

## Design decisions

- **Pure standard library.** Termux has no NDK toolchain for compiled Python
  wheels; avoiding Rich/Click keeps `pip install` instant and offline-safe.
- **State outside the project.** The store lives in `$ORCHESTRA_TX_HOME`
  (`~/.local/share/orchestra-tx`) so state survives `git clean` and re-clones,
  keyed per project by name plus a short path hash.
- **Append-only memory, atomic plan.** Memory is JSONL (a torn line loses one
  entry, never the store); the plan is a small JSON doc replaced atomically
  under an `flock`.
- **Honest wrapper.** `orchestra-tx run` does not pretend to change
  orchestraCLI's flags; it exports `ORCHESTRA_TX_*` variables and points at
  `.orchestra/context.md`, which scripts or prompts can consume.

## Usage

```bash
orchestra-tx init --goal "Ship the pipeline"
orchestra-tx plan new "Ship the pipeline" --step "Validate YAML" --step "Run it"
orchestra-tx session start
orchestra-tx memory add "API key lives in ~/.orchestra.env" -t auth
orchestra-tx run -- pipeline validate pipeline.yaml
orchestra-tx display README.txt -r 1-40
orchestra-tx session end --summary "Validated the pipeline; next: schedule it"
orchestra-tx usage
```

## Phase 2 — EGM integration (in progress)

Applying the Elephant-Goldfish Model to this project's UX/UI surface.

- [x] 11. Concepts brief (`concepts_brief.md`) and design spec
      (`.orchestra/designs/egm_ux_integration.md`)
- [x] 12. UX/UI inventory covering 22 surfaces, with a contract per surface
- [x] 13. Decisions form (`DECISIONS.md`) for the calls that cannot be delegated
- [ ] 14. Goldfish review — **blocked**: no fresh-context subagent host in this
      session. Recorded in
      `.orchestra/designs/egm_ux_integration_goldfish_review.md`; must run in a
      supported harness before the design can be `Approved`
- [x] 13a. Decisions D1–D8 locked (`DECISIONS.md`): artifacts-first host, import-only
      review truth, `.orchestra/designs/`, full five-stage depth, named-pattern
      redaction, plain CLI + future board, 40-column floor, three red lines
- [ ] 15. Implement the `egm` command group once decisions land
      (done: `init`, `status`, `brief`, `review`, `report`, `resolve`,
      `check`, with `--json`, 40-column rendering, tests, the
      AGENTS.md/CLAUDE.md pre-review warning and one-key triage; `draft`,
      `handoff`, `plan-sync`, `drift` remain)
- [ ] 16. Import and triage the real review, then sync findings into plan steps

Design status: **In Review**. Verification limits: the review is blocked, and
no implementation has started. Decided 2026-11-18: artifacts first (D1),
import-only review truth (D2), `.orchestra/designs/` (D3), five-stage depth
(D4), named-pattern redaction (D5), plain CLI now (D6), 40-column floor (D7),
three enforced red lines (D8).
