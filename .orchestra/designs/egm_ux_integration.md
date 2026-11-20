# EGM integration for orchestra-tx

*   **Author:** orchestra-tx maintainers
*   **Status:** In Review
*   **Date:** 2026-11-18

--------------------------------------------------------------------------------

## Overview

orchestra-tx is a Termux-friendly companion for orchestraCLI that already
persists a session plan, a cross-session memory and a generated context file.
This design integrates the **Elephant-Goldfish Model (EGM)** — Google's
open-source spec-driven design and review plugin — into that companion.

The integration has one architectural rule: **orchestra-tx owns artifacts and
session state; the agent host owns fresh-context review.** EGM's verification
value comes from reviewers that never saw the drafting conversation. A tool
that reviews its own draft reproduces the exact bias EGM exists to remove, so
orchestra-tx reads, writes, indexes, renders and triages EGM artifacts, and
delegates the review itself.

Scope of this document is the complete UX/UI contract: every command, every
terminal state, every output mode, every failure mode, on a 40-column Termux
screen and on a 200-column desktop terminal.

--------------------------------------------------------------------------------

## The Problem

EGM produces a set of markdown artifacts and expects a specific loop:
brainstorm → brief → draft → goldfish review → resolve → approve → implement →
drift report. On a desktop harness that loop is coherent. On Termux it breaks
in five specific ways:

1. **No artifact index.** `docs/designs/` is a folder of files. Nothing says
   which design is approved, which is in review, or which has open blockers.
2. **No bridge to the session.** The brief must restate the goal, constraints
   and decisions that orchestra-tx already holds in `plan.json` and
   `memory.jsonl`. Today that is manual copy-paste on a phone keyboard.
3. **Review output is unreadable at 40 columns.** `goldfish_review_report.md`
   is long, nested and severity-bearing. `cat` on a phone loses the structure.
4. **Triage needs a keyboard.** `PROPOSE FIX / CONTEST / ESCALATE / DECLINE`
   is the core human decision of the method, and nothing captures the decision
   in a durable place.
5. **Shell death loses the loop.** Termux kills sessions aggressively; Android
   reclaims the app. There is no resumable state for "which review round am I
   in".

The cost is not cosmetic. A phone user either abandons the design loop or runs
a self-review and trusts it — the failure mode EGM was built to prevent.

--------------------------------------------------------------------------------

## Goals

*   **G1 — Artifact contract.** `orchestra-tx egm` scaffolds, indexes, reads
    and updates EGM artifacts without requiring EGM to be installed.
*   **G2 — Session bridge.** A session plan and its memory produce a complete
    `concepts_brief.md` and can be refreshed without copy-paste.
*   **G3 — Honest handoff.** The tool emits the exact host command and file
    paths for the review, names the required capability (fresh-context,
    read-only subagents), and refuses to fake a review.
*   **G4 — Findings become work.** A `goldfish_review_report.md` imports into
    structured findings, renders readably at 40 columns, and converts triaged
    findings into plan steps and memory entries.
*   **G5 — Durable loop.** Review round, stage and triage decisions survive a
    killed shell; a second concurrent shell cannot corrupt state.
*   **G6 — Complete UX contract.** Every command specifies its human output,
    `--json` output, exit code, empty state, error state, width behaviour,
    colour behaviour, accessibility behaviour and Termux behaviour.
*   **G7 — No new dependencies and no measurable startup regression.** Cold
    start on a mid-range phone stays under 150 ms; the EGM module tree is only
    imported when an `egm` command runs.

## Non-Goals

*   **NG1 — Reimplementing Goldfish review.** No local "AI review". If no
    fresh-context host exists, the command stops with an explanation (see G3).
*   **NG2 — Vendoring EGM.** We do not copy `skills/`, `agents/` or
    `resources/` from the EGM repository. Users install EGM from its canonical
    manifest; we detect it and point at it. Vendoring forks Google's text,
    goes stale silently, and misstates what version reviewed a doc.
*   **NG3 — A full TUI in v1.** No curses, no alt-screen, no pane layout. Linear,
    append-only output that survives `| tee`, screen readers and 40 columns. An
    optional, separate `egm board` may be added later (D6); the plain path stays
    the contract and the only UI tested on Termux.
