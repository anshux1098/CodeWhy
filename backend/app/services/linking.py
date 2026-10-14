from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Sequence

from app.schemas.common import EntityType, SourceType
from app.services.ingest.git_collect import (
    GITHUB_ISSUE_URL,
    GITHUB_PULL_URL,
    ISSUE_REFERENCE,
    extract_pull_request_numbers,
    strip_code,
)
from app.stores.sqlite_cache import SqliteCache, stable_id

REVERT_COMMIT_PATTERN = re.compile(
    r"This reverts commit ([0-9a-f]{7,40})", re.IGNORECASE
)
REVERT_TRAILER_PATTERN = re.compile(
    r"^Reverts:\s*([0-9a-f]{7,40})", re.IGNORECASE | re.MULTILINE
)

CLOSING_KEYWORDS = re.compile(
    r"\b(?P<kw>fixes|fixed|fix|closes|closed|close|resolves|resolved|resolve)"
    r"[\s:]+(?:#(?P<num>\d{1,6})|(?P<url>https?://github\.com/[^/\s]+/[^/\s]+/(?:issues|pull)/(?P<url_num>\d+)))",
    re.IGNORECASE,
)

ADR_SUPERSEDED_PATTERN = re.compile(
    r"^[ \t]*Status:[ \t]*(?:Superseded|Replaced)\s+by\s+(?P<target>ADR-?\d+|[\w./-]+)",
    re.IGNORECASE | re.MULTILINE,
)

NON_MODULE_DIRS = frozenset({
    ".github",
    ".git",
    "docs",
    "doc",
    "tests",
    "test",
    "scripts",
    "benchmarks",
    "benchmark",
    "examples",
    "example",
    "review",
    "data",
    "build",
    "dist",
})


@dataclass
class LinkRecord:
    id: str
    repo: str
    source_id: str
    source_type: str
    rel_type: str
    target_id: str
    target_type: str
    is_direct: bool = True
    derivation_method: str = "direct"
    confidence: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def as_row(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "repo": self.repo,
            "source_id": self.source_id,
            "source_type": self.source_type,
            "rel_type": self.rel_type,
            "target_id": self.target_id,
            "target_type": self.target_type,
            "is_direct": 1 if self.is_direct else 0,
            "derivation_method": self.derivation_method,
            "confidence": self.confidence,
            "metadata_json": self.metadata,
            "created_at": self.created_at,
        }


def make_link_id(source_id: str, rel_type: str, target_id: str) -> str:
    """Stable identifier for a directed relationship between two entities."""
    return f"link:{source_id}:{rel_type}:{target_id}"


def extract_revert_links(
    commit_sha: str,
    message: str,
    repo: str,
) -> list[LinkRecord]:
    """Parse 'This reverts commit <sha>' and Reverts: trailers from commit messages.

    This represents the strongest deterministic supersession signal in git history (Rule 1).
    Direction: Reverting Commit -> Reverted Commit.
    """
    links: list[LinkRecord] = []
    seen_shas: set[str] = set()

    clean_message = message or ""
    for match in REVERT_COMMIT_PATTERN.finditer(clean_message):
        target_sha = match.group(1).lower()
        if target_sha != commit_sha.lower() and target_sha not in seen_shas:
            seen_shas.add(target_sha)
            source_id = stable_id("commit", repo, commit_sha)
            target_id = stable_id("commit", repo, target_sha)
            links.append(
                LinkRecord(
                    id=make_link_id(source_id, "REVERTS", target_id),
                    repo=repo,
                    source_id=source_id,
                    source_type=SourceType.COMMIT.value,
                    rel_type="REVERTS",
                    target_id=target_id,
                    target_type=SourceType.COMMIT.value,
                    is_direct=True,
                    derivation_method="revert_message",
                    confidence=1.0,
                    metadata={"target_sha": target_sha, "matched_text": match.group(0)},
                )
            )

    for match in REVERT_TRAILER_PATTERN.finditer(clean_message):
        target_sha = match.group(1).lower()
        if target_sha != commit_sha.lower() and target_sha not in seen_shas:
            seen_shas.add(target_sha)
            source_id = stable_id("commit", repo, commit_sha)
            target_id = stable_id("commit", repo, target_sha)
            links.append(
                LinkRecord(
                    id=make_link_id(source_id, "REVERTS", target_id),
                    repo=repo,
                    source_id=source_id,
                    source_type=SourceType.COMMIT.value,
                    rel_type="REVERTS",
                    target_id=target_id,
                    target_type=SourceType.COMMIT.value,
                    is_direct=True,
                    derivation_method="revert_trailer",
                    confidence=1.0,
                    metadata={"target_sha": target_sha, "matched_text": match.group(0)},
                )
            )

    return links


