from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Optional

# Match Jira / Linear / YouTrack issue keys like ENG-1420, CORE-88, ABC-12
# Exclude common technical tokens such as UTF-8, SHA-256, HTTP-2, TLS-1, RFC-9113
_TICKET_FALSE_POSITIVES: frozenset[str] = frozenset({
    "UTF", "SHA", "MD", "HTTP", "HTTPS", "TLS", "SSL", "RFC", "CVE", "CWE",
    "ISO", "ANSI", "ASCII", "POSIX", "JSON", "YAML", "TOML", "HTML", "CSS",
    "TCP", "UDP", "DNS", "SSH", "RSA", "AES", "ECDSA", "HMAC", "JWT", "CORS",
    "PEP", "API", "CLI", "SDK", "EOF", "EOL", "WIP", "TBD", "TODO", "FIXME",
    "CPU", "GPU", "RAM", "SSD", "HDD", "OS", "WIN", "MAC", "ARM", "X86",
    "ADR", "INC", "SEV",
})

EXTERNAL_TICKET_PATTERN = re.compile(r"\b(?P<proj>[A-Z]{2,10})-(?P<num>\d{1,6})\b")

# Incident markers in PRs, commits, or postmortem docs
INCIDENT_KEY_PATTERN = re.compile(r"\b(?P<key>INC-\d{1,6}|SEV-?[12]|P[01]-INCIDENT)\b", re.IGNORECASE)
POSTMORTEM_MARKER = re.compile(r"\b(postmortem|post-mortem|incident\s+report|outage|hotfix)\b", re.IGNORECASE)

# ADR / RFC Markdown frontmatter & status line patterns
_FRONTMATTER_RE = re.compile(r"\A---\s*\n(?P<yaml>.*?)\n---\s*\n", re.DOTALL)
_ADR_STATUS_LINE = re.compile(
    r"^[ \t]*(?:\*\*)?Status(?:\*\*)?:\s*(?P<status>[A-Za-z][A-Za-z0-9 _-]{1,40})",
    re.IGNORECASE | re.MULTILINE,
)
_ADR_SUPERSEDED_BY = re.compile(
    r"(?:Superseded|Replaced)\s+by\s+(?P<target>ADR-?\d+|RFC-?\d+|[\w./-]+\.md)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class DocumentMetadata:
    doc_kind: str  # "adr", "rfc", "postmortem", "changelog", "markdown"
    status: Optional[str] = None
    superseded_by: Optional[str] = None
    external_tickets: list[str] = field(default_factory=list)
    incident_keys: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class IncidentRecord:
    id: str
    repo: str
    key: str
    severity: str
    title: str
    source_id: str
    source_url: str = ""


def extract_external_tickets(text: str) -> list[str]:
    """Extract Jira/Linear style ticket keys (e.g. ENG-1420) while filtering technical tokens."""
    if not text:
        return []
    found: list[str] = []
    seen: set[str] = set()
    for match in EXTERNAL_TICKET_PATTERN.finditer(text):
        proj = match.group("proj")
        if proj in _TICKET_FALSE_POSITIVES:
            continue
        ticket = f"{proj}-{match.group('num')}"
        if ticket not in seen:
            seen.add(ticket)
            found.append(ticket)
    return found


def extract_incident_signals(text: str) -> tuple[list[str], bool]:
    """Return (incident_keys, is_postmortem_or_hotfix) from text."""
    if not text:
        return [], False
    keys: list[str] = []
    seen: set[str] = set()
    for match in INCIDENT_KEY_PATTERN.finditer(text):
        key = match.group("key").upper()
        if key not in seen:
            seen.add(key)
            keys.append(key)
    is_postmortem = bool(POSTMORTEM_MARKER.search(text))
    return keys, is_postmortem


def parse_document_metadata(path: str, content: str) -> DocumentMetadata:
    """Parse ADR/RFC frontmatter, status lines, external tickets, and incident markers."""
    lower_path = path.lower()
    if "adr" in lower_path:
        doc_kind = "adr"
    elif "rfc" in lower_path:
        doc_kind = "rfc"
    elif "postmortem" in lower_path or "incident" in lower_path:
        doc_kind = "postmortem"
    elif "changelog" in lower_path or "changes" in lower_path:
        doc_kind = "changelog"
    else:
        doc_kind = "markdown"

    status: Optional[str] = None
    superseded_by: Optional[str] = None

    fm_match = _FRONTMATTER_RE.match(content or "")
    if fm_match:
        for line in fm_match.group("yaml").splitlines():
            if ":" not in line:
                continue
            k, _, v = line.partition(":")
            kl = k.strip().lower()
            val = v.strip().strip("'\"")
            if kl == "status" and val:
                status = val
            elif kl in ("superseded_by", "replaced_by") and val:
                superseded_by = val

    if status is None:
        st_match = _ADR_STATUS_LINE.search(content or "")
        if st_match:
            status = st_match.group("status").strip()

    if superseded_by is None:
        sup_match = _ADR_SUPERSEDED_BY.search(content or "")
        if sup_match:
            superseded_by = sup_match.group("target").strip()

    tickets = extract_external_tickets(content or "")
    inc_keys, _ = extract_incident_signals(content or "")
    return DocumentMetadata(
        doc_kind=doc_kind,
        status=status,
        superseded_by=superseded_by,
        external_tickets=tickets,
        incident_keys=inc_keys,
    )


def detect_incident_from_source(
    *,
    repo: str,
    source_id: str,
    title: str,
    body: str,
    source_url: str = "",
) -> Optional[IncidentRecord]:
    """Build an IncidentRecord if a PR/commit/doc carries explicit incident markers."""
    combined = f"{title}\n{body}"
    keys, is_pm = extract_incident_signals(combined)
    if not keys and not is_pm:
        return None
    inc_keys = [k for k in keys if k.startswith("INC-")]
    primary_key = (
        inc_keys[0]
        if inc_keys
        else (keys[0] if keys else f"HOTFIX-{hashlib.sha256(source_id.encode('utf-8')).hexdigest()[:6].upper()}")
    )
    severity = "SEV-1" if any("SEV-1" in k or "SEV1" in k or "P0" in k for k in keys) else "SEV-2"
    inc_id = f"incident:{repo}:{primary_key}"
    return IncidentRecord(
        id=inc_id,
        repo=repo,
        key=primary_key,
        severity=severity,
        title=(title or primary_key)[:200],
        source_id=source_id,
        source_url=source_url,
    )
