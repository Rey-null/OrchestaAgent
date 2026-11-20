"""Goldfish review parsing, merging, summarising and rendering.

The parser is deliberately tolerant: a heading shape and a bullet shape both
work, and every finding keeps its ``raw`` text so a line we could not structure
is displayed instead of dropped. Ids are content hashes of
``persona|location|claim`` so re-importing a revised report keeps triage.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..ui import layout, theme

SEVERITIES = ("blocker", "major", "minor", "nit")
SETTLED_DECISIONS = ("propose", "contest", "decline")
DECISIONS = ("propose", "contest", "escalate", "decline", "skip")
DECISION_LETTERS = {"p": "propose", "c": "contest", "e": "escalate", "d": "decline", "s": "skip"}

_SEV_RE = re.compile(r"\b(blockers?|majors?|minors?|nits?)\b", re.IGNORECASE)
_SEV_MAP = {
    "blocker": "blocker", "blockers": "blocker",
    "major": "major", "majors": "major",
    "minor": "minor", "minors": "minor",
    "nit": "nit", "nits": "nit",
}
_DOC_META_RE = re.compile(r"^\s*\**\s*(host|round|date|design|stage|scope)\s*\**\s*[:=]\s*(.+?)\s*$", re.IGNORECASE)
_BULLET_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.*)$")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_SEVERITY_TAG_RE = re.compile(r"^\s*\[(?:blocker|major|minor|nit)\]\s*", re.IGNORECASE)
_ID_PREFIX = re.compile(r"^\[?[A-Z]{1,3}[-_]?\d+\]?\s*(?:[\u2014\u2013:|.\-]\s*)?")
_CLAIM_SEV_RE = re.compile(r"^\s*(blockers?|majors?|minors?|nits?)\s*[:=]\s*", re.IGNORECASE)
_LABELS = {
    "persona": "persona", "reviewer": "persona", "role": "persona",
    "location": "location", "where": "location", "file": "location", "path": "location",
    "severity": "severity",
}


@dataclass
class Finding:
    id: str = ""
    severity: str = "unknown"
    persona: str = "unassigned"
    location: str = ""
    claim: str = ""
    raw: str = ""

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "severity": self.severity,
            "persona": self.persona,
            "location": self.location,
            "claim": self.claim,
            "raw": self.raw,
        }


def _norm(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def finding_id(persona: str, location: str, claim: str) -> str:
    blob = "|".join(_norm(part) for part in (persona, location, claim))
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:8]


def _severity(text: str, limit: int = 0) -> str:
    """First severity word; ``limit`` keeps a later mention out of the lead."""
    text = text or ""
    if limit:
        text = " ".join(text.split()[:limit])
    for word in _SEV_RE.findall(text):
        return _SEV_MAP[word.lower()]
    return ""


def _segments(text: str) -> Tuple[Dict[str, str], List[str]]:
    parts = re.split(r"\s*(?:\u2014|\u2013|\||;|\s-\s)\s*", text or "")
    meta: Dict[str, str] = {}
    rest: List[str] = []
    for part in parts:
        cleaned = part.replace("**", "").replace("__", "").strip()
        match = re.match(r"^(?i:([A-Za-z]+))\s*[:=]\s*(.+)$", cleaned)
        key = _LABELS.get(match.group(1).lower(), "") if match else ""
        if key:
            meta[key] = match.group(2).strip().strip("*_` ")
        elif part.strip():
            rest.append(part.strip())
    return meta, rest


def _clean_claim(parts: Sequence[str]) -> str:
    text = " ".join(parts).strip()
    text = _SEVERITY_TAG_RE.sub("", text)
    text = _ID_PREFIX.sub("", text)
    text = _CLAIM_SEV_RE.sub("", text)
    return text.replace("**", "").replace("__", "").strip(" \t*-")


def parse_report(text: str) -> Tuple[List[Finding], Dict[str, str]]:
    """Return ``(findings, document_metadata)`` for a review report."""
    findings: List[Finding] = []
    meta: Dict[str, str] = {}
    section_severity = ""
    section_persona = ""
    current: Optional[dict] = None

    def close() -> None:
        nonlocal current
        if current is None:
            return
        claim = " ".join([current["claim"]] + current["extra"]).strip()
        claim = re.sub(r"\s+", " ", claim)
        persona = current["persona"] or section_persona or "unassigned"
        findings.append(Finding(
            id=finding_id(persona, current["location"], claim or current["raw"]),
            severity=current["severity"] or "unknown",
            persona=persona,
            location=current["location"],
            claim=claim,
            raw=current["raw"].strip(),
        ))
        current = None

    def start(body: str, explicit_severity: str, raw: str, inherited: str) -> None:
        nonlocal current
        body = _SEVERITY_TAG_RE.sub("", body.strip())
        segments, rest = _segments(body)
        severity = (
            _SEV_MAP.get(segments.get("severity", "").lower(), "")
            or explicit_severity
            or inherited
        )
        current = {
            "severity": severity if severity in SEVERITIES else "",
            "persona": segments.get("persona", ""),
            "location": segments.get("location", ""),
            "claim": _clean_claim(rest),
            "raw": raw,
            "extra": [],
        }

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            continue

        heading = _HEADING_RE.match(line)
        if heading:
            close()
            level = len(heading.group(1))
            body = heading.group(2).strip()
            document = _DOC_META_RE.match(body)
            if document:
                meta[document.group(1).lower()] = document.group(2).strip()
                continue
            severity = _severity(body, limit=4)
            segments, rest = _segments(body)
            words = body.split()
            if severity and not segments and len(words) <= 3:
                section_severity = severity
                section_persona = ""
                continue
            if segments.get("persona") and not rest and not severity:
                section_persona = segments["persona"]
                continue
            if severity or segments.get("persona") or segments.get("location"):
                start(body, severity, raw_line, section_severity)
            elif level >= 3 and rest:
                start(body, severity, raw_line, section_severity)
            continue

        document = _DOC_META_RE.match(line)
        if document:
            close()
            meta[document.group(1).lower()] = document.group(2).strip()
            continue

        bullet = _BULLET_RE.match(line)
        if bullet:
            close()
            body = bullet.group(1).strip()
            start(body, _severity(body, limit=4), raw_line, section_severity)
            continue

        if current is not None:
            current["extra"].append(line.strip())
            current["raw"] += "\n" + line.strip()

    close()
    return findings, meta


def decision_of(value: Any) -> str:
    """Normalise a stored decision or a one-key letter; ``""`` when unknown."""
    if isinstance(value, dict):
        value = value.get("decision", "")
    word = str(value or "").strip().lower()
    if len(word) == 1:
        word = DECISION_LETTERS.get(word, "")
    return word if word in DECISIONS else ""


def merge(previous: Sequence[dict], imported: Sequence[Finding], triage: Optional[dict] = None) -> Tuple[List[dict], Dict[str, int]]:
    """Merge a fresh import into stored findings, preserving triage decisions."""
    triage = triage or {}
    by_id = {row.get("id"): row for row in previous if isinstance(row, dict)}
    by_slot: Dict[Tuple[str, str], dict] = {}
    for row in previous:
        if isinstance(row, dict):
            by_slot[(str(row.get("persona") or ""), str(row.get("location") or ""))] = row

    counts = {"new": 0, "changed": 0, "unchanged": 0}
    merged: List[dict] = []
    for finding in imported:
        row = finding.as_dict() if isinstance(finding, Finding) else dict(finding)
        old = by_id.get(row["id"])
        if old is not None:
            state = "unchanged"
        else:
            old = by_slot.get((row.get("persona", ""), row.get("location", "")))
            state = "changed" if old is not None else "new"
        decision = decision_of(triage.get(row["id"])) or (decision_of(old.get("decision")) if old else "")
        row["decision"] = decision
        row["state"] = state
        counts[state] += 1
        merged.append(row)
    return merged, counts


def is_settled(finding: dict) -> bool:
    return decision_of(finding.get("decision")) in SETTLED_DECISIONS


def unsettled(findings: Sequence[dict], severities: Sequence[str] = ("blocker", "major")) -> List[dict]:
    return [
        row for row in findings
        if isinstance(row, dict) and row.get("severity") in severities and not is_settled(row)
    ]


def ordered(findings: Sequence[dict]) -> List[dict]:
    """Blockers first, then persona and id, so reading and triage are stable."""
    rank = {name: index for index, name in enumerate(SEVERITIES)}
    rows = [row for row in findings if isinstance(row, dict)]
    return sorted(rows, key=lambda row: (
        rank.get(str(row.get("severity") or "").lower(), len(SEVERITIES)),
        str(row.get("persona") or "").lower(),
        str(row.get("id") or ""),
    ))


def filtered(findings: Sequence[dict], severities: Sequence[str] = (),
             personas: Sequence[str] = ()) -> List[dict]:
    """Keep rows matching every given filter; no filter keeps everything."""
    wanted_sev = {str(name).strip().lower() for name in severities}
    wanted_persona = {str(name).strip().lower() for name in personas}
    rows: List[dict] = []
    for row in findings:
        if not isinstance(row, dict):
            continue
        if wanted_sev and str(row.get("severity") or "").lower() not in wanted_sev:
            continue
        if wanted_persona and str(row.get("persona") or "").lower() not in wanted_persona:
            continue
        rows.append(row)
    return rows


def summarize(findings: Sequence[dict]) -> dict:
    by_severity = {name: 0 for name in SEVERITIES}
    by_persona: Dict[str, int] = {}
    settled = 0
    for row in findings:
        if not isinstance(row, dict):
            continue
        severity = str(row.get("severity") or "unknown").lower()
        by_severity[severity] = by_severity.get(severity, 0) + 1
        persona = str(row.get("persona") or "unassigned")
        by_persona[persona] = by_persona.get(persona, 0) + 1
        if is_settled(row):
            settled += 1
    total = sum(1 for row in findings if isinstance(row, dict))
    return {
        "total": total,
        "open": total - settled,
        "settled": settled,
        "by_severity": by_severity,
        "by_persona": by_persona,
    }


def render_findings(findings: Sequence[dict], width: int = 80, color_mode: str = "never",
                    raw: bool = False, head: str = "severity") -> List[str]:
    """One block per finding, wrapped so no line exceeds ``width``.

    ``raw`` shows the reviewer's own text instead of the parsed claim. ``head``
    picks the heading: ``severity`` (default), ``id`` (id first, for a screen
    reader mid-triage) or ``persona`` (a caller already printed the severity).
    """
    lines: List[str] = []
    for row in findings:
        if not isinstance(row, dict):
            continue
        label = layout.severity_label(row.get("severity"))
        persona = str(row.get("persona") or "unassigned")
        ident = str(row.get("id") or "")
        if head == "id":
            title = "{}  {} / {}".format(ident, label, persona)
        elif head == "persona":
            title = persona
        else:
            title = "{} {}".format(label, persona)
        # Wrap first, paint after: escapes would otherwise count as width and
        # leave the colour open across the line break.
        for piece in theme.wrap(title, width, indent=0, hang=2):
            lines.append(theme.paint(piece, str(row.get("severity") or ""), color_mode))
        location = str(row.get("location") or "")
        if location:
            lines.extend(theme.wrap("at " + location, width, indent=2, hang=2))
        claim = (str(row.get("raw") or "") if raw else str(row.get("claim") or row.get("raw") or ""))
        lines.extend(theme.wrap(claim or "(no claim text)", width, indent=2, hang=2))
        if head != "id":
            meta = "id " + ident
            if row.get("state"):
                meta += "  " + str(row["state"])
            if row.get("decision"):
                meta += "  " + str(row["decision"])
            lines.extend(theme.wrap(meta, width, indent=2, hang=2))
        lines.append("")
    return lines