def extract_commit_pr_links(
    commit_sha: str,
    subject: str,
    message: str,
    repo: str,
    explicit_prs: Optional[Sequence[int]] = None,
) -> list[LinkRecord]:
    """Link a commit to the pull request it belongs to (Commit -[PART_OF]-> PullRequest).

    Detects PR numbers from squash titles (#123), merge subjects, and explicit PR lists.
    """
    links: list[LinkRecord] = []
    pr_numbers: set[int] = set()

    if explicit_prs:
        pr_numbers.update(explicit_prs)

    for pr_num in extract_pull_request_numbers(subject or ""):
        pr_numbers.add(pr_num)

    source_id = stable_id("commit", repo, commit_sha)
    for pr_num in sorted(pr_numbers):
        target_id = stable_id("pr", repo, str(pr_num))
        links.append(
            LinkRecord(
                id=make_link_id(source_id, "PART_OF", target_id),
                repo=repo,
                source_id=source_id,
                source_type=SourceType.COMMIT.value,
                rel_type="PART_OF",
                target_id=target_id,
                target_type=SourceType.PULL_REQUEST.value,
                is_direct=True,
                derivation_method="pr_reference",
                confidence=1.0,
                metadata={"pr_number": pr_num},
            )
        )

    return links


def extract_issue_links(
    source_id: str,
    source_type: str,
    text: str,
    repo: str,
) -> list[LinkRecord]:
    """Extract REFERENCES links between a PR/Commit and related Issues or PRs.

    Distinguishes closing keywords ('Fixes #123', 'Closes #456') as direct references (1.0),
    from plain mentions ('#123') as inferred references (0.7).
    Code blocks and inline code are stripped first to avoid false positives.
    """
    links: list[LinkRecord] = []
    clean_text = strip_code(text or "")
    closing_numbers: set[int] = set()
    mention_numbers: set[int] = set()

    for match in CLOSING_KEYWORDS.finditer(clean_text):
        num_str = match.group("num") or match.group("url_num")
        if num_str:
            closing_numbers.add(int(num_str))

    for found in ISSUE_REFERENCE.findall(clean_text):
        num = int(found)
        if num not in closing_numbers:
            mention_numbers.add(num)

    for match in GITHUB_ISSUE_URL.finditer(clean_text):
        matched_repo = f"{match.group('owner')}/{match.group('repo')}"
        if matched_repo.lower() == repo.lower():
            num = int(match.group("number"))
            if num not in closing_numbers:
                mention_numbers.add(num)

    for num in sorted(closing_numbers):
        target_id = stable_id("issue", repo, str(num))
        links.append(
            LinkRecord(
                id=make_link_id(source_id, "REFERENCES", target_id),
                repo=repo,
                source_id=source_id,
                source_type=source_type,
                rel_type="REFERENCES",
                target_id=target_id,
                target_type=SourceType.ISSUE.value,
                is_direct=True,
                derivation_method="closing_keyword",
                confidence=1.0,
                metadata={"issue_number": num, "closing": True},
            )
        )

    for num in sorted(mention_numbers):
        target_id = stable_id("issue", repo, str(num))
        links.append(
            LinkRecord(
                id=make_link_id(source_id, "REFERENCES", target_id),
                repo=repo,
                source_id=source_id,
                source_type=source_type,
                rel_type="REFERENCES",
                target_id=target_id,
                target_type=SourceType.ISSUE.value,
                is_direct=False,
                derivation_method="mention",
                confidence=0.7,
                metadata={"issue_number": num, "closing": False},
            )
        )

    return links


