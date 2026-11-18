"""Command line interface for orchestra-tx."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

from . import __version__, context as context_mod, display, memory, plan as plan_mod, session as session_mod, store, termux

DATA_DIR = Path(__file__).resolve().parent / "data"
USAGE_FILE = DATA_DIR / "USAGE.txt"


# --------------------------------------------------------------------------- #
# output helpers
# --------------------------------------------------------------------------- #

def _flag(args: argparse.Namespace, name: str, default=None):
    return getattr(args, name, default)


def _supports_color() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    stream = sys.stdout
    return bool(getattr(stream, "isatty", lambda: False)()) and os.environ.get("TERM", "") not in ("", "dumb")


def _color(args: argparse.Namespace) -> bool:
    choice = _flag(args, "color", None)
    if choice is False:
        return False
    return _supports_color()


def _emit(text: str = "") -> None:
    sys.stdout.write(text + "\n")


def _error(message: str) -> int:
    sys.stderr.write("orchestra-tx: " + message + "\n")
    return 1


def _dump(payload) -> None:
    sys.stdout.write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


# --------------------------------------------------------------------------- #
# init / doctor / usage / display
# --------------------------------------------------------------------------- #

def cmd_init(args: argparse.Namespace) -> int:
    project = _flag(args, "project")
    store.ensure_dir(store.project_store(project))
    store.ensure_dir(store.state_dir(project))
    plan = plan_mod.load(project)
    goal = _flag(args, "goal")
    if goal:
        plan["goal"] = goal
        plan_mod.save(plan, project)
    if _flag(args, "json"):
        _dump({
            "project": str(store.project_root(project)),
            "store": str(store.project_store(project)),
            "plan": str(plan_mod.path_for(project)),
            "memory": str(memory.path_for("project", project)),
            "context": str(context_mod.context_path(project)),
        })
        return 0
    _emit("orchestra-tx {} initialized".format(__version__))
    _emit("  project : {}".format(store.project_root(project)))
    _emit("  store   : {}".format(store.project_store(project)))
    _emit("  plan    : {}".format(plan_mod.path_for(project)))
    _emit("  memory  : {}".format(memory.path_for("project", project)))
    _emit("  context : {}".format(context_mod.context_path(project)))
    _emit("")
    _emit("Next: orchestra-tx plan new \"<goal>\" --step \"<first step>\"")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    project = _flag(args, "project")
    core = termux.report(store.project_store(project))
    from . import a11y
    rows = list(core) + a11y.report_rows()
    if _flag(args, "json"):
        _dump([{"check": label, "value": value, "ok": ok} for label, value, ok in rows])
        return 0
    _emit("orchestra-tx doctor")
    _emit("")
    width = max(len(label) for label, _, _ in rows)
    for label, value, ok in rows:
        mark = "ok  " if ok else "warn"
        _emit("  [{}] {:<{w}}  {}".format(mark, label, value, w=width))
    if not rows[2][2]:
        _emit("")
        _emit("Install orchestraCLI with: " + termux.install_hint())
    return 0 if all(ok for _, _, ok in core) else 1


def cmd_usage(args: argparse.Namespace) -> int:
    target = Path(_flag(args, "file") or USAGE_FILE)
    if not target.exists():
        return _error("usage file not found: {}".format(target))
    lines, label = display.read_lines(str(target))
    text = display.render(lines, numbers=False, wrap=_flag(args, "wrap", True), color=False)
    if _flag(args, "pager"):
        display.page(text)
    else:
        _emit(text)
    return 0


def cmd_display(args: argparse.Namespace) -> int:
    project = store.project_root(_flag(args, "project"))
    source = _flag(args, "file")

    if _flag(args, "list") or not source:
        base = Path(_flag(args, "list")) if isinstance(_flag(args, "list"), str) else project
        if not base.is_absolute():
            base = project / base
        files = display.find_text_files(base, any_extension=bool(_flag(args, "any_files")))
        if _flag(args, "json"):
            _dump([{"path": str(path), "bytes": path.stat().st_size} for path in files])
            return 0
        if not files:
            _emit("no text files in {}".format(base))
            _emit("tip: use --list DIR or --any-files, or pass a path directly")
            return 0
        _emit("Text files in {}:".format(base))
        for path in files:
            _emit("  " + display.describe(path))
        return 0

    try:
        ranges = display.parse_ranges(_flag(args, "ranges"))
        lines, label = display.read_lines(source, base=project, encoding=_flag(args, "encoding") or "utf-8")
    except (FileNotFoundError, IsADirectoryError, ValueError) as exc:
        return _error(str(exc))

    width = _flag(args, "width")
    text = display.render(
        lines,
        numbers=not _flag(args, "no_numbers"),
        width=width,
        wrap=not _flag(args, "no_wrap"),
        color=_color(args),
        ranges=ranges,
        max_lines=_flag(args, "max_lines"),
    )
    if _flag(args, "stats"):
        shown = len(text.split("\n")) if text else 0
        sys.stderr.write("{}: {} ({} line(s) total)\n".format(label, display.byte_cap_note(lines, shown), len(lines)))
    if _flag(args, "pager"):
        display.page(text)
    else:
        sys.stdout.write(text + "\n")
    return 0


# --------------------------------------------------------------------------- #
# plan
# --------------------------------------------------------------------------- #

def cmd_plan_new(args: argparse.Namespace) -> int:
    project = _flag(args, "project")
    steps = list(_flag(args, "step") or [])
    goal = " ".join(_flag(args, "goal") or []).strip()
    plan = plan_mod.create(goal, steps, project)
    if _flag(args, "json"):
        _dump(plan)
        return 0
    _emit(plan_mod.render(plan, ascii_only=_flag(args, "ascii"), color=_color(args)))
    return 0


def cmd_plan_add(args: argparse.Namespace) -> int:
    project = _flag(args, "project")
    step = plan_mod.add(" ".join(args.text).strip(), note=_flag(args, "note") or "", project=project)
    if _flag(args, "json"):
        _dump(step)
        return 0
    _emit("added step {id}: {text}".format(**step))
    return 0


def cmd_plan_use(args: argparse.Namespace) -> int:
    project = _flag(args, "project")
    try:
        step = plan_mod.set_status(args.id, "active", _flag(args, "note"), project)
    except KeyError as exc:
        return _error(str(exc))
    if _flag(args, "json"):
        _dump(step)
        return 0
    _emit("working on step {id}: {text}".format(**step))
    return 0


def cmd_plan_done(args: argparse.Namespace) -> int:
    project = _flag(args, "project")
    try:
        step = plan_mod.set_status(args.id, "done", _flag(args, "note"), project)
    except KeyError as exc:
        return _error(str(exc))
    plan = plan_mod.load(project)
    nxt = plan_mod.active_step(plan)
    if _flag(args, "json"):
        _dump(step)
        return 0
    _emit("done: {text}".format(**step))
    if nxt:
        _emit("next: [{id}] {text}".format(**nxt))
    else:
        _emit("next: nothing active (use 'orchestra-tx plan use <id>')")
    return 0


def cmd_plan_block(args: argparse.Namespace) -> int:
    project = _flag(args, "project")
    try:
        step = plan_mod.set_status(args.id, "blocked", _flag(args, "note"), project)
    except KeyError as exc:
        return _error(str(exc))
    _emit("blocked: {text}".format(**step) + (" ({})".format(step["note"]) if step.get("note") else ""))
    return 0


def cmd_plan_note(args: argparse.Namespace) -> int:
    project = _flag(args, "project")
    try:
        step = plan_mod.set_note(args.id, " ".join(args.text).strip(), project)
    except KeyError as exc:
        return _error(str(exc))
    _emit("note saved on step {id}".format(**step))
    return 0


def cmd_plan_show(args: argparse.Namespace) -> int:
    project = _flag(args, "project")
    plan = plan_mod.load(project)
    if _flag(args, "json"):
        _dump(plan)
        return 0
    _emit(plan_mod.render(plan, ascii_only=_flag(args, "ascii"), color=_color(args)))
    return 0


def cmd_plan_reset(args: argparse.Namespace) -> int:
    project = _flag(args, "project")
    if not _flag(args, "yes"):
        return _error("refusing to reset the plan without --yes")
    plan = plan_mod.create("", [], project)
    if _flag(args, "json"):
        _dump(plan)
        return 0
    _emit("plan reset")
    return 0


# --------------------------------------------------------------------------- #
# memory
# --------------------------------------------------------------------------- #

def _scope_from_args(args: argparse.Namespace) -> str:
    if _flag(args, "global_scope"):
        return "global"
    return "all"


def cmd_memory_add(args: argparse.Namespace) -> int:
    project = _flag(args, "project")
    text = " ".join(args.text).strip()
    session = session_mod.current(project) or {}
    try:
        entry = memory.add(
            text,
            tags=_flag(args, "tag") or [],
            scope="global" if _flag(args, "global_scope") else "project",
            project=project,
            session=session.get("id", ""),
            pinned=bool(_flag(args, "pin")),
        )
    except ValueError as exc:
        return _error(str(exc))
    if _flag(args, "json"):
        _dump(entry)
        return 0
    _emit("remembered [{id}] {text}".format(**entry))
    return 0


def cmd_memory_list(args: argparse.Namespace) -> int:
    project = _flag(args, "project")
    scope = _scope_from_args(args)
    rows = memory.recent(_flag(args, "limit") or 20, scope=scope, project=project)
    if _flag(args, "json"):
        _dump(rows)
        return 0
    _emit(memory.render(rows, color=_color(args)))
    return 0


def cmd_memory_search(args: argparse.Namespace) -> int:
    project = _flag(args, "project")
    scope = _scope_from_args(args)
    rows = memory.search(" ".join(args.query), _flag(args, "limit") or 10, scope=scope, project=project)
    if _flag(args, "json"):
        _dump(rows)
        return 0
    if not rows:
        _emit("nothing remembered matches '{}'".format(" ".join(args.query)))
        return 0
    _emit(memory.render(rows, color=_color(args)))
    return 0


def cmd_memory_forget(args: argparse.Namespace) -> int:
    project = _flag(args, "project")
    scope = "global" if _flag(args, "global_scope") else "project"
    if memory.remove(args.id, scope=scope, project=project):
        _emit("forgot {}".format(args.id))
        return 0
    return _error("no memory entry {} in {} scope".format(args.id, scope))


def cmd_memory_export(args: argparse.Namespace) -> int:
    project = _flag(args, "project")
    scope = _scope_from_args(args)
    sys.stdout.write(memory.export(scope=scope, fmt=_flag(args, "format") or "jsonl", project=project))
    return 0


# --------------------------------------------------------------------------- #
# session
# --------------------------------------------------------------------------- #

def _write_context(project: Optional[str], session: Optional[dict]) -> Path:
    plan = plan_mod.load(project)
    rows = memory.recent(20, scope="all", project=project)
    text = context_mod.build(session, plan, rows, project)
    return context_mod.write(project, text)


def cmd_session_start(args: argparse.Namespace) -> int:
    project = _flag(args, "project")
    previous = session_mod.current(project)
    goal = " ".join(_flag(args, "goal") or []).strip()
    if not goal:
        goal = plan_mod.load(project).get("goal", "")
    session = session_mod.start(goal, project)
    path = _write_context(project, session)
    if _flag(args, "json"):
        _dump({"session": session, "context": str(path)})
        return 0
    if previous:
        _emit("previous session {} closed out (run 'orchestra-tx session end' next time)".format(previous.get("id")))
    _emit("session {} started".format(session["id"]))
    _emit("  goal    : {}".format(session.get("goal") or "(none)"))
    _emit("  context : {}".format(path))
    return 0


def cmd_session_status(args: argparse.Namespace) -> int:
    project = _flag(args, "project")
    session = session_mod.current(project)
    plan = plan_mod.load(project)
    stats = plan_mod.progress(plan)
    if _flag(args, "json"):
        _dump({"session": session, "progress": stats, "memory": len(memory.load_all(project))})
        return 0
    if session:
        _emit("session : {} (started {})".format(session["id"], session.get("started", "")))
        _emit("goal    : {}".format(session.get("goal") or "(none)"))
        if session.get("notes"):
            _emit("notes   : {} recorded".format(len(session["notes"])))
    else:
        _emit("session : none (start one with 'orchestra-tx session start')")
    _emit("plan    : {done}/{total} done ({percent}%)".format(**stats))
    active = plan_mod.active_step(plan)
    if active:
        _emit("next    : [{id}] {text}".format(**active))
    _emit("memory  : {} entries".format(len(memory.load_all(project))))
    return 0


def cmd_session_end(args: argparse.Namespace) -> int:
    project = _flag(args, "project")
    summary = " ".join(_flag(args, "summary") or []).strip()
    session = session_mod.end(summary, remember=not _flag(args, "no_remember"), project=project)
    if session is None:
        return _error("no active session")
    if _flag(args, "json"):
        _dump(session)
        return 0
    _emit("session {} ended".format(session["id"]))
    if summary and not _flag(args, "no_remember"):
        _emit("summary stored in project memory")
    return 0


def cmd_session_context(args: argparse.Namespace) -> int:
    project = _flag(args, "project")
    session = session_mod.current(project)
    path = _write_context(project, session)
    if _flag(args, "json"):
        _dump({"context": str(path)})
        return 0
    if _flag(args, "quiet"):
        _emit(str(path))
        return 0
    _emit("# wrote " + str(path))
    _emit(store.read_text(path).rstrip())
    return 0


def cmd_session_list(args: argparse.Namespace) -> int:
    project = _flag(args, "project")
    rows = session_mod.recent(_flag(args, "limit") or 10, project)
    if _flag(args, "json"):
        _dump(rows)
        return 0
    if not rows:
        _emit("no sessions recorded for this project")
        return 0
    current = session_mod.current_id(project)
    for row in rows:
        mark = "*" if row.get("id") == current else " "
        _emit("{} {}  {}  {}".format(mark, row.get("id"), row.get("started", "")[:19], row.get("goal", "")[:48]))
    return 0


# --------------------------------------------------------------------------- #
# run
# --------------------------------------------------------------------------- #
# eyes: desktop accessibility trees
# --------------------------------------------------------------------------- #

def cmd_see(args: argparse.Namespace) -> int:
    from . import a11y

    if _flag(args, "backends"):
        rows = a11y.available()
        if _flag(args, "json"):
            _dump([{"backend": name, "usable": usable, "detail": detail} for name, usable, detail in rows])
            return 0
        _emit("accessibility backends")
        _emit("")
        for name, usable, detail in rows:
            _emit("  [{}] {:<8} {}".format("ok  " if usable else "--  ", name, detail))
        _emit("")
        _emit("They read the same tree a screen reader walks: no screenshots, no OCR.")
        return 0 if any(usable for _, usable, _ in rows) else 3

    dump = _flag(args, "dump")
    if _flag(args, "apps") and not dump:
        names, problem = a11y.list_apps(_flag(args, "backend"))
        if not names:
            _error(problem or "no applications reported")
            _emit_detail("run 'orchestra-tx see --backends' to see what this machine exposes")
            return 3
        if _flag(args, "json"):
            _dump({"apps": names})
            return 0
        for name in names:
            _emit(name)
        return 0

    if dump:
        try:
            text = sys.stdin.read() if dump == "-" else Path(dump).expanduser().read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return _error("cannot read dump: {}".format(exc))
        capture = a11y.Capture(ok=True, backend="dump", text=text)
    else:
        capture = a11y.capture(
            app=_flag(args, "app") or "",
            depth=_flag(args, "depth", a11y.MAX_DEPTH),
            backend=_flag(args, "backend"),
        )
        if not capture.ok:
            _error("{}: {}".format(capture.backend, capture.error))
            if capture.hint:
                _emit_detail(capture.hint)
            _emit_detail("on a phone, 'orchestra-tx see --apps' tells you what is in front")
            return 3

    nodes = capture.nodes()
    if not nodes:
        _error("the accessibility tree is empty")
        _emit_detail("the app may be drawing its own pixels (games, Electron with a11y off)")
        return 3

    limit = max(1, _flag(args, "max_nodes", a11y.MAX_NODES))
    shown = nodes[:limit]
    if _flag(args, "json"):
        _emit(a11y.dump_json(capture, shown))
        return 0

    width = _flag(args, "width") or shutil.get_terminal_size((80, 24)).columns
    width = max(40, min(200, width))
    _emit(a11y.render(shown, width=width, color=_color(args), show_value=_flag(args, "values", True)))
    if len(nodes) > len(shown):
        sys.stderr.write("{} more node(s); raise --max-nodes or lower --depth\n".format(len(nodes) - len(shown)))
    sys.stderr.write("{}\n".format(a11y.describe(nodes, 4)))

    if _flag(args, "remember"):
        label = capture.app or capture.backend
        memory.add("a11y {}: {}".format(label, a11y.describe(nodes, 6)),
                   tags=["a11y"], project=_flag(args, "project"))
    return 0


def _emit_detail(message: str) -> None:
    sys.stderr.write("  {}\n".format(message))


# --------------------------------------------------------------------------- #
# egm (Elephant-Goldfish Model artifacts and review import)
# --------------------------------------------------------------------------- #

def cmd_egm(args: argparse.Namespace) -> int:
    from .egm import commands as egm_commands

    return egm_commands.run(args)


# --------------------------------------------------------------------------- #

def cmd_run(args: argparse.Namespace) -> int:
    project = _flag(args, "project")
    binary = termux.orchestra_binary()
    argv = list(_flag(args, "argv") or [])
    if argv and argv[0] == "--":
        argv = argv[1:]

    session = session_mod.current(project) or session_mod.start(project=project)
    path = _write_context(project, session)
    env = os.environ.copy()
    env.update({
        "ORCHESTRA_TX_PROJECT": str(store.project_root(project)),
        "ORCHESTRA_TX_STORE": str(store.project_store(project)),
        "ORCHESTRA_TX_PLAN": str(plan_mod.path_for(project)),
        "ORCHESTRA_TX_MEMORY": str(memory.path_for("project", project)),
        "ORCHESTRA_TX_SESSION": session.get("id", ""),
        "ORCHESTRA_TX_CONTEXT": str(path),
    })
    if not argv:
        argv = ["--help"]
    if _flag(args, "print_env"):
        for key in sorted(env):
            if key.startswith("ORCHESTRA_TX_"):
                _emit("export {}={}".format(key, env[key]))
        return 0
    if not binary:
        _error("orchestraCLI not found. Install it with: " + termux.install_hint())
        return 127
    try:
        return subprocess.call([binary] + argv, cwd=str(store.project_root(project)), env=env)
    except OSError as exc:
        return _error("failed to run {}: {}".format(binary, exc))


# --------------------------------------------------------------------------- #
# parser
# --------------------------------------------------------------------------- #

def _add_common(parser: argparse.ArgumentParser, suppress: bool = False) -> None:
    default = argparse.SUPPRESS if suppress else None
    parser.add_argument("--project", metavar="DIR", default=default, help="project directory (default: current directory)")
    parser.add_argument("--json", action="store_true", default=(argparse.SUPPRESS if suppress else False),
                        help="machine readable output")
    parser.add_argument("--ascii", action="store_true", default=(argparse.SUPPRESS if suppress else False),
                        help="ASCII-only markers")
    parser.add_argument("--color", dest="color", action="store_true",
                        default=(argparse.SUPPRESS if suppress else None), help="force ANSI colour")
    parser.add_argument("--no-color", dest="color", action="store_false",
                        default=(argparse.SUPPRESS if suppress else None), help="disable ANSI colour")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="orchestra-tx",
        description="Termux-friendly plugin for orchestraCLI: session plan, persistent memory and a text-file display.",
        epilog="Run 'orchestra-tx usage' for the full reference.",
    )
    parser.add_argument("--version", action="version", version="orchestra-tx " + __version__)
    _add_common(parser)
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    # init / doctor / usage
    p_init = sub.add_parser("init", help="create the plugin store for this project")
    p_init.add_argument("--goal", metavar="TEXT", help="initial goal for the session plan")
    _add_common(p_init, suppress=True)
    p_init.set_defaults(func=cmd_init)

    p_doctor = sub.add_parser("doctor", help="check Termux, python and orchestraCLI")
    _add_common(p_doctor, suppress=True)
    p_doctor.set_defaults(func=cmd_doctor)

    p_usage = sub.add_parser("usage", help="print the bundled USAGE.txt reference")
    p_usage.add_argument("--file", metavar="PATH", help="print another text file instead")
    p_usage.add_argument("-p", "--pager", action="store_true", help="page the output")
    p_usage.add_argument("--no-wrap", dest="wrap", action="store_false", default=True, help="do not wrap long lines")
    _add_common(p_usage, suppress=True)
    p_usage.set_defaults(func=cmd_usage)

    # display
    p_disp = sub.add_parser("display", help="display a text file in the terminal")
    p_disp.add_argument("file", nargs="?", help="file to display ('-' for stdin); omit to list .txt files")
    p_disp.add_argument("-r", "--range", dest="ranges", action="append", metavar="N[-M]",
                        help="line or range to show (repeatable, comma separated)")
    p_disp.add_argument("-n", "--no-numbers", action="store_true", help="hide line numbers")
    p_disp.add_argument("-w", "--width", type=int, metavar="COLS", help="wrap width (default: terminal width)")
    p_disp.add_argument("--no-wrap", dest="no_wrap", action="store_true", help="never wrap long lines")
    p_disp.add_argument("--max-lines", type=int, metavar="N", help="stop after N displayed lines")
    p_disp.add_argument("--encoding", metavar="NAME", help="file encoding (default: utf-8)")
    p_disp.add_argument("-p", "--pager", action="store_true", help="page the output through less/$PAGER")
    p_disp.add_argument("--stats", action="store_true", help="print a line count summary to stderr")
    p_disp.add_argument("--list", nargs="?", const="", metavar="DIR", help="list .txt files instead of displaying")
    p_disp.add_argument("--any-files", action="store_true", help="with --list: include .md/.log/.json/...")
    _add_common(p_disp, suppress=True)
    p_disp.set_defaults(func=cmd_display)

    # plan
    p_plan = sub.add_parser("plan", help="create and advance the session plan")
    _add_common(p_plan, suppress=True)
    plan_sub = p_plan.add_subparsers(dest="plan_command", metavar="ACTION")

    p_plan_new = plan_sub.add_parser("new", help="start a fresh plan")
    p_plan_new.add_argument("goal", nargs="*", help="goal for this session")
    p_plan_new.add_argument("--step", action="append", metavar="TEXT", help="add a step (repeatable)")
    _add_common(p_plan_new, suppress=True)
    p_plan_new.set_defaults(func=cmd_plan_new)

    p_plan_add = plan_sub.add_parser("add", help="append a step")
    p_plan_add.add_argument("text", nargs="+", help="step description")
    p_plan_add.add_argument("--note", metavar="TEXT", help="note for the step")
    _add_common(p_plan_add, suppress=True)
    p_plan_add.set_defaults(func=cmd_plan_add)

    p_plan_use = plan_sub.add_parser("use", help="mark a step active")
    p_plan_use.add_argument("id", type=int)
    p_plan_use.add_argument("--note", metavar="TEXT")
    _add_common(p_plan_use, suppress=True)
    p_plan_use.set_defaults(func=cmd_plan_use)

    p_plan_done = plan_sub.add_parser("done", help="mark a step done")
    p_plan_done.add_argument("id", type=int)
    p_plan_done.add_argument("--note", metavar="TEXT")
    _add_common(p_plan_done, suppress=True)
    p_plan_done.set_defaults(func=cmd_plan_done)

    p_plan_block = plan_sub.add_parser("block", help="mark a step blocked")
    p_plan_block.add_argument("id", type=int)
    p_plan_block.add_argument("--note", metavar="TEXT")
    _add_common(p_plan_block, suppress=True)
    p_plan_block.set_defaults(func=cmd_plan_block)

    p_plan_note = plan_sub.add_parser("note", help="attach a note to a step")
    p_plan_note.add_argument("id", type=int)
    p_plan_note.add_argument("text", nargs="+")
    _add_common(p_plan_note, suppress=True)
    p_plan_note.set_defaults(func=cmd_plan_note)

    p_plan_show = plan_sub.add_parser("show", aliases=["status"], help="render the plan")
    _add_common(p_plan_show, suppress=True)
    p_plan_show.set_defaults(func=cmd_plan_show)

    p_plan_reset = plan_sub.add_parser("reset", help="wipe the plan steps")
    p_plan_reset.add_argument("--yes", action="store_true")
    _add_common(p_plan_reset, suppress=True)
    p_plan_reset.set_defaults(func=cmd_plan_reset)

    # memory
    p_mem = sub.add_parser("memory", help="persist facts across sessions")
    _add_common(p_mem, suppress=True)
    mem_sub = p_mem.add_subparsers(dest="memory_command", metavar="ACTION")

    p_mem_add = mem_sub.add_parser("add", help="remember something")
    p_mem_add.add_argument("text", nargs="+")
    p_mem_add.add_argument("-t", "--tag", action="append", metavar="TAG", help="tag (repeatable)")
    p_mem_add.add_argument("--pin", action="store_true", help="always surface this entry in context")
    p_mem_add.add_argument("--global", dest="global_scope", action="store_true", help="store for all projects")
    _add_common(p_mem_add, suppress=True)
    p_mem_add.set_defaults(func=cmd_memory_add)

    p_mem_list = mem_sub.add_parser("list", help="show recent entries")
    p_mem_list.add_argument("-n", "--limit", type=int, default=20)
    p_mem_list.add_argument("--global", dest="global_scope", action="store_true")
    p_mem_list.add_argument("--all", action="store_true", default=True, help="project and global (default)")
    _add_common(p_mem_list, suppress=True)
    p_mem_list.set_defaults(func=cmd_memory_list)

    p_mem_search = mem_sub.add_parser("search", help="search memory")
    p_mem_search.add_argument("query", nargs="+")
    p_mem_search.add_argument("-n", "--limit", type=int, default=10)
    p_mem_search.add_argument("--global", dest="global_scope", action="store_true")
    p_mem_search.add_argument("--all", action="store_true", default=True, help="project and global (default)")
    _add_common(p_mem_search, suppress=True)
    p_mem_search.set_defaults(func=cmd_memory_search)

    p_mem_forget = mem_sub.add_parser("forget", help="delete an entry by id")
    p_mem_forget.add_argument("id")
    p_mem_forget.add_argument("--global", dest="global_scope", action="store_true")
    _add_common(p_mem_forget, suppress=True)
    p_mem_forget.set_defaults(func=cmd_memory_forget)

    p_mem_export = mem_sub.add_parser("export", help="export memory")
    p_mem_export.add_argument("--format", choices=["jsonl", "json", "md"], default="jsonl")
    p_mem_export.add_argument("--global", dest="global_scope", action="store_true")
    p_mem_export.add_argument("--all", action="store_true", default=True, help="project and global (default)")
    _add_common(p_mem_export, suppress=True)
    p_mem_export.set_defaults(func=cmd_memory_export)

    # session
    p_sess = sub.add_parser("session", help="start, inspect and end sessions")
    _add_common(p_sess, suppress=True)
    sess_sub = p_sess.add_subparsers(dest="session_command", metavar="ACTION")

    p_sess_start = sess_sub.add_parser("start", help="start a session and write context.md")
    p_sess_start.add_argument("goal", nargs="*")
    _add_common(p_sess_start, suppress=True)
    p_sess_start.set_defaults(func=cmd_session_start)

    p_sess_status = sess_sub.add_parser("status", help="current session, plan and memory")
    _add_common(p_sess_status, suppress=True)
    p_sess_status.set_defaults(func=cmd_session_status)

    p_sess_end = sess_sub.add_parser("end", help="end the session and remember the summary")
    p_sess_end.add_argument("--summary", nargs="*", metavar="TEXT")
    p_sess_end.add_argument("--no-remember", action="store_true", help="do not store the summary in memory")
    _add_common(p_sess_end, suppress=True)
    p_sess_end.set_defaults(func=cmd_session_end)

    p_sess_ctx = sess_sub.add_parser("context", help="rebuild and print session context")
    p_sess_ctx.add_argument("-q", "--quiet", action="store_true", help="only print the context path")
    _add_common(p_sess_ctx, suppress=True)
    p_sess_ctx.set_defaults(func=cmd_session_context)

    p_sess_list = sess_sub.add_parser("list", help="recent sessions for this project")
    p_sess_list.add_argument("-n", "--limit", type=int, default=10)
    _add_common(p_sess_list, suppress=True)
    p_sess_list.set_defaults(func=cmd_session_list)

    # see (accessibility trees)
    p_see = sub.add_parser("see", help="read a desktop app through its accessibility tree")
    p_see.add_argument("--app", metavar="NAME", help="application to inspect (default: the frontmost one)")
    p_see.add_argument("--depth", type=int, default=6, metavar="N", help="maximum tree depth (0 = unlimited)")
    p_see.add_argument("--max-nodes", type=int, default=200, metavar="N", help="stop after N nodes")
    p_see.add_argument("-w", "--width", type=int, metavar="COLS", help="wrap width (default: terminal width)")
    p_see.add_argument("--no-values", dest="values", action="store_false", default=True,
                       help="omit field values")
    p_see.add_argument("--backend", choices=["macos", "windows", "linux", "android"],
                       help="force one accessibility backend")
    p_see.add_argument("--apps", action="store_true", help="list applications instead of a tree")
    p_see.add_argument("--backends", action="store_true", help="list accessibility backends and their status")
    p_see.add_argument("--dump", metavar="FILE", help="re-render a captured dump ('-' for stdin)")
    p_see.add_argument("--remember", action="store_true", help="store a one-line summary in project memory")
    _add_common(p_see, suppress=True)
    p_see.set_defaults(func=cmd_see)

    # egm
    p_egm = sub.add_parser("egm", help="Elephant-Goldfish design loop: artifacts, review import, gate")
    _add_common(p_egm, suppress=True)
    egm_sub = p_egm.add_subparsers(dest="egm_command", metavar="ACTION")

    def _egm_verb(name: str, help_text: str) -> argparse.ArgumentParser:
        child = egm_sub.add_parser(name, help=help_text)
        child.add_argument("-w", "--width", type=int, metavar="COLS", help="wrap width (default: terminal width)")
        child.add_argument("-q", "--quiet", action="store_true", help="suppress the progress line")
        _add_common(child, suppress=True)
        child.set_defaults(func=cmd_egm)
        return child

    p_egm_init = _egm_verb("init", "scaffold the design directory, SITEMAP.md and egm state")
    p_egm_init.add_argument("--dir", metavar="DIR", help="design directory (default: .orchestra/designs)")
    p_egm_init.add_argument("--force", action="store_true", help="skip the prompt and reset state.json")

    _egm_verb("status", "board: design, status, round, findings and the next command")

    p_egm_brief = _egm_verb("brief", "seed concepts_brief.md from the plan and memory")
    p_egm_brief.add_argument("--write", action="store_true", help="write <designs>/concepts_brief.md instead of printing")

    p_egm_review = _egm_verb("review", "import a goldfish review report")
    p_egm_review.add_argument("report", metavar="REPORT.md", help="review report written by the host")
    p_egm_review.add_argument("--design", metavar="PATH", help="design the review applies to")

    p_egm_check = _egm_verb("check", "exit 4 on an unsettled Blocker or Major finding")
    p_egm_check.add_argument("design", nargs="?", help="design to check (default: the last imported one)")

    # run
    p_run = sub.add_parser("run", help="run orchestraCLI with session context exported")
    p_run.add_argument("argv", nargs=argparse.REMAINDER, help="arguments passed to orchestra (use -- first)")
    p_run.add_argument("--print-env", action="store_true", help="print the ORCHESTRA_TX_* exports instead of running")
    _add_common(p_run, suppress=True)
    p_run.set_defaults(func=cmd_run)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = getattr(args, "func", None)
    if handler is None:
        # bare `orchestra-tx` shows a live status board
        command = getattr(args, "command", "") or ""
        if command == "plan":
            return cmd_plan_show(args)
        if command == "memory":
            return cmd_memory_list(args)
        if command == "session":
            return cmd_session_status(args)
        if command == "egm":
            return cmd_egm(args)
        # Bare `orchestra-tx`: show the board you want when opening a shell.
        cmd_session_status(args)
        _emit("")
        cmd_plan_show(args)
        return 0
    try:
        return handler(args)
    except BrokenPipeError:  # e.g. `orchestra-tx display big.txt | head`
        try:
            sys.stdout.close()
        except OSError:
            pass
        return 0
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
