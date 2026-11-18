"""Eyes for orchestraCLI: read desktop apps through their accessibility trees.

Desktop applications already expose their user interface, for free, through the
platform accessibility API -- the very same tree a screen reader walks. This
module uses it instead of pixels: no screenshot, no OCR, no vision model, and
nothing to install that needs a compiler.

    macOS    System Events (JXA) via ``osascript``
    Windows  UI Automation via ``powershell``
    Linux    AT-SPI2 via ``pyatspi`` when the system has it
    Android  ``uiautomator dump`` XML (Termux, rooted or over adb)

Every backend is optional. When none is usable the command reports what is
missing and exits 3, exactly like a missing EGM install.

Wire format (what a backend prints, and what ``--dump`` accepts)::

    window|Inbox - Mail||focused
      toolbar|||
        button|Compose||enabled
        button|Delete||disabled

One node per line, two spaces of indentation per level, and four pipe
separated fields: role, name, value, states. Pipes inside a field are
replaced by ``/`` and newlines by spaces, so the format stays line-greppable
on a phone.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

MAX_NODES = 200
MAX_DEPTH = 6
VALUE_LIMIT = 60

FIELD_COUNT = 4


# --------------------------------------------------------------------------- #
# model
# --------------------------------------------------------------------------- #

@dataclass
class Node:
    role: str
    name: str = ""
    value: str = ""
    states: List[str] = field(default_factory=list)
    depth: int = 0

    def as_dict(self) -> Dict[str, object]:
        return {
            "role": self.role,
            "name": self.name,
            "value": self.value,
            "states": list(self.states),
        }


def _clean(text: object, limit: int = VALUE_LIMIT) -> str:
    """One line, no separators, no runaway length."""
    value = "" if text is None else str(text)
    value = value.replace("\r", " ").replace("\n", " ").replace("\t", " ")
    value = value.replace("|", "/")
    value = " ".join(value.split())
    if limit and len(value) > limit:
        value = value[: limit - 1] + "\u2026"
    return value


def parse_dump(text: str, max_depth: int = 0) -> List[Node]:
    """Parse the wire format into nodes. Unknown lines are kept verbatim."""
    nodes: List[Node] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        stripped = raw.lstrip(" ")
        depth = (len(raw) - len(stripped)) // 2
        if max_depth and depth > max_depth:
            continue
        parts = stripped.split("|", FIELD_COUNT - 1)
        parts += [""] * (FIELD_COUNT - len(parts))
        states = [s.strip() for s in parts[3].split(",")
                  if s.strip() and s.strip().replace("-", "").replace("_", "").isalnum()]
        nodes.append(Node(
            role=_clean(parts[0], 40) or "element",
            name=_clean(parts[1]),
            value=_clean(parts[2], VALUE_LIMIT),
            states=states,
            depth=depth,
        ))
    return nodes


def to_tree(nodes: Sequence[Node]) -> List[Dict[str, object]]:
    """Nested view of a flat, depth-annotated node list."""
    roots: List[Dict[str, object]] = []
    stack: List[Tuple[int, Dict[str, object]]] = []
    for node in nodes:
        item = node.as_dict()
        item["children"] = []
        while stack and stack[-1][0] >= node.depth:
            stack.pop()
        if stack:
            stack[-1][1]["children"].append(item)  # type: ignore[index]
        else:
            roots.append(item)
        stack.append((node.depth, item))
    return roots


def summarize(nodes: Sequence[Node]) -> Dict[str, object]:
    roles: Dict[str, int] = {}
    states: Dict[str, int] = {}
    for node in nodes:
        roles[node.role] = roles.get(node.role, 0) + 1
        for state in node.states:
            states[state] = states.get(state, 0) + 1
    top = sorted(roles.items(), key=lambda pair: (-pair[1], pair[0]))
    return {"nodes": len(nodes), "roles": dict(top), "states": states}


# --------------------------------------------------------------------------- #
# rendering
# --------------------------------------------------------------------------- #

def wrap(text: str, width: int, indent: str = "") -> List[str]:
    """Hard wrap with a hanging indent, so 40 columns stay readable."""
    width = max(20, width)
    if width <= 1:
        return [indent + text]
    body_width = max(8, width - len(indent))
    out: List[str] = []
    for line in text.split("\n"):
        remaining = line
        first = True
        while remaining:
            room = body_width if not first else max(8, width)
            if len(remaining) <= room:
                out.append((indent if not first else "") + remaining)
                break
            cut = remaining.rfind(" ", 0, room + 1)
            if cut <= 0:
                cut = room
            out.append((indent if not first else "") + remaining[:cut].rstrip())
            remaining = remaining[cut:].lstrip()
            first = False
        if not remaining:
            continue
    return out or [indent.rstrip()]


def _line(node: Node, show_value: bool) -> str:
    parts = [node.role]
    if node.name:
        parts.append(node.name)
    text = " ".join(parts)
    if show_value and node.value:
        text += " = " + node.value
    if node.states:
        text += " [" + ",".join(node.states) + "]"
    return text


def render(
    nodes: Sequence[Node],
    width: int = 80,
    color: bool = False,
    show_value: bool = True,
) -> str:
    lines: List[str] = []
    for node in nodes:
        prefix = "  " * node.depth
        if node.depth and not prefix:
            prefix = ""
        body = prefix + _line(node, show_value)
        hanging = " " * min(len(prefix) + 2, max(0, width - 8))
        wrapped = wrap(body, width, indent=hanging)
        if color and not lines:
            wrapped[0] = "\033[1;36m" + wrapped[0] + "\033[0m"
        lines.extend(wrapped)
    return "\n".join(lines)


def describe(nodes: Sequence[Node], limit: int) -> str:
    """One-line summary, what ``--remember`` stores in memory."""
    counts = summarize(nodes)
    roles = counts["roles"]  # type: ignore[index]
    controls = 0
    labels = ("button", "entry", "text field", "checkbox", "radio", "toggle",
              "link", "menu item", "tab", "slider", "combo box", "push button")
    for role, count in roles.items():  # type: ignore[union-attr]
        if any(word in role.lower() for word in labels):
            controls += count
    readable = ", ".join("{} {}".format(v, k) for k, v in list(roles.items())[:limit])  # type: ignore[union-attr]
    return "{} nodes, {} controls ({})".format(counts["nodes"], controls, readable or "no roles")


# --------------------------------------------------------------------------- #
# backends
# --------------------------------------------------------------------------- #

MACOS_SCRIPT = r"""
function run(argv) {
  var se = Application('System Events');
  var want = argv.length > 0 ? String(argv[0]) : '';
  var depthLimit = argv.length > 1 ? parseInt(argv[1], 10) : 0;
  var lines = [];
  function safe(fn, fallback) {
    try { var v = fn(); return (v === null || v === undefined) ? fallback : v; }
    catch (e) { return fallback; }
  }
  function pad(depth) { var s = ''; for (var i = 0; i < depth; i++) { s += '  '; } return s; }
  function clean(v, limit) {
    var s = String(v === undefined || v === null ? '' : v).replace(/[\r\n\t]+/g, ' ');
    s = s.replace(/\|/g, '/').replace(/\s+/g, ' ').replace(/^\s+|\s+$/g, '');
    return s.length > limit ? s.substring(0, limit - 1) + '\u2026' : s;
  }
  var procs = se.applicationProcesses();
  var target = null;
  for (var i = 0; i < procs.length; i++) {
    var p = procs[i];
    var name = clean(safe(function () { return p.name(); }, ''), 80);
    if (want) { if (name === want) { target = p; break; } }
    else if (safe(function () { return p.frontmost(); }, false)) { target = p; break; }
  }
  if (!target) { throw new Error('no matching application: ' + (want || '(frontmost)')); }
  function walk(el, depth) {
    if (depthLimit && depth > depthLimit) { return; }
    var role = clean(safe(function () { return el.role(); }, 'element'), 40);
    var name = clean(safe(function () { return el.name(); }, ''), 60);
    var value = clean(safe(function () { return el.value(); }, ''), 60);
    var states = [];
    if (safe(function () { return el.focused(); }, false)) { states.push('focused'); }
    if (safe(function () { return el.selected(); }, false)) { states.push('selected'); }
    if (!safe(function () { return el.enabled(); }, true)) { states.push('disabled'); }
    lines.push(pad(depth) + [role, name, value, states.join(',')].join('|'));
    var kids = safe(function () { return el.uiElements(); }, []);
    for (var k = 0; k < kids.length; k++) { walk(kids[k], depth + 1); }
  }
  var windows = safe(function () { return target.windows(); }, []);
  for (var w = 0; w < windows.length; w++) { walk(windows[w], 0); }
  return lines.join('\n');
}
"""

MACOS_APPS = r"""
function run() {
  var se = Application('System Events');
  var out = [];
  var procs = se.applicationProcesses();
  for (var i = 0; i < procs.length; i++) {
    try {
      if (procs[i].backgroundOnly()) { continue; }
      out.push(String(procs[i].name()));
    } catch (e) {}
  }
  return out.join('\n');
}
"""

WINDOWS_SCRIPT = r"""
param([string]$App = "", [int]$Depth = 0)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$walker = [System.Windows.Automation.TreeWalker]::ControlViewWalker
$root = $null
if ($App -ne "") {
  $cond = New-Object System.Windows.Automation.PropertyCondition(
    [System.Windows.Automation.AutomationElement]::NameProperty, $App)
  $root = [System.Windows.Automation.AutomationElement]::RootElement.FindFirst(
    [System.Windows.Automation.TreeScope]::Children, $cond)
} else {
  $root = [System.Windows.Automation.AutomationElement]::FocusedElement
}
if ($null -eq $root) { Write-Error "no matching application: $App"; exit 3 }
function Clean([object]$value, [int]$limit) {
  if ($null -eq $value) { return "" }
  $s = ([string]$value) -replace "[\r\n\t]+", " "
  $s = $s -replace "\|", "/"
  $s = ($s -replace "\s+", " ").Trim()
  if ($s.Length -gt $limit) { $s = $s.Substring(0, $limit - 1) + [char]0x2026 }
  return $s
}
function Walk([object]$element, [int]$depth) {
  if ($Depth -gt 0 -and $depth -gt $Depth) { return }
  $role = Clean $element.Current.ControlType.ProgrammaticName 40
  $role = $role -replace "^ControlType\.", ""
  $name = Clean $element.Current.Name 60
  $value = ""
  try {
    $pattern = $null
    if ($element.TryGetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern, [ref]$pattern)) {
      $value = Clean $pattern.Current.Value 60
    }
  } catch {}
  $states = @()
  if ($element.Current.IsKeyboardFocusable) { $states += "focusable" }
  if ($element.Current.HasKeyboardFocus) { $states += "focused" }
  if ($element.Current.IsEnabled -eq $false) { $states += "disabled" }
  $line = ("  " * $depth) + (@($role, $name, $value, ($states -join ",")) -join "|")
  Write-Output $line
  $child = $walker.GetFirstChild($element)
  while ($null -ne $child) {
    Walk $child ($depth + 1)
    $child = $walker.GetNextSibling($child)
  }
}
Walk $root 0
"""

WINDOWS_APPS = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$walker = [System.Windows.Automation.TreeWalker]::ControlViewWalker
$child = $walker.GetFirstChild([System.Windows.Automation.AutomationElement]::RootElement)
while ($null -ne $child) {
  $name = $child.Current.Name
  if ($name) { Write-Output $name }
  $child = $walker.GetNextSibling($child)
}
"""