def normalise_document_reference(reference: str) -> str:
    """Turn a status-line reference into the path a document is stored under.

    Stripping every non-word character destroyed the directory separators, so
    'docs/adr/0003.md' became 'docsadr0003.md' and the edge pointed at a document
    that could never exist. Bare references such as 'ADR-7' are left as written,
    because those name a document that is matched elsewhere rather than by path.
    """
    text = (reference or "").strip().strip("`").strip()
    if "/" in text or text.endswith((".md", ".rst", ".txt")):
        return text.lstrip("./")
    return text


def extract_document_supersession(
    doc_path: str,
    content: str,
    repo: str,
) -> list[LinkRecord]:
    """Parse design doc / ADR status lines such as 'Status: Superseded by ADR-7'.

    Per Spec v2 Rule 3b: A design-doc status line is a confirmed supersession signal.
    Relationship direction (Spec v2 Page 16):
      SUPERSEDES: Newer replaces older (NewerDoc -[SUPERSEDES]-> OlderDoc).
    """
    links: list[LinkRecord] = []
    clean_content = content or ""
    match = ADR_SUPERSEDED_PATTERN.search(clean_content)
    if not match:
        return links

    target_ref = match.group("target").strip()
    target_path = normalise_document_reference(target_ref)
    older_doc_id = stable_id("doc", repo, doc_path)
    newer_doc_id = stable_id("doc", repo, target_path)

    links.append(
        LinkRecord(
            id=make_link_id(newer_doc_id, "SUPERSEDES", older_doc_id),
            repo=repo,
            source_id=newer_doc_id,
            source_type=SourceType.DOCUMENT.value,
            rel_type="SUPERSEDES",
            target_id=older_doc_id,
            target_type=SourceType.DOCUMENT.value,
            is_direct=True,
            derivation_method="adr_status",
            confidence=1.0,
            metadata={"superseded_doc": doc_path, "target_ref": target_ref},
        )
    )
    return links


class FileHistoryTracker:
    """Maintains file identity across Git renames (git log --follow).

    Enables historical commits to link to the canonical/latest file entity,
    while preserving every path a file ever had.
    """

    def __init__(self) -> None:
        self._forward_renames: dict[str, str] = {}
        self._reverse_renames: dict[str, set[str]] = {}

    def record_rename(self, old_path: str, new_path: str) -> None:
        if not old_path or not new_path or old_path == new_path:
            return
        self._forward_renames[old_path] = new_path
        self._reverse_renames.setdefault(new_path, set()).add(old_path)
        if old_path in self._reverse_renames:
            for ancestor in self._reverse_renames[old_path]:
                self._reverse_renames[new_path].add(ancestor)

    def canonical_path(self, path: str) -> str:
        """Resolve a historical file path forward to its latest known path."""
        current = path
        visited = {current}
        while current in self._forward_renames:
            next_path = self._forward_renames[current]
            if next_path in visited:
                break
            visited.add(next_path)
            current = next_path
        return current

    def all_historical_paths(self, canonical_path: str) -> set[str]:
        """All past and present paths that correspond to the given canonical file."""
        result = {canonical_path}
        stack = [canonical_path]
        while stack:
            curr = stack.pop()
            for prev in self._reverse_renames.get(curr, set()):
                if prev not in result:
                    result.add(prev)
                    stack.append(prev)
        return result

    def build_commit_file_links(
        self,
        repo: str,
        commit_files: Sequence[dict[str, Any]],
    ) -> list[LinkRecord]:
        """Build CodeEntity(File) -[MODIFIED_IN]-> Commit links following renames."""
        for cf in commit_files:
            old_p = cf.get("old_path")
            new_p = cf.get("path")
            if old_p and new_p and old_p != new_p:
                self.record_rename(old_p, new_p)

        links: list[LinkRecord] = []
        for cf in commit_files:
            sha = cf["sha"]
            raw_path = cf["path"]
            canonical = self.canonical_path(raw_path)
            was_renamed = raw_path != canonical

            source_id = f"file:{repo}:{canonical}"
            target_id = stable_id("commit", repo, sha)

            links.append(
                LinkRecord(
                    id=make_link_id(source_id, "MODIFIED_IN", target_id),
                    repo=repo,
                    source_id=source_id,
                    source_type=EntityType.FILE.value,
                    rel_type="MODIFIED_IN",
                    target_id=target_id,
                    target_type=SourceType.COMMIT.value,
                    is_direct=not was_renamed,
                    derivation_method="rename_follow" if was_renamed else "commit_file",
                    confidence=1.0,
                    metadata={
                        "path_in_commit": raw_path,
                        "canonical_path": canonical,
                        "status": cf.get("status"),
                    },
                )
            )

        return links


