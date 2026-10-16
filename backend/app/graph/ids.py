from __future__ import annotations

import re
from typing import Any, Optional

#: Source-id prefixes and the graph label each one maps to. Kept in one place so the
#: build and the API agree on what a source id means.
SOURCE_LABELS: dict[str, str] = {
    "pr": "PullRequest",
    "issue": "Issue",
    "doc": "Document",
    "commit": "Commit",
}

#: The enum spelling stored on the node, matching schemas.common.SourceType values.
SOURCE_TYPE_NAMES: dict[str, str] = {
    "pr": "PullRequest",
    "issue": "Issue",
    "doc": "Document",
    "commit": "Commit",
}

_NUMBERED = re.compile(r"^(?P<kind>pr|issue):[^#]*#(?P<number>\d+)$")


def to_api_id(repo: str) -> str:
    """`owner/name` -> `owner-name`, the single path segment the API route carries.

    A repository id with a slash cannot appear in `/repositories/{repository_id}`, so
    the graph is addressed by this slug while the raw `owner/name` is kept on the
    node as `full_name`.
    """
    cleaned = (repo or "").strip().strip("/")
    return cleaned.replace("/", "-")


def graph_id(identifier: str, repo: str) -> str:
    """Map a cache identifier onto the id its node carries in the graph.

    Only the Repository node is addressed by slug: every other node keeps the id the
    cache and the links table already use, so a link endpoint resolves to the node it
    names. The one exception is `repo:<owner/name>`, which the linkage layer emits but
    whose node is the slug-addressed Repository.
    """
    if identifier == f"repo:{repo}":
        return to_api_id(repo)
    return identifier


def source_kind(source_id: Any) -> str:
    """The prefix before the first colon: `pr`, `issue`, `doc` or `commit`."""
    text = str(source_id or "")
    return text.split(":", 1)[0] if ":" in text else ""


def source_label_for(source_id: Any) -> Optional[str]:
    """The graph label a source id belongs to, or None when it is not a source."""
    return SOURCE_LABELS.get(source_kind(source_id))


def source_type_name(source_id: Any) -> str:
    """The `SourceType` value for a source id; empty when it is not a known source."""
    return SOURCE_TYPE_NAMES.get(source_kind(source_id), "")


def source_number(source_id: Any) -> Optional[int]:
    """The pull/issue number carried by a source id, or None."""
    match = _NUMBERED.match(str(source_id or ""))
    return int(match.group("number")) if match else None


def source_url(source_id: Any, repo: str) -> str:
    """The canonical web address of a source, derived from its id.

    A citation that pointed at the repository homepage instead of the pull request
    would not be checkable, so the address is always derived rather than guessed.
    """
    text = str(source_id or "")
    kind = source_kind(text)
    if kind == "pr":
        number = source_number(text)
        if number is not None:
            return f"https://github.com/{repo}/pull/{number}"
    if kind == "issue":
        number = source_number(text)
        if number is not None:
            return f"https://github.com/{repo}/issues/{number}"
    if kind == "commit":
        sha = text.split(":", 1)[1] if ":" in text else ""
        if sha:
            return f"https://github.com/{repo}/commit/{sha}"
    if kind == "doc":
        path = text.split(":", 2)[2] if text.count(":") >= 2 else ""
        if path:
            return f"https://github.com/{repo}/blob/main/{path}"
    return f"https://github.com/{repo}"


def source_text_from_payload(payload: dict[str, Any]) -> str:
    """The text a quote is checked against: title, body and the comment bodies.

    Mirrors the corpus extraction verifies against, so a quote that verified while the
    record was made can be re-verified at answer time from the node alone.
    """
    parts: list[str] = [str(payload.get("title") or ""), str(payload.get("body") or "")]
    comments = payload.get("comments")
    if isinstance(comments, list):
        for comment in comments:
            if isinstance(comment, dict) and comment.get("body"):
                parts.append(str(comment["body"]))
    return "\n".join(parts)


def entity_id_for(name: str, repo: str) -> str:
    """The node id an affected entity is stored under.

    A path is a file the containment links also name; anything else is a configuration
    key. The two use the same prefixes as the linkage layer so one artefact is one node.
    """
    if "/" in name or name.endswith((".py", ".pyi", ".rst", ".md", ".txt")):
        return f"file:{repo}:{name}"
    return f"entity:{repo}:{name}"
