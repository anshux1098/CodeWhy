from __future__ import annotations

import ast
import json
import re
import tomllib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Sequence

import yaml

from app.schemas.common import EntityType
from app.services.linking import LinkRecord, make_link_id

ENV_LINE_PATTERN = re.compile(
    r"^[ \t]*(?:export[ \t]+)?(?P<name>[A-Za-z_][A-Za-z0-9_]*)[ \t]*=[ \t]*(?P<value>.*)$"
)


@dataclass
class ConfigKeyEntity:
    id: str
    repo: str
    file_path: str
    name: str
    current_value: str
    file_type: str
    line_number: Optional[int] = None
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "repo": self.repo,
            "file_path": self.file_path,
            "name": self.name,
            "current_value": self.current_value,
            "file_type": self.file_type,
            "line_number": self.line_number,
            "created_at": self.created_at,
        }


@dataclass
class ConfigValueChange:
    id: str
    config_id: str
    repo: str
    file_path: str
    name: str
    commit_sha: str
    old_value: Optional[str]
    new_value: str
    authored_at: Optional[str] = None
    author_name: Optional[str] = None
    diff_snippet: Optional[str] = None
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "config_id": self.config_id,
            "repo": self.repo,
            "file_path": self.file_path,
            "name": self.name,
            "commit_sha": self.commit_sha,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "authored_at": self.authored_at,
            "author_name": self.author_name,
            "diff_snippet": self.diff_snippet,
            "created_at": self.created_at,
        }


def make_config_id(repo: str, file_path: str, name: str) -> str:
    """Stable entity identifier for a configuration key or constant."""
    clean_path = Path(file_path).as_posix()
    return f"config:{repo}:{clean_path}#{name}"


def is_upper_constant(name: str) -> bool:
    """Checks if a name follows UPPER_CASE constant naming.

    Leading-underscore names (e.g. _PRIVATE, __DUNDER__) are treated as private
    and excluded — they carry no public API meaning.
    """
    return (
        not name.startswith("_")
        and name.isupper()
        and name.strip("_") != ""
    )


def _eval_ast_value(node: Optional[ast.expr]) -> str:
    """Safely format an AST expression value as string."""
    if node is None:
        return ""
    try:
        val = ast.literal_eval(node)
        return repr(val)
    except (ValueError, SyntaxError, TypeError, MemoryError, RecursionError):
        pass
    try:
        return ast.unparse(node)
    except Exception:
        return "<complex expression>"


def extract_python_constants(
    source: str,
    file_path: str,
    repo: str,
) -> list[ConfigKeyEntity]:
    """Parse Python source using the built-in ast module to find UPPER_CASE constants.

    Per Spec v2 Layer 2 (Page 14): Uses ast module. Functions/classes are out of scope,
    but module-level and class-level UPPER_CASE constants are extracted.
    """
    clean_path = Path(file_path).as_posix()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    results: list[ConfigKeyEntity] = []

    def check_stmt(stmt: ast.stmt, prefix: str = "") -> None:
        if isinstance(stmt, ast.Assign):
            val_str = _eval_ast_value(stmt.value)
            for target in stmt.targets:
                if isinstance(target, ast.Name) and is_upper_constant(target.id):
                    name = f"{prefix}{target.id}" if prefix else target.id
                    results.append(
                        ConfigKeyEntity(
                            id=make_config_id(repo, clean_path, name),
                            repo=repo,
                            file_path=clean_path,
                            name=name,
                            current_value=val_str,
                            file_type="python",
                            line_number=stmt.lineno,
                        )
                    )
        elif isinstance(stmt, ast.AnnAssign):
            if isinstance(stmt.target, ast.Name) and is_upper_constant(stmt.target.id):
                val_str = _eval_ast_value(stmt.value)
                name = f"{prefix}{stmt.target.id}" if prefix else stmt.target.id
                results.append(
                    ConfigKeyEntity(
                        id=make_config_id(repo, clean_path, name),
                        repo=repo,
                        file_path=clean_path,
                        name=name,
                        current_value=val_str,
                        file_type="python",
                        line_number=stmt.lineno,
                    )
                )
        elif isinstance(stmt, ast.ClassDef):
            # Inspect class attributes for constants
            for item in stmt.body:
                check_stmt(item, prefix=f"{stmt.name}.")

    for node in tree.body:
        check_stmt(node)

    return results