*   **NG4 — An HTML/web report.** No browser on Termux; `display` and `less`
    cover reading. (Revisit only if a desktop surface is requested.)
*   **NG5 — Harness installation.** We never run `agy plugin install`,
    `claude plugin install` or `pip install` of EGM on the user's behalf.
*   **NG6 — Editing document prose.** We scaffold sections and read status; we
    do not generate or rewrite design prose. That is the Elephant's job.

## Decisions and Open Questions

Locked 2026-11-18 by the human sign-off form (`DECISIONS.md`). These are the
calls that cannot be delegated: they define what "quality" means here, so the
implementation follows them exactly.

| ID | Decision | Chosen | Consequence |
| --- | --- | --- | --- |
| D1 | Review host | Artifacts first; handoff adapts to the host installed later | Artifact and session layers ship now; the review loop reports `blocked` until a host exists |
| D2 | Review truth | orchestra-tx imports and stores reports; the host reviews | No local review path exists; status may say "unreviewed" or "reviewed by X at round N" and nothing stronger |
| D3 | Artifact location | `.orchestra/designs/` | Designs stay off the repo surface; `SITEMAP.md` moves with them; reviewers receive explicit absolute paths |
| D4 | Review depth | Full five-stage; two clean rounds; hard stop at five | Long mobile runs, so completion notification and resume become mandatory, not optional |
| D5 | Secrets | Redact and name the matched pattern families | Briefs and handoffs are auditable; the user learns what reached memory |
| D6 | UI scope | Plain CLI now; optional `egm board` later | v1 has no curses and no alt-screen; the board is a separate opt-in command |
| D7 | Width floor | 40 columns | Wrap budget and snapshot tests start at 40, not 80 |
| D8 | Red lines | No auto-approval; no prose edits; no review without fresh-context isolation | Enforced in code and tests, not only stated in docs |

Settled by default without a sign-off because each has one defensible answer:
command grammar stays `orchestra-tx egm <verb>` (consistent with orchestraCLI's
noun-verb shape); Termux clipboard and notification helpers are used when
present and skipped when absent.

### Still open

*   **S7**: **Answered 2026-11-18 — yes.** The pre-review warning ships in
    `egm status`, `egm brief`, `egm review` and `egm check` when the project has
    `AGENTS.md` or `CLAUDE.md`, and leaves exit codes unchanged.
*   **D9**: Whether Termux API helpers stay opt-out or become opt-in.

--------------------------------------------------------------------------------

## Critical User Journeys (CUJs)

### CUJ 1: First design from a phone

*   **Given**: A project with an active orchestra-tx session and at least one
    plan step; orchestra-cli installed; EGM installed in the agent host.
*   **When**: The user runs `orchestra-tx egm init`, then `egm brief`, then
    `egm handoff`.
*   **Then**: `.orchestra/designs/` exists with `SITEMAP.md`; `concepts_brief.md`
    contains the goal, plan steps and pinned memory; `handoff` prints one
    copy-paste prompt naming the harness command and the brief path; nothing
    was sent anywhere and no review was claimed.

### CUJ 2: Reading a review on a 40-column screen

*   **Given**: `goldfish_review_report.md` produced by the host.
*   **When**: The user runs `orchestra-tx egm review goldfish_review_report.md`
    then `egm report --severity blocker`.
*   **Then**: The report imports into `.orchestra/egm/findings.json`; the
    terminal shows counts by severity and persona, then findings one per block
    wrapped to the real width; blockers are readable without horizontal
    scrolling; `--json` yields the same data.

### CUJ 3: Triage without a mouse

*   **Given**: Imported findings, an interactive terminal.
*   **When**: The user runs `orchestra-tx egm resolve`.
*   **Then**: Each finding shows severity, persona, location and the reviewer's
    claim, then a one-key prompt (`p/c/e/d/s/q`). Each decision appends to
    `.orchestra/egm/triage.json` and a memory entry; `q` preserves progress and
    exits 0; re-running resumes at the first undecided finding.

### CUJ 4: Resume after Android kills the app