LINUX_SCRIPT = r"""
import sys

try:
    import pyatspi
except ImportError:
    sys.stderr.write("pyatspi is not installed\n")
    raise SystemExit(3)

want = sys.argv[1] if len(sys.argv) > 1 else ""
limit = int(sys.argv[2]) if len(sys.argv) > 2 else 0
desktop = pyatspi.Registry.getDesktop(0)
target = None
for app in desktop:
    try:
        name = app.name or ""
    except Exception:
        continue
    if want:
        if name == want:
            target = app
            break
    else:
        try:
            if app.getState().contains(pyatspi.STATE_ACTIVE):
                target = app
                break
        except Exception:
            pass
if target is None:
    sys.stderr.write("no matching application: %s\n" % (want or "(active)"))
    raise SystemExit(3)


def clean(value, size):
    text = "" if value is None else str(value)
    text = " ".join(text.replace("|", "/").split())
    return text[: size - 1] + "\u2026" if len(text) > size else text


def walk(node, depth):
    if limit and depth > limit:
        return
    try:
        role = clean(node.getRoleName(), 40) or "element"
    except Exception:
        role = "element"
    try:
        name = clean(node.name, 60)
    except Exception:
        name = ""
    try:
        value = clean(node.description, 60)
    except Exception:
        value = ""
    try:
        state = node.getState()
        flags = []
        if state.contains(pyatspi.STATE_FOCUSED):
            flags.append("focused")
        if state.contains(pyatspi.STATE_SELECTED):
            flags.append("selected")
        if state.contains(pyatspi.STATE_CHECKED):
            flags.append("checked")
        if not state.contains(pyatspi.STATE_ENABLED):
            flags.append("disabled")
        if not state.contains(pyatspi.STATE_SHOWING):
            flags.append("hidden")
    except Exception:
        flags = []
    sys.stdout.write("  " * depth + "|".join([role, name, value, ",".join(flags)]) + "\n")
    try:
        total = node.childCount
    except Exception:
        total = 0
    for index in range(total):
        try:
            walk(node[index], depth + 1)
        except Exception:
            continue


walk(target, 0)
"""

