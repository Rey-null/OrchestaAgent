# Decisions form — EGM × orchestra-tx

**Status: COMPLETE — answered 2026-11-18.**

These are the calls I did not make for you: they change what "quality" means
for the product, or depend on hardware, accounts and habits I cannot see.
Every answer below is now applied in
[.orchestra/designs/egm_ux_integration.md](.orchestra/designs/egm_ux_integration.md).

---

## D1 — Which agent host actually runs EGM?

> Not delegable: a review only exists if a host can spawn fresh, read-only
> subagents. This decides whether the loop is real or a stub on your device.

**Chosen: Artifacts first; adapt handoff to whichever host is installed later.**

- [x] Artifacts first; handoff adapts later
- [ ] Antigravity CLI (`agy`)
- [ ] Claude Code
- [ ] Codex CLI
- [ ] Another harness; none yet

Effect: the artifact, session and triage layers are built and testable today;
`egm handoff` stays generic and `egm status` reports the review as `blocked`
until a host is present. D4's full-depth default applies from the first real
review.

## D2 — Who owns review truth?

> Not delegable: it is the ethical boundary of the tool.

**Chosen: A — orchestra-tx imports and stores reports; the host reviews.**

- [x] **A** orchestra-tx imports and stores reports; the host reviews
- [ ] **B** orchestra-tx also orchestrates hosts and tracks rounds itself
- [ ] **C** orchestra-tx calls an LLM API directly for review

Effect: no local review path, no API key on the phone, and status wording is
capped at "unreviewed" or "reviewed by <host> at round N". NG1 and D8 follow
from this.

## D3 — Where do designs live?

> Not delegable: visibility changes who reads them and what leaks into git.

**Chosen: `.orchestra/designs/`.**

- [ ] `docs/designs/` (EGM convention)
- [x] `.orchestra/designs/`
- [ ] Custom path from `AGENTS.md`

Effect: this repository's own design set was moved there too — the sitemap, the
design and the review record now live in `.orchestra/designs/`, and every
handoff passes explicit paths to the host.

## D4 — Default review depth and round cap

> Not delegable: it trades minutes and tokens against coverage.

**Chosen: full five-stage pipeline; two consecutive clean rounds; hard stop at five.**

- [x] Full five-stage; two clean rounds; hard stop at five
- [ ] Single quick pass
- [ ] Choose per invocation

Effect: reviews are long, so completion notification, resumable stage state and
Ctrl-C-safe import are requirements rather than nice-to-have.

## D5 — Secrets in briefs and memory

> Not delegable: getting this wrong publishes a key to a reviewer.

**Chosen: redact and name the matched pattern families.**

- [ ] **A** redact silently, report only a count
- [x] **B** redact and name the pattern families that matched
- [ ] **C** refuse to write and exit

Effect: brief and handoff output reports, for example,
`redacted 2 matches: API_KEY, sk-`, so you can audit what reached memory.

## D6 — UI ambition

> Not delegable: it is a product decision, and the phone is the constraint.

**Chosen: plain CLI now; optional `egm board` TUI later.**

- [ ] **A** plain, linear, accessible CLI only
- [x] **B** plain CLI now, optional `egm board` TUI later
- [ ] **C** also render an HTML report

Effect: v1 ships no curses and no alt-screen; `egm board` is a separate opt-in
command and Termux keeps using the plain path.

## D7 — Narrowest supported terminal

> Not delegable: it sets the testing floor and the wrap budget.

**Chosen: 40 columns.**

- [x] 40 columns
- [ ] 60 columns
- [ ] 80 columns

Effect: snapshot tests start at 40; no table may exceed the terminal width.

## D8 — What must never be automated?

> Not delegable: this is your quality-control red line.

**Chosen: three red lines.** The fourth option was not selected, so writing
inside `.orchestra/designs/` remains a product default (always an explicit
command) rather than a hard enforced red line.

- [x] Never mark a design `Approved` without a human
- [x] Never edit design prose
- [x] Never run a review without fresh-context isolation
- [ ] Never write to the design directory without an explicit command

Effect: all three are enforced in code and tests, not just documented.

---

## Defaults applied without a sign-off

| Item | Default | Why it needs no sign-off |
| --- | --- | --- |
| D-grammar | `orchestra-tx egm <verb>` | Matches orchestraCLI's noun-verb shape; one defensible answer |
| D-Termux | clipboard + notification helpers used when present | Additive, skipped automatically when absent; no permission requested |
| D-globals | reuse existing `--ascii`, `--color`, `--json`, `--project` | Avoids a second flag vocabulary |

## Still open

*   **S7** — **Answered 2026-11-18: yes.** `egm status`, `egm brief`,
    `egm review` and `egm check` warn when the project has `AGENTS.md` or
    `CLAUDE.md`, because a reviewer that loads project files is no longer
    fresh-context. The warning never changes an exit code.
*   **D9** — Should the Termux helpers be opt-out (current default) or opt-in?

---

## Sign-off

| Field | Value |
| --- | --- |
| Decisions made by | Project owner, via the in-chat form |
| Date | 2026-11-18 |
| Design status after decisions | **In Review** (review blocked, not approved) |
| Next action | Implement the `egm` artifact/session layers (D1 path), then run a real Goldfish review once a host is installed |