*   **Given**: A review loop at round 2, stage "critic".
*   **When**: The user reopens Termux and runs `orchestra-tx egm status`.
*   **Then**: The board shows design, status, round, stage, open findings by
    severity and the next action, all reconstructed from disk; a stale lock is
    detected by PID and age and reported, not silently cleared.

### CUJ 5: CI gate on a design

*   **Given**: A repository where designs are reviewed in CI.
*   **When**: `orchestra-tx egm check .orchestra/designs/feature.md` runs in CI after
    a review report was imported.
*   **Then**: It exits `4` when a `Blocker` or `Major` finding is unsettled, and
    exits `3` when no report was ever imported for that design — never `0` on
    an unverified design. It makes no network call and needs no agent host.

### CUJ 6: Two shells, one project

*   **Given**: Two Termux sessions in the same project.
*   **When**: Both run `egm resolve`.
*   **Then**: The second waits up to the lock timeout (default 5 s), then exits
    `5` with the holder's PID and a retry hint; no state file is torn.

--------------------------------------------------------------------------------

## Technical Plan (Architecture)

Four layers, each independently testable. Only layer 3 needs anything outside
the repository.

```text
+---------------------------------------------------------------+
| 4. Adapter (optional, later)                                   |
|    orchestra-tx as an EGM harness: NOT possible in v1          |
|    (no fresh-context subagent tool in a plain CLI)             |
+---------------------------------------------------------------+
| 3. Handoff      egm/handoff.py, egm/detect.py                  |
|    detect host -> emit prompt + paths -> optionally launch     |
+---------------------------------------------------------------+
| 2. Session      plan.py, memory.py, session.py (existing)      |
|    brief seed, findings as plan steps, triage as memory        |
+---------------------------------------------------------------+
| 1. Artifacts    egm/scaffold.py, artifacts.py, report.py       |
|    .orchestra/designs/, SITEMAP.md, brief, report parse        |
+---------------------------------------------------------------+
| 0. Presentation ui/theme.py, ui/layout.py, ui/stream.py        |
|    width, glyphs, colour, wrapping, progress lines, exit codes |
+---------------------------------------------------------------+
```

### Layer 0 — presentation contract

One module decides every visual question so no command invents its own.

*   **Width**: `COLUMNS` → `shutil.get_terminal_size` → 80. Clamped to
    `[40, 200]`. Never assume 80 in tests; every renderer takes `width`.
*   **Glyphs**: two fixed sets (`unicode`, `ascii`) selected by
    `--ascii`, `LANG=C` or `TERM=dumb`. Severity always carries a word, never a
    glyph alone.
*   **Colour**: 8 basic ANSI codes only (Termux 256-colour support varies).
    `--color=auto|always|never`, honouring `NO_COLOR` and `CLICOLOR=0`.
    Colour never encodes information on its own.
*   **Wrapping**: hard-wrap at width with a two-space hanging indent for
    continuation, so pasted output stays greppable.
*   **Progress**: append-only status lines, no spinner, no cursor movement:
    `[2/5] critic review ........ 3 findings (1 blocker)`. Motion-free by
    default; battery- and screen-reader-friendly.
*   **Exit codes**: `0` ok · `1` state/usage error · `2` bad arguments ·
    `3` prerequisite missing (EGM, harness, artifact) · `4` unsettled blockers
    in `--check` mode · `5` lock timeout. Documented in `USAGE.txt` and tested.

### Layer 1 — artifacts

*   `egm init` creates `<design_dir>/` and appends to `SITEMAP.md` (creates it
    with columns: Document · Status · Date · Components · Description).
*   `egm brief` renders `concepts_brief.md` from the plan, pinned memory and
    the last session summary. It is idempotent: re-running replaces the
    generated block between explicit markers and preserves hand-written text.
*   `egm draft` scaffolds `design_draft.md` with EGM's section skeleton
    (Overview, Problem, Goals, Non-Goals, Open Questions, CUJs, Technical Plan,
    Alternatives, NFRs, Detailed Implementation Plan, Verification Plan) and a
    status header. It writes structure only (NG6).
*   `egm report` parses `goldfish_review_report.md` into findings with
    `severity`, `persona`, `location`, `claim`, `raw`. The parser is tolerant
    (heading-based and bullet-based shapes) and always keeps `raw`, so an
    unparsed line is displayed rather than dropped.