LINUX_APPS = r"""
import sys

try:
    import pyatspi
except ImportError:
    sys.stderr.write("pyatspi is not installed\n")
    raise SystemExit(3)

for app in pyatspi.Registry.getDesktop(0):
    try:
        if app.name:
            print(app.name)
    except Exception:
        continue
"""

TEST_LINUX = "import pyatspi"


@dataclass
class Capture:
    ok: bool
    backend: str
    text: str = ""
    app: str = ""
    error: str = ""
    hint: str = ""

    def nodes(self) -> List[Node]:
        return parse_dump(self.text)


def _run(argv: Sequence[str], env: Optional[Dict[str, str]] = None, timeout: int = 25) -> Tuple[int, str, str]:
    try:
        process = subprocess.run(
            list(argv),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            timeout=timeout,
        )
    except FileNotFoundError:
        return 127, "", "not found: " + argv[0]
    except subprocess.TimeoutExpired:
        return 124, "", "timed out after {}s".format(timeout)
    except OSError as exc:
        return 1, "", str(exc)
    return (
        process.returncode,
        process.stdout.decode("utf-8", "replace").strip(),
        process.stderr.decode("utf-8", "replace").strip(),
    )


def _temp_script(suffix: str, body: str) -> str:
    handle, path = tempfile.mkstemp(prefix="orchestra-tx-a11y-", suffix=suffix)
    with os.fdopen(handle, "w", encoding="utf-8") as stream:
        stream.write(body)
    return path