def _flatten_dict(data: Any, prefix: str = "") -> list[tuple[str, str]]:
    """Flatten nested dicts into dotted key-value string pairs."""
    items: list[tuple[str, str]] = []
    if isinstance(data, dict):
        for key, val in data.items():
            key_str = str(key)
            full_key = f"{prefix}.{key_str}" if prefix else key_str
            if isinstance(val, dict):
                items.extend(_flatten_dict(val, full_key))
            else:
                items.append((full_key, repr(val) if val is not None else "null"))
    return items


def extract_json_keys(
    source: str,
    file_path: str,
    repo: str,
) -> list[ConfigKeyEntity]:
    """Parse JSON configuration files into dotted configuration keys."""
    clean_path = Path(file_path).as_posix()
    try:
        data = json.loads(source)
    except (json.JSONDecodeError, ValueError):
        return []

    results: list[ConfigKeyEntity] = []
    for key, val in _flatten_dict(data):
        results.append(
            ConfigKeyEntity(
                id=make_config_id(repo, clean_path, key),
                repo=repo,
                file_path=clean_path,
                name=key,
                current_value=val,
                file_type="json",
            )
        )
    return results


def extract_yaml_keys(
    source: str,
    file_path: str,
    repo: str,
) -> list[ConfigKeyEntity]:
    """Parse YAML configuration files into dotted configuration keys."""
    clean_path = Path(file_path).as_posix()
    try:
        data = yaml.safe_load(source)
    except Exception:
        return []

    results: list[ConfigKeyEntity] = []
    for key, val in _flatten_dict(data):
        results.append(
            ConfigKeyEntity(
                id=make_config_id(repo, clean_path, key),
                repo=repo,
                file_path=clean_path,
                name=key,
                current_value=val,
                file_type="yaml",
            )
        )
    return results


def extract_toml_keys(
    source: str,
    file_path: str,
    repo: str,
) -> list[ConfigKeyEntity]:
    """Parse TOML configuration files using Python's built-in tomllib."""
    clean_path = Path(file_path).as_posix()
    try:
        data = tomllib.loads(source)
    except Exception:
        return []

    results: list[ConfigKeyEntity] = []
    for key, val in _flatten_dict(data):
        results.append(
            ConfigKeyEntity(
                id=make_config_id(repo, clean_path, key),
                repo=repo,
                file_path=clean_path,
                name=key,
                current_value=val,
                file_type="toml",
            )
        )
    return results


