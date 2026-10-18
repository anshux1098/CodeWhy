"""The published contract may only grow.

`contract/openapi.v1.json` is a frozen copy of the contract as it stood before the
API-gap work. This test walks it against the current `contract/openapi.json` and
fails if any path, method, parameter, response, schema, property, required field,
enum value or type from the frozen copy was removed, renamed or narrowed. New
paths, new (optional) properties and new enum values are additions, and are allowed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.main import create_app

CONTRACT_DIR = Path(__file__).resolve().parents[3] / "contract"
FROZEN = CONTRACT_DIR / "openapi.v1.json"

# Documentation and presentation keys carry no compatibility promise, so additions
# or edits to them are not contract changes.
IGNORED_KEYS = {
    "title",
    "description",
    "summary",
    "example",
    "examples",
    "default",
    "operationId",
    "tags",
    "version",
}

# Path items are keyed by URL; methods are lower-case HTTP verbs. Keeping them in
# one set makes "the frozen copy has this operation" a single membership check.
HTTP_METHODS = {"get", "put", "post", "delete", "options", "head", "patch", "trace"}


def _compatible(old: Any, new: Any, where: str) -> None:
    """Assert every part of `old` still appears in `new` with the same shape."""
    if isinstance(old, dict):
        assert isinstance(new, dict), f"{where}: was an object, now {type(new).__name__}"
        for key, value in old.items():
            if key in IGNORED_KEYS:
                continue
            assert key in new, f"{where}.{key} was removed"
            _compatible(value, new[key], f"{where}.{key}")
    elif isinstance(old, list):
        assert isinstance(new, list), f"{where}: was a list, now {type(new).__name__}"
        for item in old:
            if not any(_ok(item, candidate) for candidate in new):
                raise AssertionError(f"{where}: entry {item!r} was removed")
    else:
        assert old == new, f"{where}: {old!r} changed to {new!r}"


def _ok(old: Any, new: Any) -> bool:
    try:
        _compatible(old, new, "")
    except AssertionError:
        return False
    return True


def _frozen() -> dict:
    return json.loads(FROZEN.read_text(encoding="utf-8"))


def _current() -> dict:
    return json.loads((CONTRACT_DIR / "openapi.json").read_text(encoding="utf-8"))


def test_the_frozen_contract_is_a_valid_document() -> None:
    document = _frozen()
    assert document["openapi"].startswith("3.")
    assert document["paths"], "the frozen copy has no paths"


def test_every_frozen_path_and_method_survives() -> None:
    old, new = _frozen(), _current()
    for path, operations in old["paths"].items():
        assert path in new["paths"], f"path {path} was removed"
        for method in operations:
            if method.lower() in HTTP_METHODS:
                assert method in new["paths"][path], f"{method.upper()} {path} was removed"


def test_every_frozen_schema_and_property_survives() -> None:
    old, new = _frozen(), _current()
    old_schemas = old["components"]["schemas"]
    new_schemas = new["components"]["schemas"]
    for name, schema in old_schemas.items():
        assert name in new_schemas, f"schema {name} was removed"
        for prop, spec in schema.get("properties", {}).items():
            assert prop in new_schemas[name].get("properties", {}), (
                f"schema {name} lost property {prop}"
            )
            _compatible(spec, new_schemas[name]["properties"][prop], f"{name}.{prop}")
        for field in schema.get("required", []):
            assert field in new_schemas[name].get("required", []), (
                f"schema {name} lost required field {field}"
            )


def test_the_frozen_contract_is_otherwise_a_subset_of_the_current_one() -> None:
    """A belt-and-braces full walk: nothing anywhere in the old document vanished."""
    _compatible(_frozen(), _current(), "openapi")


def test_the_frozen_contract_matches_what_the_app_publishes_today() -> None:
    """A drift guard: regenerating must reproduce the frozen copy's shape, not change it."""
    generated = json.loads(json.dumps(create_app().openapi(), sort_keys=True))
    _compatible(_frozen(), generated, "openapi")