def _platform() -> str:
    names = {"darwin": "macos", "win32": "windows", "linux": "linux"}
    return names.get(sys.platform, sys.platform)


def available() -> List[Tuple[str, bool, str]]:
    """(backend, usable, detail) for every backend on this machine."""
    rows: List[Tuple[str, bool, str]] = []
    osascript = shutil.which("osascript")
    rows.append(("macos", bool(osascript) and sys.platform == "darwin",
                 osascript or "needs macOS and osascript"))
    powershell = shutil.which("powershell") or shutil.which("pwsh")
    rows.append(("windows", bool(powershell) and sys.platform == "win32",
                 powershell or "needs Windows PowerShell"))
    python = _atspi_python()
    rows.append(("linux", bool(python), (python + " + pyatspi") if python else "needs pyatspi (python3-pyatspi)"))
    adb = shutil.which("adb")
    dump = shutil.which("uiautomator")
    rows.append(("android", bool(adb or dump),
                 (adb + " (adb)" if adb else (dump or "needs adb or uiautomator"))))
    return rows


def _atspi_python() -> Optional[str]:
    for candidate in (sys.executable, "/usr/bin/python3", "/usr/local/bin/python3"):
        if not candidate or not Path(candidate).exists():
            continue
        code, _, _ = _run([candidate, "-c", TEST_LINUX], timeout=10)
        if code == 0:
            return candidate
    return None