def get_module_for_path(path: str) -> Optional[str]:
    """Identify the top-level module folder for a file path.

    Spec v2 Layer 2 (Page 14): 'A module is a top-level folder.'
    Standard Python layouts like src/<pkg>/... map to src/<pkg>.
    Files in repository root or in non-module directories have no module entity.
    """
    parts = Path(path).as_posix().split("/")
    if len(parts) <= 1:
        return None

    top = parts[0]
    if top in NON_MODULE_DIRS:
        return None

    if top == "src" and len(parts) > 2:
        return f"src/{parts[1]}"

    return top


def extract_containment_links(
    repo: str,
    file_paths: Sequence[str],
) -> list[LinkRecord]:
    """Build CONTAINS hierarchy:
    Repository -[CONTAINS]-> Module (or root File)
    Module -[CONTAINS]-> File
    """
    links: list[LinkRecord] = []
    repo_node_id = f"repo:{repo}"
    seen_modules: set[str] = set()

    for file_path in sorted(set(file_paths)):
        file_id = f"file:{repo}:{file_path}"
        module_name = get_module_for_path(file_path)

        if module_name:
            module_id = f"module:{repo}:{module_name}"
            if module_name not in seen_modules:
                seen_modules.add(module_name)
                links.append(
                    LinkRecord(
                        id=make_link_id(repo_node_id, "CONTAINS", module_id),
                        repo=repo,
                        source_id=repo_node_id,
                        source_type="Repository",
                        rel_type="CONTAINS",
                        target_id=module_id,
                        target_type=EntityType.MODULE.value,
                        is_direct=True,
                        derivation_method="repository_structure",
                        confidence=1.0,
                        metadata={"module_name": module_name},
                    )
                )

            links.append(
                LinkRecord(
                    id=make_link_id(module_id, "CONTAINS", file_id),
                    repo=repo,
                    source_id=module_id,
                    source_type=EntityType.MODULE.value,
                    rel_type="CONTAINS",
                    target_id=file_id,
                    target_type=EntityType.FILE.value,
                    is_direct=True,
                    derivation_method="module_containment",
                    confidence=1.0,
                    metadata={"path": file_path},
                )
            )
        else:
            links.append(
                LinkRecord(
                    id=make_link_id(repo_node_id, "CONTAINS", file_id),
                    repo=repo,
                    source_id=repo_node_id,
                    source_type="Repository",
                    rel_type="CONTAINS",
                    target_id=file_id,
                    target_type=EntityType.FILE.value,
                    is_direct=True,
                    derivation_method="repository_containment",
                    confidence=1.0,
                    metadata={"path": file_path},
                )
            )

    return links
