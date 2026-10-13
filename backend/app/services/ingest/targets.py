from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.services.ingest.git_probe import parse_slug


class TargetConfigKey(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file: str
    name: str


class IngestTargets(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repo: str
    files: list[str] = Field(default_factory=list)
    dirs: list[str] = Field(default_factory=list)
    config_keys: list[TargetConfigKey] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_at_least_one_target(self) -> "IngestTargets":
        if not self.files and not self.config_keys:
            raise ValueError("targets must name at least one file or one config key")
        for key in self.config_keys:
            if key.file not in self.files:
                raise ValueError(
                    f"config key {key.name!r} points at {key.file!r}, which is not listed in files"
                )
        return self

    def all_files(self) -> list[str]:
        seen: list[str] = []
        for name in list(self.files) + [key.file for key in self.config_keys]:
            if name not in seen:
                seen.append(name)
        return seen

    def config_key_names(self) -> list[str]:
        return [key.name for key in self.config_keys]

    def target_files_in_clone(self) -> list[str]:
        return list(self.files)


def load_targets(path: Path) -> IngestTargets:
    import json

    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"targets file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"targets file is not valid JSON: {path}: {exc}") from exc
    return IngestTargets(**payload)


def require_matching_repo(targets: IngestTargets, repo: str) -> None:
    if targets.repo != repo:
        raise ValueError(
            f"targets file declares repo {targets.repo!r} but --repo is {repo!r}; "
            "the two must agree or the wrong repository would be ingested"
        )
    parse_slug(repo)