### Layer 2 — session bridge

*   Brief seeding reads: `plan.json` goal + steps + notes, pinned and recent
    memory, last session summary.
*   Imported findings are *not* plan steps automatically. `egm resolve` marks
    decisions; `egm plan-sync` (explicit, reviewable) turns accepted findings
    into plan steps with the finding id in the step note.
*   Finding ids are content hashes of `persona|location|claim`, so re-importing
    a revised report preserves every existing triage decision. Changed findings
    are marked `changed` and keep their previous decision visible until
    re-triaged; new ones are marked `new`. Importing into a design whose status
    is `Approved` moves it to `In Review` with a one-line warning.
*   `egm resolve` requires a TTY. With stdin or stdout redirected it exits `1`
    and prints the `--decide` form instead: no prompt is ever written to a pipe.
*   Every triage decision writes a memory entry tagged `egm,decision` so the
    next session recalls *why* the design changed.

### Layer 3 — handoff

*   `egm detect` looks for EGM in the known harness paths (`~/.gemini/config/
    plugins/egm`, Claude/Cowork plugin dirs, Codex/agents marketplace caches)
    and for host binaries (`agy`, `claude`, `codex`). It reports what it found
    and what it implies; absence of a host is a `3` exit, not a warning.
*   `egm handoff` writes `.orchestra/egm/handoff.md` containing: the design
    path, the brief path, the exact command per detected host (including EGM's
    `/egm:` prefix rule for agy/Claude and the skill-picker note for Codex),
    the required capability statement ("reviewers run in fresh, read-only,
    zero-context subagents"), and a copy-paste block.
*   `--launch` runs the detected binary with the prompt only when the user
    explicitly asks; it never installs anything and never sends a file.

### Command surface

```text
orchestra-tx egm init [--dir DIR] [--force]      scaffold + index
orchestra-tx egm status                          board: design, round, stage, findings
orchestra-tx egm brief [--write]                 seed concepts_brief.md from plan+memory
orchestra-tx egm draft [--brief PATH]            scaffold design_draft.md sections
orchestra-tx egm handoff [--launch]              emit prompt + paths for the host
orchestra-tx egm review REPORT.md                import a goldfish review report
orchestra-tx egm report [--severity S] [--raw]   render imported findings
orchestra-tx egm resolve [--decide D|--all]      triage PROPOSE/CONTEST/ESCALATE/DECLINE
orchestra-tx egm check [DESIGN]                  exit 4 on unsettled Blocker/Major
orchestra-tx egm plan-sync [--dry-run]           accepted findings -> plan steps
orchestra-tx egm drift [DOC|DIR]                 drift findings -> plan steps
```

Every command supports `--json`. Nouns before verbs, matching orchestraCLI's
`pipeline validate` grammar.

### UX/UI inventory (the complete surface)

| # | Surface | Contract |
| --- | --- | --- |
| 1 | Information architecture | `egm` noun group with ten verbs; `egm status` is the always-safe entry point; `usage` lists the loop in order |
| 2 | First run | `egm init` on a repos with no design dir explains the four artifacts it will create, writes nothing without confirmation at a TTY, `--force` for scripts |
| 3 | Empty states | never a bare blank: each command names the next command, e.g. "no designs yet — run `egm init`" |
| 4 | Help | `--help` per verb with one example; `orchestra-tx usage` has an EGM section; `egm` bare prints `status` + the loop order |
| 5 | Human output | severities as words, aligned counts, hanging-indent wrap, no tables wider than the terminal |
| 6 | Machine output | `--json` stable keys (`status`, `design`, `round`, `stage`, `findings[]`, `next`); `--json` never mixes prose into stdout; diagnostics go to stderr |
| 7 | Streaming | report/import emit one JSON object per line with `--jsonl` for pipes |
| 8 | Progress | append-only stage lines `[n/5] stage … result`; `--quiet` suppresses them; no animation |
| 9 | Report reading | `egm report` groups by severity then persona, supports `--severity`, `--persona`, `--raw`, `-r` ranges via `display`, and pages with `-p` |
| 10 | Triage | one-key `p/c/e/d/s/q`, shows finding id first for a screen reader, `--decide` for scripts, resumes at first undecided |
| 11 | Approval gates | one question per gate, no preselected answer, never auto-approve; a gate is never printed if stdin is not a TTY |
| 12 | Errors | `problem → cause → next command`; artifact paths quoted; no stack traces unless `--debug` |
| 13 | Recovery | every state file is written atomically; a corrupt `.orchestra/egm/state.json` is moved aside as `.corrupt-<ts>` and rebuilt, with a warning |
| 14 | Interruption | Ctrl-C exits `130`, keeps imported findings, prints the resume command |
| 15 | Concurrency | project lock, 5 s default wait, exit `5` naming the holder PID |
| 16 | Accessibility | `NO_COLOR`, `--ascii`, `TERM=dumb`, `LANG=C`; no colour-only meaning; no motion; linear reading order; 40-column floor; no horizontal scroll |
| 17 | Termux | width floor 40; `termux-clipboard-set` for the handoff block when present; optional `termux-notification` on review completion; no browser dependency; store stays under `$HOME` |
| 18 | Privacy | brief/handoff redaction before write (`API_KEY`, `TOKEN`, `SECRET`, `PASSWORD`, `PRIVATE KEY`, `ghp_`, `sk-`, `AKIA`) with the match count reported; no telemetry, ever |
| 19 | Performance | EGM modules imported lazily; report import streams line-by-line; cold start < 150 ms; report render < 100 ms for 2 000 findings |
| 20 | Language | plain English; a six-line glossary (Elephant, Goldfish, Brief, SITEMAP, CUJ, Heilmeier) in `usage`; ISO-8601 dates |
| 21 | Discoverability in shell | `completions/orchestra-tx.bash` completing verbs, flags, design paths and finding ids |
| 22 | Trust calibration | `handoff` and `report` state the verification limit in one line: a review is not a test and not a human approval |

### State files

```text
<project>/.orchestra/egm/
  state.json      {design, status, round, stage, updated}
  findings.json   [{id, severity, persona, location, claim, raw, decision}]
  triage.json     {finding_id: decision, decided_at, note}
  handoff.md      generated prompt block
```

All are derived from artifacts plus the current session; deleting the directory
loses triage history only, never a design document.

--------------------------------------------------------------------------------

## Alternatives Considered

### Alternative A: Vendor the EGM plugin inside orchestra-tx

*   **Pros**: One install; guaranteed versions; works offline.
*   **Cons**: Forks Google's skill and persona text; upstream changes go
    unnoticed; the plugin would claim a review methodology it does not own;
    Apache-2.0 notices multiply.
*   **Reason for Rejection**: Rejected by author: silent drift in review text is
    a quality failure, and EGM's own docs warn that partial installs break the
    skills. We detect and point at the canonical install instead.

### Alternative B: Build a local reviewer (call an LLM API directly)

*   **Pros**: Works with no agent host; one command; no handoff.
*   **Cons**: Requires the user's API key in a Termux environment; the review
    runs in the same process that holds the drafting context, so isolation is
    unverifiable; token cost per review; contradicts NG1 and EGM's premise.
*   **Reason for Rejection**: Rejected by author: an unverifiable review is worse
    than a clearly unavailable one.

### Alternative C: Thin wrapper that shells out to the agent CLI only

*   **Pros**: Smallest possible code; always the host's semantics.
*   **Cons**: No artifact index, no brief seeding, no findings model, no
    triage persistence, no resume — i.e. none of G1, G2, G4, G5.
*   **Reason for Rejection**: Kept as the `handoff --launch` escape hatch inside
    the chosen approach, not as the whole design.

### Alternative D: Do nothing; use EGM natively on desktop

*   **Pros**: Zero maintenance; upstream UX.
*   **Cons**: The phone remains unable to read or triage a report or resume a
    loop; designs still drift from plan and memory.
*   **Reason for Rejection**: Acceptable fallback for desktop users; fails the
    Termux premise of the product.

--------------------------------------------------------------------------------

## Non-Functional Requirements

*   **Security & Privacy**: no network calls in any `egm` command except the
    user-requested `--launch`; redaction before writing briefs, naming the
    matched pattern families (D5); store under
    `$ORCHESTRA_TX_HOME`, never `/sdcard`; report files are read-only inputs.
*   **Performance & Latency**: cold start < 150 ms; import streams; render
    budget 100 ms / 2 000 findings; no polling loops, so no battery drain.
*   **Rollout & Rollback**: opt-in via `egm init`; no existing command changes
    behaviour; rollback is `rm -rf .orchestra/egm` plus removing
    `.orchestra/designs/SITEMAP.md`; the plan/memory schema is unchanged.
*   **Compatibility**: Python 3.9+, Termux aarch64, 40-column terminals,
    `LESS=FRX`-style pagers, `NO_COLOR`-compliant environments.

### Additional Resources

*   EGM repository: <https://github.com/google/elephant-goldfish-model>
*   EGM review protocol: `docs/designs/review.md` in that repository
*   EGM harness limits: `docs/harnesses.md` (fresh-context requirements,
    known instruction leaks on Codex and Antigravity)
*   `PLAN.md` in this repository (session plan this design extends)

### Future Improvements

*   **The idea**: an optional `egm board` full-screen view for desktop users.
*   **The idea**: a `--watch` mode that re-imports a report directory when the
    host writes a new review.
*   **The idea**: multi-user review attribution if teams share a repo.

--------------------------------------------------------------------------------

## Detailed Implementation Plan

### Target Files to Create/Modify

#### 1. `orchestra_tx/egm/__init__.py` (Create)

*   **Type / Scope**: Python package marker.
*   **Proposed Changes**: expose `__all__` for lazy imports; no side effects, so
    `import orchestra_tx.cli` does not pay for EGM code.

#### 2. `orchestra_tx/ui/theme.py` (Create)

*   **Type / Scope**: Presentation primitives.
*   **Proposed Changes**: `color_mode(argv_env) -> str`, `glyphs(ascii_only,
    dumb) -> dict`, `paint(text, role, mode) -> str`, `wrap(text, width,
    indent) -> list[str]`. Single source for every glyph and colour decision.

#### 3. `orchestra_tx/ui/layout.py` (Create)

*   **Type / Scope**: Width and blocks.
*   **Proposed Changes**: `terminal_width(clamp=(40, 200))`, `block(title,
    body, width)`, `key_value(rows, width)`, `severity_label(level)`.

#### 4. `orchestra_tx/ui/stream.py` (Create)

*   **Type / Scope**: Progress and machine output.
*   **Proposed Changes**: `stage(index, total, name, result)`, `JsonlWriter`,
    `diagnostic(msg)` (stderr), `ExitCode` constants.

#### 5. `orchestra_tx/egm/scaffold.py` (Create)

*   **Type / Scope**: Artifact creation.
*   **Proposed Changes**: `init(project, directory, force) -> Report`,
    `ensure_sitemap(path)`, `append_sitemap(path, entry)`, `design_status(path)
    -> str` reading the `**Status:**` header, `list_designs(directory)`.

#### 6. `orchestra_tx/egm/artifacts.py` (Create)

*   **Type / Scope**: Document rendering.
*   **Proposed Changes**: `render_brief(plan, memories, session) -> str` with
    `<!-- orchestra-tx:generated:start/end -->` markers; `scaffold_draft(title,
    brief_sections) -> str` emitting the EGM section skeleton; `redact(text) ->
    (text, count)`.

#### 7. `orchestra_tx/egm/report.py` (Create)

*   **Type / Scope**: Review parsing and rendering.
*   **Proposed Changes**: `parse_report(text) -> list[Finding]` (dataclass:
    id, severity, persona, location, claim, raw); tolerant to heading and
    bullet shapes; `render_findings(findings, width, severity_filter,
    persona_filter, raw) -> str`; `summarize(findings) -> dict`.

#### 8. `orchestra_tx/egm/state.py` (Create)

*   **Type / Scope**: Durable loop state.
*   **Proposed Changes**: `load_state/save_state` (atomic, corrupt-file
    quarantine), `load_findings/save_findings`, `decide(finding_id, decision,
    note)`, `next_undecided(findings)`, `stale_lock(pid, age)`.

#### 9. `orchestra_tx/egm/detect.py` (Create)

*   **Type / Scope**: Host and EGM discovery.
*   **Proposed Changes**: `find_egm(dirs) -> Optional[dict]`,
    `find_harness() -> Optional[dict]` for `agy`/`claude`/`codex`,
    `capabilities(harness) -> dict` (fresh_context: bool, note: str).

#### 10. `orchestra_tx/egm/handoff.py` (Create)

*   **Type / Scope**: Host handoff.
*   **Proposed Changes**: `render_handoff(design, brief, harness) -> str`
    including the exact command per host, the isolation requirement and the
    trust-calibration line; `write_handoff(project, text)`; `launch(harness,
    prompt, cwd)` used only by `--launch`.

#### 11. `orchestra_tx/egm/commands.py` (Create)

*   **Type / Scope**: Verb handlers.
*   **Proposed Changes**: one function per verb returning an exit code;
    `resolve()` implements the one-key loop with resume; `plan_sync()` maps
    accepted findings to `plan.add()` with the finding id in the note.

#### 12. `orchestra_tx/cli.py` (Modify)

*   **Type / Scope**: Argument surface.
*   **Proposed Changes**: add the `egm` subparser group with ten verbs, common
    flags (`--json`, `--jsonl`, `--quiet`, `--debug`, `--color`), a lazy import
    of `orchestra_tx.egm.commands` inside the handler, and an `egm` branch in
    the bare-command board.

#### 13. `orchestra_tx/data/USAGE.txt` (Modify)

*   **Type / Scope**: Reference text.
*   **Proposed Changes**: add the EGM loop (ordered), state files, exit-code
    table, glossary, Termux tips (`termux-clipboard-set`, notifications) and
    the isolation warning.

#### 14. `orchestra_tx/data/templates/` (Create)

*   **Type / Scope**: Bundled templates.
*   **Proposed Changes**: `design_doc.md` (EGM skeleton), `concepts_brief.md`,
    `review_report.md` (format we parse and recommend to hosts), all shipped as
    package data.

#### 15. `completions/orchestra-tx.bash` (Create)

*   **Type / Scope**: Shell UX.
*   **Proposed Changes**: complete verbs, per-verb flags, `.orchestra/designs/*.md`,
    finding ids for `resolve`.

#### 16. `.orchestra/designs/SITEMAP.md` (Create, present)

*   **Type / Scope**: Design index.
*   **Proposed Changes**: columns Document · Status · Date · Components ·
    Description; first row for this document.

#### 17. `tests/test_egm_artifacts.py`, `tests/test_egm_report.py`, `tests/test_egm_resolve.py`, `tests/test_egm_ui.py` (Create)

*   **Type / Scope**: Unit and snapshot tests.
*   **Proposed Changes**: fixtures under `tests/fixtures/egm/` including a real
    40-column report, a malformed report, and a corrupt `state.json`; snapshot
    assertions at widths 40/80/120 with colour on and off.

#### 18. `PLAN.md` (Modify)

*   **Type / Scope**: Session plan.
*   **Proposed Changes**: add the EGM integration phase and link this design.

### Verification Plan

*   **Build**: `python3 -m compileall orchestra_tx` (no new dependencies).
*   **Unit tests**: `python3 -m unittest discover -s tests` — parsers, triage
    state machine, redaction, width/glyph/colour matrix, exit codes.
*   **Snapshot tests**: renderers at 40/60/80/120 columns, `NO_COLOR` and
    `TERM=dumb`, asserting no line exceeds the width.
*   **CLI end-to-end**: temp `ORCHESTRA_TX_HOME` and temp project; run
    `egm init → brief → draft → review(fixture) → report → resolve --decide →
    plan-sync → status`; assert exit codes `0/1/3/4/5`.
*   **Concurrency**: two processes on `egm resolve`; assert one exits `5`.
*   **Crash safety**: kill during import; assert prior findings intact and the
    corrupt state quarantined.
*   **Manual Termux**: 40-column portrait, soft keyboard only, `LANG=C`,
    `TERM=xterm-256color`; clipboard and notification helpers present/absent.
*   **Accessibility review**: linear reading order, no motion, no colour-only
    meaning; confirm with `--ascii --no-color` on a screen reader.

--------------------------------------------------------------------------------

<!-- Provenance: Indicates initial structural drafting via EGM. -->

*Drafted with EGM*
