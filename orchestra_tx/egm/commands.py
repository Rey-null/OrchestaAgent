"""The egm verbs implemented so far: init, status, brief, review, report, resolve, check."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from .. import display, memory, plan as plan_mod, session as session_mod, store
from ..ui import layout, stream, theme
from . import artifacts, report, scaffold, state as state_mod

INSTRUCTION_FILES = ("AGENTS.md", "CLAUDE.md")
BRIEF_NAME = "concepts_brief.md"
LOOP = (
    "init -> brief -> review -> report -> resolve -> check -> approve"
)
TRUST_LINE = "A review is not a test and is not a human approval."
DECISION_HINT = "p=propose c=contest e=escalate d=decline s=skip q=quit"
LOCK_WAIT = 5.0

VERBS = {}


def _project(args) -> Optional[str]:
    return getattr(args, "project", None)


def _json(args) -> bool:
    return bool(getattr(args, "json", False))


def _width(args) -> int:
    return layout.resolve_width(getattr(args, "width", None))


def _mode(args) -> str:
    return theme.color_mode(getattr(args, "color", None))


def _emit(text: str = "") -> None:
    sys.stdout.write(text + "\n")


def _emit_lines(lines: Sequence[str]) -> None:
    for line in lines:
        sys.stdout.write(line + "\n")


def _dump(payload) -> None:
    sys.stdout.write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


def _error(message: str) -> None:
    sys.stderr.write("orchestra-tx: " + message + "\n")


def _resolve(project: Optional[str], value) -> Path:
    path = Path(str(value)).expanduser()
    if not path.is_absolute():
        path = store.project_root(project) / path
    return path


def _rel(path, project: Optional[str]) -> str:
    try:
        return Path(os.path.relpath(str(Path(path).resolve()), str(store.project_root(project)))).as_posix()
    except (OSError, ValueError):
        return str(path)


def _norm(path: str) -> str:
    return os.path.normpath(str(path or "")).lstrip("./")


def _isolation_files(project: Optional[str]) -> List[str]:
    root = store.project_root(project)
    return [name for name in INSTRUCTION_FILES if (root / name).is_file()]


def _isolation_message(files: Sequence[str]) -> str:
    if not files:
        return ""
    if len(files) == 1:
        return (
            "project has {}; a reviewer may load it, so the review is only "
            "fresh-context if it is excluded".format(files[0])
        )
    names = ", ".join(files[:-1]) + " and " + files[-1]
    return (
        "project has {}; a reviewer may load them, so the review is only "
        "fresh-context if they are excluded".format(names)
    )


def _warning_lines(message: str, width: int, mode: str) -> List[str]:
    if not message:
        return []
    prefix = theme.paint("warning:", "warn", mode) + " "
    body = theme.wrap(message, max(12, width - len("warning: ")), indent=0, hang=0)
    if not body:
        return []
    return [prefix + body[0]] + [" " * len("warning: ") + piece for piece in body[1:]]


def _isolation_lines(files: Sequence[str], width: int, mode: str) -> List[str]:
    return _warning_lines(_isolation_message(files), width, mode)


def _add_warnings(lines: List[str], messages: Sequence[str], width: int, mode: str) -> None:
    for message in messages:
        if message:
            lines.append("")
            lines.extend(_warning_lines(message, width, mode))


def _decisions(findings: Sequence[dict], triage: dict) -> List[dict]:
    rows: List[dict] = []
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        row = dict(finding)
        row["decision"] = report.decision_of(triage.get(row.get("id"))) or report.decision_of(row.get("decision"))
        rows.append(row)
    return rows


def _finding_line(stats: dict) -> str:
    if not stats["total"]:
        return "none imported"
    text = "{} imported, {} open".format(stats["total"], stats["open"])
    if stats["settled"]:
        text += ", {} settled".format(stats["settled"])
    return text


def _severity_line(stats: dict) -> str:
    parts = []
    for name in report.SEVERITIES:
        count = stats["by_severity"].get(name, 0)
        if count:
            parts.append("{} {}".format(count, name))
    return ", ".join(parts) or "none"


def _status_word(project: Optional[str], state: dict, design: str) -> str:
    if not state_mod.initialized(project):
        return "uninitialized"
    if not design:
        return "no design"
    return scaffold.design_status(_resolve(project, design)) or "unknown"


def _triage_next(findings: Sequence[dict]) -> str:
    return "orchestra-tx egm resolve" if report.unsettled(findings) else "orchestra-tx egm check"


def _next_action(ready: bool, design: str, findings: Sequence[dict], designs: Sequence[Path]) -> str:
    if not ready:
        return "orchestra-tx egm init"
    if not design:
        return "orchestra-tx egm review REPORT.md --design PATH" if designs else "orchestra-tx egm brief --write"
    if not findings:
        return "orchestra-tx egm brief"
    return _triage_next(findings)


def _wrap_document(text: str, width: int) -> List[str]:
    lines: List[str] = []
    for line in str(text).splitlines():
        if not line.strip():
            lines.append("")
            continue
        stripped = line.lstrip(" ")
        indent = min(len(line) - len(stripped), 8)
        lines.extend(theme.wrap(stripped, width, indent=indent, hang=2))
    return lines


# --------------------------------------------------------------------------- #
# verbs
# --------------------------------------------------------------------------- #

def egm_init(args) -> int:
    project = _project(args)
    width = _width(args)
    mode = _mode(args)
    target = getattr(args, "dir", None)
    force = bool(getattr(args, "force", False))
    interactive = sys.stdin.isatty() and sys.stdout.isatty() and not _json(args)
    if interactive and not force:
        _error("EGM init will create the design directory, SITEMAP.md and .orchestra/egm/state.json")
        sys.stderr.write("Create them here? [Y/n] ")
        try:
            answer = sys.stdin.readline().strip().lower()
        except KeyboardInterrupt:
            return stream.ExitCode.INTERRUPT
        if answer not in ("", "y", "yes"):
            _emit("nothing written")
            return stream.ExitCode.STATE

    result = scaffold.init(project, target, force=force)
    files = _isolation_files(project)
    payload = dict(result)
    payload["isolation"] = {"files": files, "message": _isolation_message(files)}
    if _json(args):
        _dump(payload)
        return stream.ExitCode.OK

    rows = [
        ("designs", result["design_dir"]),
        ("sitemap", result["sitemap"]),
        ("state", result["state"]),
    ]
    if result["created"]:
        summary = "created {} path(s); existing files were left alone".format(len(result["created"]))
    else:
        summary = "nothing new; every path already existed"
    lines = ["EGM initialized", ""] + layout.key_value(rows, width, mode)
    lines.append("")
    lines.extend(theme.wrap(summary, width, indent=0, hang=2))
    warnings = _isolation_lines(files, width, mode)
    if warnings:
        lines.append("")
        lines.extend(warnings)
    lines += ["", "Next: orchestra-tx egm brief --write"]
    _emit_lines(lines)
    return stream.ExitCode.OK


def egm_status(args, bare: bool = False) -> int:
    project = _project(args)
    width = _width(args)
    mode = _mode(args)
    state, corrupt = state_mod.load_state(project)
    ready = state_mod.initialized(project)
    findings = _decisions(state_mod.load_findings(project), state_mod.load_triage(project))
    stats = report.summarize(findings)
    designs = scaffold.list_designs(scaffold.designs_dir(project))
    design = state.get("design") or ""
    if not design and len(designs) == 1:
        # read-only fallback: one design on disk and none recorded yet
        design = _rel(designs[0], project)
    files = _isolation_files(project)
    next_action = _next_action(ready, design, findings, designs)
    status_word = _status_word(project, state, design)

    payload = {
        "initialized": ready,
        "design": design,
        "status": status_word,
        "round": int(state.get("round") or 0),
        "stage": state.get("stage") or "none",
        "findings": [
            {key: row.get(key, "") for key in ("id", "severity", "persona", "location", "claim", "decision", "state")}
            for row in findings
        ],
        "counts": stats,
        "isolation": {"files": files, "message": _isolation_message(files)},
        "next": next_action,
    }
    warnings = [corrupt, _isolation_message(files)]
    if _json(args):
        for message in warnings:
            if message:
                stream.diagnostic(message)
        _dump(payload)
        return stream.ExitCode.OK

    if not ready:
        lines = ["EGM status", "", "No EGM state in this project yet.", "Run: orchestra-tx egm init"]
        for message in warnings:
            lines += _warning_lines(message, width, mode) if message else []
        _emit_lines(lines)
        return stream.ExitCode.OK

    rows = [
        ("design", design or "(none selected)"),
        ("status", status_word),
        ("round", str(payload["round"])),
        ("stage", payload["stage"]),
        ("findings", _finding_line(stats)),
    ]
    if stats["total"]:
        rows.append(("severity", _severity_line(stats)))
    lines = ["EGM status", ""] + layout.key_value(rows, width, mode)
    lines += [""] + layout.key_value([("next", next_action)], width, mode)
    _add_warnings(lines, warnings, width, mode)
    if bare:
        lines += [""] + layout.key_value([("loop", LOOP)], width, mode)
    _emit_lines(lines)
    return stream.ExitCode.OK


def egm_brief(args) -> int:
    project = _project(args)
    width = _width(args)
    mode = _mode(args)
    written = bool(getattr(args, "write", False))
    if written and not state_mod.initialized(project):
        _error("no EGM state yet; run 'orchestra-tx egm init' first (--write would create an unindexed designs directory)")
        return stream.ExitCode.MISSING

    plan = plan_mod.load(project)
    pinned = memory.pinned(project)
    recent = [entry for entry in memory.recent(10, project=project) if not entry.get("pinned")][:5]
    session = session_mod.current(project) or (session_mod.recent(1, project=project) or [None])[0]
    body = artifacts.render_brief(plan, pinned, recent, session)
    text, families = artifacts.redact(body)
    files = _isolation_files(project)
    note = artifacts.redaction_note(families)
    target = scaffold.designs_dir(project) / BRIEF_NAME

    if written:
        store.write_text(target, artifacts.merge_brief(store.read_text(target), text))

    payload = {
        "written": written,
        "path": str(target),
        "brief": text,
        "redacted": [{"family": name, "count": count} for name, count in families],
        "redaction_note": note,
        "isolation": {"files": files, "message": _isolation_message(files)},
    }
    if _json(args):
        for message in (note, _isolation_message(files)):
            if message:
                stream.diagnostic(message)
        _dump(payload)
        return stream.ExitCode.OK

    if written:
        rows = [("wrote", str(target))]
        if note:
            rows.append(("redacted", note))
        lines = layout.key_value(rows, width, mode)
        warnings = _isolation_lines(files, width, mode)
        if warnings:
            lines += [""] + warnings
        lines += ["", "Next: orchestra-tx egm review REPORT.md"]
        _emit_lines(lines)
        return stream.ExitCode.OK

    _emit_lines(_wrap_document(artifacts.merge_brief("", text), width))
    for message in (note, _isolation_message(files)):
        if message:
            stream.diagnostic(message)
    stream.diagnostic("tip: orchestra-tx egm brief --write saves this to {}".format(target))
    return stream.ExitCode.OK


def _pick_design(args, project: Optional[str], state: dict, designs: Sequence[Path]) -> Tuple[str, str, int]:
    explicit = getattr(args, "design", None)
    if explicit:
        path = _resolve(project, explicit)
        if not path.is_file():
            return "", "no such design: {} (run 'orchestra-tx egm init' to scaffold the designs directory)".format(path), stream.ExitCode.MISSING
        return _rel(path, project), "", stream.ExitCode.OK
    if state.get("design"):
        return state["design"], "", stream.ExitCode.OK
    if len(designs) == 1:
        return _rel(designs[0], project), "", stream.ExitCode.OK
    if not designs:
        return "", "", stream.ExitCode.OK
    listing = "\n".join("  " + _rel(path, project) for path in designs)
    return "", "several designs found; choose one with --design PATH:\n" + listing, stream.ExitCode.STATE


def egm_review(args) -> int:
    project = _project(args)
    width = _width(args)
    mode = _mode(args)
    quiet = bool(getattr(args, "quiet", False))
    state, corrupt = state_mod.load_state(project)
    source = _resolve(project, getattr(args, "report", ""))
    if not source.is_file():
        _error("no such report: {}".format(source))
        stream.diagnostic("  cause: the review must be written to a file first")
        stream.diagnostic("  next : orchestra-tx egm review REPORT.md")
        return stream.ExitCode.MISSING
    try:
        text = source.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        _error("cannot read {}: {}".format(source, exc))
        return stream.ExitCode.MISSING

    parsed, meta = report.parse_report(text)
    if not parsed:
        _error("no findings in {}: add '## Blockers' / '## Major' / '## Minor' sections or bullet findings".format(_rel(source, project)))
        return stream.ExitCode.STATE

    designs = scaffold.list_designs(scaffold.designs_dir(project))
    design, problem, code = _pick_design(args, project, state, designs)
    if problem:
        _error(problem)
        return code

    triage = state_mod.load_triage(project)
    merged, counts = report.merge(state_mod.load_findings(project), parsed, triage)
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()
    previous = state.get("last_review") or {}
    same_report = bool(previous.get("digest")) and previous.get("digest") == digest
    round_no = int(state.get("round") or 0) + (0 if same_report else 1)
    status_word = scaffold.design_status(_resolve(project, design)) if design else (state.get("status") or "none")
    state.update({
        "design": design,
        "status": status_word or "none",
        "round": round_no,
        "stage": "review imported",
        "updated": state_mod.now(),
        "last_review": {
            "report": _rel(source, project),
            "design": design,
            "imported": state_mod.now(),
            "round": round_no,
            "findings": len(merged),
            "host": meta.get("host", ""),
            "digest": digest,
        },
    })
    state_mod.save_findings(merged, project)
    state_mod.save_state(state, project)

    rows = _decisions(merged, triage)
    stats = report.summarize(rows)
    files = _isolation_files(project)
    warnings: List[str] = []
    if corrupt:
        warnings.append(corrupt)
    if same_report:
        warnings.append("this exact report was already imported; round not incremented")
    if (status_word or "").strip().lower() == "approved":
        warnings.append("design is Approved; importing a review does not change its status (edit **Status:** by hand)")
    isolation = _isolation_message(files)
    if isolation:
        warnings.append(isolation)

    payload = {
        "report": _rel(source, project),
        "design": design,
        "round": round_no,
        "imported": state["last_review"]["imported"],
        "host": meta.get("host", ""),
        "new": counts["new"],
        "changed": counts["changed"],
        "unchanged": counts["unchanged"],
        "findings": rows,
        "counts": stats,
        "isolation": {"files": files, "message": _isolation_message(files)},
    }
    if _json(args):
        for message in warnings:
            if message:
                stream.diagnostic(message)
        _dump(payload)
        return stream.ExitCode.OK

    if not quiet:
        stream.stage(1, 1, "import report", "{} finding{} ({} blocker)".format(
            len(merged), "" if len(merged) == 1 else "s",
            stats["by_severity"].get("blocker", 0)), width=width)
    rows_kv = [
        ("report", _rel(source, project)),
        ("design", design or "(none selected)"),
        ("round", str(round_no)),
        ("new", str(counts["new"])),
        ("changed", str(counts["changed"])),
        ("unchanged", str(counts["unchanged"])),
    ]
    lines = [""] + layout.key_value(rows_kv, width, mode)
    if stats["total"]:
        lines.append("")
        lines += layout.key_value([("severity", _severity_line(stats))], width, mode)
    lines.append("")
    lines += report.render_findings(rows, width, mode)
    _add_warnings(lines, warnings, width, mode)
    lines += [""] + layout.key_value([("next", "orchestra-tx egm report")], width, mode)
    _emit_lines(lines)
    return stream.ExitCode.OK


def _filter_text(severities: Sequence[str], personas: Sequence[str]) -> str:
    parts = []
    if severities:
        parts.append("--severity " + ", ".join(severities))
    if personas:
        parts.append("--persona " + ", ".join(personas))
    return " and ".join(parts) or "the filter"


def egm_report(args) -> int:
    project = _project(args)
    width = _width(args)
    mode = _mode(args)
    state, corrupt = state_mod.load_state(project)
    findings = _decisions(state_mod.load_findings(project), state_mod.load_triage(project))
    if not findings:
        _error("no findings imported yet")
        stream.diagnostic("  cause: egm report reads what 'egm review' imported")
        stream.diagnostic("  next : orchestra-tx egm review REPORT.md")
        return stream.ExitCode.MISSING

    severities = [str(name) for name in getattr(args, "severity", None) or []]
    personas = [str(name) for name in getattr(args, "persona", None) or []]
    unknown = [name for name in severities if name not in report.SEVERITIES]
    if unknown:
        _error("unknown severity: {} (choose {})".format(", ".join(unknown), ", ".join(report.SEVERITIES)))
        return stream.ExitCode.ARGS

    raw = bool(getattr(args, "raw", False))
    rows = report.ordered(report.filtered(findings, severities, personas))
    totals = report.summarize(findings)
    stats = report.summarize(rows)
    design = state.get("design") or ""
    payload = {
        "status": _status_word(project, state, design),
        "design": design,
        "round": int(state.get("round") or 0),
        "stage": state.get("stage") or "none",
        "filters": {"severity": severities, "persona": personas, "raw": raw},
        "imported": totals["total"],
        "findings": rows,
        "counts": stats,
        "next": _triage_next(findings),
        "note": TRUST_LINE,
    }
    files = _isolation_files(project)
    if _json(args):
        for message in (corrupt, _isolation_message(files)):
            if message:
                stream.diagnostic(message)
        _dump(payload)
        return stream.ExitCode.OK

    try:
        ranges = display.parse_ranges(getattr(args, "ranges", None))
    except ValueError as exc:
        _error(str(exc))
        return stream.ExitCode.STATE

    lines = ["EGM report", ""] + layout.key_value([
        ("design", design or "(none selected)"),
        ("round", str(payload["round"])),
        ("findings", _finding_line(totals)),
        ("severity", _severity_line(totals)),
    ], width, mode)

    if not rows:
        lines += [""] + theme.wrap("no findings match " + _filter_text(severities, personas), width, indent=0, hang=2)

    groups: Dict[str, List[dict]] = {}
    for row in rows:  # already ordered, so group order is severity order
        groups.setdefault(str(row.get("severity") or "unknown").lower(), []).append(row)
    for name, group in groups.items():
        if lines[-1].strip():
            lines.append("")
        heading = "{} ({})".format(layout.severity_label(name), len(group))
        for piece in theme.wrap(heading, width, indent=0, hang=2):
            lines.append(theme.paint(piece, name, mode))
        for row in group:
            block = report.render_findings([row], width, mode, raw=raw, head="persona")
            while block and not block[-1].strip():
                block.pop()
            lines.extend(block)
            lines.append("")

    while lines and not lines[-1].strip():
        lines.pop()
    lines += [""] + theme.wrap(TRUST_LINE, width, indent=0, hang=0)
    _add_warnings(lines, [corrupt, _isolation_message(files)], width, mode)

    if ranges:
        lines = display.render(lines, numbers=False, wrap=False, ranges=ranges).split("\n")
    if getattr(args, "pager", False):
        display.page("\n".join(lines))
    else:
        _emit_lines(lines)
    return stream.ExitCode.OK


def _ask_key() -> str:
    """Read one triage answer; ``""`` means end of input."""
    while True:
        sys.stdout.write("choice [p/c/e/d/s/q]: ")
        sys.stdout.flush()
        line = sys.stdin.readline()
        if line == "":
            return ""
        letter = line.strip()[:1].lower()
        if letter == "q" or letter in report.DECISION_LETTERS:
            return letter
        sys.stdout.write("unknown choice; " + DECISION_HINT + "\n")


def _record_decision(project: Optional[str], row: dict, decision: str) -> dict:
    """Persist one decision and the memory entry that explains it."""
    state_mod.decide(str(row.get("id") or ""), decision, project=project)
    where = " at " + str(row["location"]) if row.get("location") else ""
    memory.add(
        "egm {} ({}): {}{}".format(row.get("id"), row.get("severity") or "finding", decision, where),
        tags=["egm", "decision"],
        project=project,
    )
    return {
        "id": row.get("id"),
        "decision": decision,
        "severity": row.get("severity") or "",
        "persona": row.get("persona") or "",
    }


def egm_resolve(args) -> int:
    project = _project(args)
    width = _width(args)
    mode = _mode(args)
    every = bool(getattr(args, "all", False))
    requested = getattr(args, "decide", None)
    decision = report.decision_of(requested) if requested is not None else ""
    interactive = (not _json(args)) and sys.stdin.isatty() and sys.stdout.isatty()

    if requested is not None and not decision:
        _error("unknown decision: {} (choose {})".format(requested, ", ".join(report.DECISIONS)))
        return stream.ExitCode.ARGS
    if every and not decision:
        _error("--all needs --decide D (choose {})".format(", ".join(report.DECISIONS)))
        return stream.ExitCode.ARGS
    if not decision and not interactive:
        _error("egm resolve needs an interactive terminal")
        stream.diagnostic("  cause: stdin or stdout is redirected, and no prompt is ever written to a pipe")
        stream.diagnostic("  instead: orchestra-tx egm resolve --decide propose [--all]")
        stream.diagnostic("  choices: " + ", ".join(report.DECISIONS))
        return stream.ExitCode.STATE

    wait = getattr(args, "lock_timeout", None)
    stopped = ""
    decided: List[dict] = []
    try:
        with store.locked(state_mod.egm_dir(project), timeout=LOCK_WAIT if wait is None else float(wait)):
            state, corrupt = state_mod.load_state(project)
            findings = _decisions(state_mod.load_findings(project), state_mod.load_triage(project))
            if not findings:
                _error("no findings imported yet")
                stream.diagnostic("  next : orchestra-tx egm review REPORT.md")
                return stream.ExitCode.MISSING
            open_rows = [row for row in report.ordered(findings) if not report.is_settled(row)]
            if not decision and open_rows:
                lines = theme.wrap("Triage: " + DECISION_HINT, width, indent=0, hang=8) + [""]
                _emit_lines(lines)
            targets = open_rows if (every or not decision) else open_rows[:1]
            for row in targets:
                if decision:
                    choice = decision
                else:
                    _emit_lines(report.render_findings([row], width, mode, head="id"))
                    answer = _ask_key()
                    if answer in ("", "q"):
                        stopped = "quit" if answer == "q" else "end of input"
                        break
                    if answer == "s":
                        continue
                    choice = report.DECISION_LETTERS[answer]
                decided.append(_record_decision(project, row, choice))
            if decided:
                state["stage"] = "triaged"
                state["updated"] = state_mod.now()
                state_mod.save_state(state, project)
    except store.LockTimeout as exc:
        _error(str(exc))
        stream.diagnostic("  next : retry when the other orchestra-tx session finishes")
        return stream.ExitCode.LOCKED

    current = _decisions(state_mod.load_findings(project), state_mod.load_triage(project))
    stats = report.summarize(current)
    blocking = report.unsettled(current)
    remaining = [row for row in report.ordered(current) if not report.is_settled(row)]
    design = state.get("design") or ""
    next_action = _triage_next(current)
    files = _isolation_files(project)
    payload = {
        "status": _status_word(project, state, design),
        "design": design,
        "round": int(state.get("round") or 0),
        "stage": state.get("stage") or "none",
        "decided": decided,
        "remaining": [row.get("id") for row in remaining],
        "findings": current,
        "counts": stats,
        "triage": str(state_mod.triage_path(project)),
        "stopped": stopped,
        "next": next_action,
    }
    if _json(args):
        for message in (corrupt, _isolation_message(files)):
            if message:
                stream.diagnostic(message)
        _dump(payload)
        return stream.ExitCode.OK

    rows = [
        ("decided", "{} finding{}".format(len(decided), "" if len(decided) == 1 else "s")),
        ("open", "{} ({} blocker/major)".format(stats["open"], len(blocking))),
        ("triage", _rel(state_mod.triage_path(project), project)),
    ]
    lines = [""] + layout.key_value(rows, width, mode)
    if stopped:
        lines += [""] + theme.wrap("stopped ({}); progress is saved, re-run to resume".format(stopped), width, indent=0, hang=2)
    if not remaining:
        lines += [""] + theme.wrap("every finding is settled", width, indent=0, hang=2)
    lines += [""] + layout.key_value([("next", next_action)], width, mode)
    _add_warnings(lines, [corrupt, _isolation_message(files)], width, mode)
    _emit_lines(lines)
    return stream.ExitCode.OK


def egm_check(args) -> int:
    project = _project(args)
    width = _width(args)
    mode = _mode(args)
    state, corrupt = state_mod.load_state(project)
    findings = _decisions(state_mod.load_findings(project), state_mod.load_triage(project))
    requested = getattr(args, "design", None)
    design = _rel(_resolve(project, requested), project) if requested else (state.get("design") or "")
    last = state.get("last_review") or {}
    files = _isolation_files(project)

    problem = ""
    code = stream.ExitCode.OK
    if not findings or not last:
        problem = "no review report imported for {}".format(design or "this project")
        code = stream.ExitCode.MISSING
    elif requested and design and state.get("design") and _norm(design) != _norm(state["design"]):
        problem = "no review report imported for {} (last import was for {})".format(design, state["design"])
        code = stream.ExitCode.MISSING

    open_rows = report.unsettled(findings) if not problem else []
    if not problem and open_rows:
        code = stream.ExitCode.UNSETTLED
    stats = report.summarize(findings)

    payload = {
        "design": design,
        "status": "missing" if problem else ("blocked" if open_rows else "ok"),
        "counts": stats,
        "unsettled": [row.get("id") for row in open_rows],
        "findings": open_rows,
        "isolation": {"files": files, "message": _isolation_message(files)},
        "problem": problem,
        "code": code,
    }
    if _json(args):
        for message in (corrupt, _isolation_message(files)):
            if message:
                stream.diagnostic(message)
        _dump(payload)
        return code

    if problem:
        _error(problem)
        stream.diagnostic("  next : orchestra-tx egm review REPORT.md")
        for line in _isolation_lines(files, width, mode):
            stream.diagnostic(line)
        return code

    rows = [
        ("check", "blocked" if open_rows else "ok"),
        ("design", design or "(none selected)"),
        ("findings", _finding_line(stats)),
        ("unsettled", "{} blocker/major".format(len(open_rows)) if open_rows else "none"),
    ]
    lines = layout.key_value(rows, width, mode)
    if open_rows:
        lines.append("")
        lines += report.render_findings(open_rows, width, mode)
        lines += _warning_lines("settle these findings before treating the design as reviewed", width, mode)
    _add_warnings(lines, [corrupt, _isolation_message(files)], width, mode)
    _emit_lines(lines)
    return code


VERBS.update({
    "init": egm_init,
    "status": egm_status,
    "brief": egm_brief,
    "review": egm_review,
    "report": egm_report,
    "resolve": egm_resolve,
    "check": egm_check,
})


def run(args) -> int:
    verb = getattr(args, "egm_command", "") or ""
    if not verb:
        return egm_status(args, bare=True)
    handler = VERBS.get(verb)
    if handler is None:
        _error("unknown egm verb: {}".format(verb))
        return stream.ExitCode.ARGS
    return handler(args)
