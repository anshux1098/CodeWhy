"""Entity resolution: an explicit reference wins, and ambiguity means a real tie.

The resolver used to score any token that appeared anywhere in an entity's path, so
the repository name (`urllib3` sits inside every path) made every entity tie and
returned `ambiguous_entity` for questions that named no entity at all. It also let a
`.pyi` stub sit beside its `.py` file and split a basename match into a false tie.
These pin the rules the live answer path depends on.
"""

from __future__ import annotations

from app.services.entity_resolution import ResolutionOutcome, resolve_entity


def _entity(path: str, entity_type: str = "File") -> dict:
    return {"id": f"file:urllib3/urllib3:{path}", "name": path, "path": path, "entity_type": entity_type}


def test_an_exact_full_path_beats_a_basename_match() -> None:
    entities = [
        _entity("src/urllib3/util/url.py"),
        _entity("docs/url.py"),
    ]
    result = resolve_entity("Why was src/urllib3/util/url.py changed?", entities)
    assert result.outcome is ResolutionOutcome.SUCCESS
    assert result.entity is not None
    assert result.entity.path == "src/urllib3/util/url.py"


def test_a_basename_beats_a_partial_token_match() -> None:
    entities = [
        _entity("src/urllib3/util/url.py"),
        _entity("src/urllib3/other.py"),
    ]
    result = resolve_entity("Why was url.py changed?", entities)
    assert result.outcome is ResolutionOutcome.SUCCESS
    assert result.entity is not None
    assert result.entity.path == "src/urllib3/util/url.py"


def test_a_pyi_stub_does_not_split_its_py_file_into_a_tie() -> None:
    entities = [
        _entity("src/urllib3/util/url.py"),
        _entity("src/urllib3/util/url.pyi"),
    ]
    result = resolve_entity("Why was url.py changed?", entities)
    assert result.outcome is ResolutionOutcome.SUCCESS
    assert result.entity is not None
    assert result.entity.path == "src/urllib3/util/url.py"


def test_two_genuinely_different_files_with_the_same_basename_stay_ambiguous() -> None:
    entities = [
        _entity("a/retry.py"),
        _entity("b/retry.py"),
    ]
    result = resolve_entity("Why is retry.py like this?", entities)
    assert result.outcome is ResolutionOutcome.AMBIGUOUS
    assert {c.path for c in result.candidates} == {"a/retry.py", "b/retry.py"}


def test_a_repository_name_in_every_path_is_not_an_entity_reference() -> None:
    entities = [
        _entity("src/urllib3/util/ssl_.py"),
        _entity("src/urllib3/connection.py"),
        _entity("src/urllib3/connectionpool.py"),
    ]
    result = resolve_entity(
        "Why does urllib3 use Kubernetes for orchestration?",
        entities,
        repository="urllib3/urllib3",
    )
    assert result.outcome is ResolutionOutcome.REFUSAL
    assert result.reason_code == "entity_not_found"