def pick(backend: Optional[str] = None) -> Tuple[Optional[str], str, List[Tuple[str, bool, str]]]:
    rows = available()
    if backend:
        for name, usable, detail in rows:
            if name == backend:
                return (name if usable else None), detail, rows
        return None, "unknown backend: {}".format(backend), rows
    order = {"darwin": ["macos"], "win32": ["windows"]}.get(
        sys.platform, ["linux", "android"] if sys.platform == "linux" else ["linux"])
    for name in order:
        for candidate, usable, _detail in rows:
            if candidate == name and usable:
                return name, "", rows
    return None, "no accessibility backend available", rows


# --------------------------------------------------------------------------- #
# capture
# --------------------------------------------------------------------------- #

def capture(app: str = "", depth: int = MAX_DEPTH, backend: Optional[str] = None) -> Capture:
    name, detail, _rows = pick(backend)
    if not name:
        return Capture(ok=False, backend=backend or _platform(), error=detail,
                       hint="run 'orchestra-tx see --backends' to see what this machine exposes")
    depth = max(1, depth) if depth else 0

    if name == "macos":
        script = _temp_script(".js", MACOS_SCRIPT)
        try:
            code, out, err = _run(["osascript", "-l", "JavaScript", script, app, str(depth)])
        finally:
            _silent_unlink(script)
        if code != 0:
            return Capture(ok=False, backend=name, error=err or "osascript failed (exit {})".format(code),
                           hint="macOS: System Settings > Privacy & Security > Accessibility")
        return Capture(ok=True, backend=name, text=out, app=app)

    if name == "windows":
        script = _temp_script(".ps1", WINDOWS_SCRIPT)
        binary = shutil.which("powershell") or shutil.which("pwsh") or "powershell"
        try:
            code, out, err = _run([binary, "-NoProfile", "-NonInteractive",
                                   "-ExecutionPolicy", "Bypass", "-File", script,
                                   "-App", app, "-Depth", str(depth)])
        finally:
            _silent_unlink(script)
        if code != 0:
            return Capture(ok=False, backend=name, error=err or "UI Automation failed (exit {})".format(code))
        return Capture(ok=True, backend=name, text=out, app=app)

    if name == "linux":
        python = _atspi_python()
        if not python:
            return Capture(ok=False, backend=name, error="pyatspi is not installed",
                           hint="Debian/Ubuntu: sudo apt install python3-pyatspi")
        code, out, err = _run([python, "-c", LINUX_SCRIPT, app, str(depth)])
        if code != 0:
            return Capture(ok=False, backend=name, error=err or "AT-SPI failed (exit {})".format(code),
                           hint="make sure accessibility bus is running: gsettings set org.gnome.desktop.interface toolkit-accessibility true")
        return Capture(ok=True, backend=name, text=out, app=app)

    return _capture_android(app, depth)