def extract_env_keys(
    source: str,
    file_path: str,
    repo: str,
) -> list[ConfigKeyEntity]:
    """Parse .env environment variable files line-by-line."""
    clean_path = Path(file_path).as_posix()
    results: list[ConfigKeyEntity] = []

    for line_num, line in enumerate(source.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = ENV_LINE_PATTERN.match(line)
        if not match:
            continue
        name = match.group("name")
        raw_val = match.group("value").strip()
        if (raw_val.startswith('"') and raw_val.endswith('"')) or (
            raw_val.startswith("'") and raw_val.endswith("'")
        ):
            raw_val = raw_val[1:-1]
        results.append(
            ConfigKeyEntity(
                id=make_config_id(repo, clean_path, name),
                repo=repo,
                file_path=clean_path,
                name=name,
                current_value=raw_val,
                file_type="env",
                line_number=line_num,
            )
        )

    return results


def extract_config_keys_from_source(
    source: str,
    file_path: str,
    repo: str,
) -> list[ConfigKeyEntity]:
    """Dispatch extraction based on file extension and naming conventions."""
    path_obj = Path(file_path)
    suffix = path_obj.suffix.lower()
    name = path_obj.name.lower()

    if suffix == ".py":
        return extract_python_constants(source, file_path, repo)
    if suffix == ".json":
        return extract_json_keys(source, file_path, repo)
    if suffix in (".yaml", ".yml"):
        return extract_yaml_keys(source, file_path, repo)
    if suffix == ".toml":
        return extract_toml_keys(source, file_path, repo)
    if name == ".env" or name.startswith(".env.") or suffix == ".env":
        return extract_env_keys(source, file_path, repo)

    return []


def make_config_containment_link(
    repo: str,
    config: ConfigKeyEntity,
) -> LinkRecord:
    """Build File -[CONTAINS]-> ConfigKey link (Spec v2 Page 16 Table)."""
    file_id = f"file:{repo}:{config.file_path}"
    return LinkRecord(
        id=make_link_id(file_id, "CONTAINS", config.id),
        repo=repo,
        source_id=file_id,
        source_type=EntityType.FILE.value,
        rel_type="CONTAINS",
        target_id=config.id,
        target_type=EntityType.CONFIG_KEY.value,
        is_direct=True,
        derivation_method="file_definition",
        confidence=1.0,
        metadata={"config_name": config.name, "line_number": config.line_number},
    )


# Regex patterns to parse assignments from diff hunks
_PY_ASSIGN_LINE = re.compile(
    r"^(?P<prefix>[-+])\s*(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*(?::[^=]+)?=\s*(?P<val>.+)$"
)
_CONFIG_ASSIGN_LINE = re.compile(
    r"^(?P<prefix>[-+])\s*(?P<name>[A-Za-z0-9_.-]+)\s*[:=]\s*(?P<val>.+)$"
)


def extract_value_changes_from_diff(
    diff: str,
    key_name: str,
    file_path: str,
    repo: str,
    commit_sha: str,
    authored_at: Optional[str] = None,
    author_name: Optional[str] = None,
) -> Optional[ConfigValueChange]:
    """Detect when a diff changes the assigned value of key_name.

    Under Supersession Rule 2 (Spec v2 Page 18):
    'The same config key changed to a different value in a later merged change
     -> Confirmed for the value. The new decision may have rationale unknown.'
    """
    if not diff:
        return None

    target_name = key_name.split(".")[-1]
    removed_values: list[str] = []
    added_values: list[str] = []
    relevant_lines: list[str] = []

    for line in diff.splitlines():
        if line.startswith("---") or line.startswith("+++"):
            continue
        if line.startswith("-") or line.startswith("+"):
            m = _PY_ASSIGN_LINE.match(line) or _CONFIG_ASSIGN_LINE.match(line)
            if m and m.group("name") == target_name:
                relevant_lines.append(line)
                prefix = m.group("prefix")
                val = m.group("val").strip()
                if prefix == "-":
                    removed_values.append(val)
                elif prefix == "+":
                    added_values.append(val)

    if added_values:
        old_val = removed_values[-1] if removed_values else None
        new_val = added_values[-1]
        if old_val != new_val:
            config_id = make_config_id(repo, file_path, key_name)
            change_id = f"valchange:{config_id}:{commit_sha}"
            return ConfigValueChange(
                id=change_id,
                config_id=config_id,
                repo=repo,
                file_path=file_path,
                name=key_name,
                commit_sha=commit_sha,
                old_value=old_val,
                new_value=new_val,
                authored_at=authored_at,
                author_name=author_name,
                diff_snippet="\n".join(relevant_lines),
            )

    return None


def build_config_value_history(
    repo: str,
    key_name: str,
    file_path: str,
    commit_files: Sequence[dict[str, Any]],
) -> list[ConfigValueChange]:
    """Scan commit diffs for a file to reconstruct the chronological value history."""
    changes: list[ConfigValueChange] = []
    for cf in commit_files:
        diff = cf.get("diff") or ""
        sha = cf.get("sha") or ""
        authored_at = cf.get("authored_at")
        author_name = cf.get("author_name")
        change = extract_value_changes_from_diff(
            diff=diff,
            key_name=key_name,
            file_path=file_path,
            repo=repo,
            commit_sha=sha,
            authored_at=authored_at,
            author_name=author_name,
        )
        if change:
            changes.append(change)

    return changes
