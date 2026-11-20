# Goldfish review record — egm_ux_integration

*   **Target:** [egm_ux_integration.md](egm_ux_integration.md)
*   **Date:** 2026-11-18
*   **Status:** BLOCKED — no fresh-context subagent host in this environment
*   **Verdict:** NOT REVIEWED by Goldfish. Do not treat this document as approved.

--------------------------------------------------------------------------------

## 1. Goldfish review attempt

The design's own rule (G3, NG1) is that a review only counts when it runs in
fresh, read-only, zero-context subagents. This session has no such host: the
available agent delegation surface exposes only a web-research agent, which
cannot read the repository and cannot be verified as context-isolated.

Running a same-context "review" here would produce exactly the confirmation
bias EGM exists to remove, so it was not done. Per the design's CUJ 5 and exit
code `3`, the correct result is a blocked review, reported as blocked.

### What is required to unblock

Run one of the following in a harness that supports fresh subagents, then
import the report with `orchestra-tx egm review <report.md>`:

| Harness | Command |
| --- | --- |
| Antigravity CLI | `/egm:egm-review .orchestra/designs/egm_ux_integration.md` |
| Claude Code | `/egm:egm-review .orchestra/designs/egm_ux_integration.md` |
| Codex CLI | select `egm-review` from the skill picker, then pass the path |

Required capability, to be stated in the review request: reviewers must run
with no parent conversation, no project instruction files if the host allows
excluding them, and read-only tools.

### Known limits to record with any future review

*   Codex CLI 0.166.0 has been reported to supply project and user `AGENTS.md`
    to reviewers despite `fork_turns: "none"`.
*   Antigravity CLI has been reported to leak project `AGENTS.md` and
    `GEMINI.md` into reviewer context.
*   This repository's `AGENTS.md`/`CLAUDE.md` (if added later) must therefore
    be treated as potentially visible to reviewers, and must not contain the
    answers the review is meant to test.

--------------------------------------------------------------------------------

## 2. Author self-review (explicitly NOT a Goldfish review)

Performed by the drafting context, so it carries confirmation bias. Recorded
because the findings are concrete and were applied. It does not substitute for
the review above.

| # | Finding | Severity | Resolution |
| --- | --- | --- | --- |
| S1 | `egm review --check` conflated importing a report with running a review; CI on a headless host has no report to run and no host to spawn, making the command's contract ambiguous. | Major | Applied: split into `egm review REPORT.md` (import) and `egm check [DESIGN]` (gate). CUJ 5 rewritten to use `check`. |
| S2 | Finding identity was unspecified. Re-importing a revised report would have orphaned triage decisions or duplicated findings. | Major | Applied: content-hash ids of `persona|location|claim`; re-import preserves decisions, marks `changed`/`new`. |
| S3 | Importing a report into an `Approved` design left the status misleading. | Minor | Applied: import downgrades `Approved` to `In Review` with a warning. |
| S4 | `egm resolve` is an interactive one-key loop but the non-TTY path was only implied. | Minor | Applied: without a TTY it exits `1` and prints the `--decide` form; no prompt is ever printed to a pipe. |
| S5 | The `--ascii` flag was listed as new in the EGM designs while the plugin already has a global `--ascii`. | Nit | Applied: the design now reuses the existing global flags rather than defining EGM-specific ones. |
| S6 | "Every aspect of UX/UI" is a claim that cannot be verified by a list. | Major | Open: needs a human check against the 22-row inventory, and a review by a fresh reviewer against the real Termux screen. |
| S7 | The design assumes hosts can exclude instruction files; that assumption is known to fail on two harnesses. | Major | Open: confirm the trust-calibration line is strong enough, or add a pre-review warning when a project `AGENTS.md` exists. |

--------------------------------------------------------------------------------

## 3. Triage state

| Decision | Findings |
| --- | --- |
| PROPOSE FIX (applied) | S1, S2, S3, S4, S5 |
| ESCALATE (human decides) | S6, S7 |
| CONTEST | none |
| DECLINE | none |

## 4. Next action

1. ~~Human answers `DECISIONS.md`~~ — done 2026-11-18; decisions D1–D8 are
   locked in the design doc.
2. Run the real Goldfish review in a supported harness.
3. Re-import and triage; a design becomes `Approved` only after two clean
   rounds and a human sign-off.

*This record was produced without a Goldfish review. It must not be cited as
one.*