def _capture_android(app: str, depth: int) -> Capture:
    adb = shutil.which("adb")
    remote = "/sdcard/window_dump.xml"
    if adb:
        code, _out, err = _run([adb, "shell", "uiautomator", "dump", remote])
        if code != 0:
            return Capture(ok=False, backend="android", error=err or "uiautomator dump failed", hint=_ADB_HINT)
        code, xml, err = _run([adb, "shell", "cat", remote])
        if code != 0:
            return Capture(ok=False, backend="android", error=err or "could not read the dump", hint=_ADB_HINT)
    else:
        dump = shutil.which("uiautomator")
        if not dump:
            return Capture(ok=False, backend="android", error="needs adb or uiautomator", hint=_ADB_HINT)
        target = "/data/local/tmp/orchestra-tx-window.xml"
        code, _out, err = _run([dump, "dump", target])
        if code != 0:
            return Capture(ok=False, backend="android", error=err or "uiautomator dump failed", hint=_ADB_HINT)
        try:
            xml = Path(target).read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return Capture(ok=False, backend="android", error=str(exc), hint=_ADB_HINT)
    text = parse_android_xml(xml, depth=depth, app=app)
    return Capture(ok=True, backend="android", text=text, app=app)


_ADB_HINT = "adb: enable wireless debugging and pair, or use 'adb shell uiautomator dump'"


def parse_android_xml(xml: str, depth: int = 0, app: str = "") -> str:
    """Turn a uiautomator dump into the wire format."""
    import xml.etree.ElementTree as ElementTree

    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError as exc:
        raise ValueError("unreadable uiautomator dump: {}".format(exc))

    lines: List[str] = []

    def walk(element, level: int) -> None:
        if depth and level > depth:
            return
        role = _clean(str(element.get("class", "node")).split(".")[-1], 40) or "node"
        label = element.get("text") or element.get("content-desc") or ""
        value = element.get("resource-id") or element.get("bounds") or ""
        states: List[str] = []
        for flag in ("clickable", "focused", "selected", "checked", "scrollable", "long-clickable"):
            if element.get(flag) == "true":
                states.append(flag)
        if element.get("enabled") == "false":
            states.append("disabled")
        lines.append("  " * level + "|".join([
            role, _clean(label), _clean(value), ",".join(states)]))
        for child in list(element):
            walk(child, level + 1)

    walk(root, 0)
    if app:
        kept = [line for line in lines if app.lower() in line.lower()]
        if kept:
            lines = kept
    return "\n".join(lines)


def list_apps(backend: Optional[str] = None) -> Tuple[List[str], str]:
    name, detail, _rows = pick(backend)
    if not name:
        return [], detail
    if name == "macos":
        script = _temp_script(".js", MACOS_APPS)
        try:
            code, out, err = _run(["osascript", "-l", "JavaScript", script])
        finally:
            _silent_unlink(script)
        return ([line for line in out.split("\n") if line.strip()], err if code else "")
    if name == "windows":
        script = _temp_script(".ps1", WINDOWS_APPS)
        binary = shutil.which("powershell") or shutil.which("pwsh") or "powershell"
        try:
            code, out, err = _run([binary, "-NoProfile", "-NonInteractive",
                                   "-ExecutionPolicy", "Bypass", "-File", script])
        finally:
            _silent_unlink(script)
        return ([line.strip() for line in out.split("\n") if line.strip()], err if code else "")
    if name == "linux":
        python = _atspi_python()
        if not python:
            return [], "pyatspi is not installed"
        code, out, err = _run([python, "-c", LINUX_APPS])
        return ([line.strip() for line in out.split("\n") if line.strip()], err if code else "")
    capture_result = _capture_android("", MAX_DEPTH)
    packages: List[str] = []
    for node in capture_result.nodes():
        if node.value and "/" not in node.value and node.value not in packages:
            packages.append(node.value)
    return packages, capture_result.error


def _silent_unlink(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


def report_rows() -> List[Tuple[str, str, bool]]:
    rows: List[Tuple[str, str, bool]] = []
    for name, usable, detail in available():
        rows.append(("a11y " + name, detail if usable else "unavailable ({})".format(detail), usable))
    return rows


def dump_json(capture_result: Capture, nodes: Sequence[Node]) -> str:
    payload = {
        "backend": capture_result.backend,
        "app": capture_result.app,
        "summary": summarize(nodes),
        "tree": to_tree(nodes),
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)
