"""The seven live answer scenarios, pinned as a regression test.

`scripts/check_live_answers.py` asks these questions and prints the answers for a
human to read. This turns the same seven scenarios into assertions, so a change
that quietly turns a real answer into a refusal (or leaks the system prompt) fails
a test instead of only being noticed on the next manual run.

Set RUN_LIVE=1 to run it against the live graph and the real model. It is skipped
by default because it needs Neo4j and an LLM, and it spends real tokens. The test
reads `.env` itself and forces `offline=False`, so RUN_LIVE=1 alone uses the real
embedder; if that embedder is unavailable the test fails instead of skipping.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
CHECK_SCRIPT = REPO_ROOT / "scripts" / "check_live_answers.py"
REPO = "urllib3-urllib3"

#: Outcome and reason code each scenario must produce. Only those two fields are
#: asserted: the wording comes from the model and is expected to vary.
EXPECTED: dict[str, tuple[str, str | None]] = {
    "path-named": ("full", None),
    "http2-revert": ("full", None),
    "thin-file": ("full", None),
    "kubernetes": ("refusal", "entity_not_found"),
    "unknown-entity": ("refusal", "entity_not_found"),
    "injection": ("refusal", "low_score"),
}

#: The two pull requests the HTTP/2 story must cite: the addition and the revert.
HTTP2_CITATIONS = {"3456", "3466"}


def _check_script():
    """Load the live check script so its scenarios and helpers are shared."""
    spec = importlib.util.spec_from_file_location("check_live_answers", CHECK_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.live
def test_live_answer_scenarios() -> None:
    if os.environ.get("RUN_LIVE") != "1":
        pytest.skip("set RUN_LIVE=1 to ask the live graph with the real model")

    from app.config import Settings
    from app.providers.embeddings import (
        SentenceTransformersProvider,
        get_embedding_provider,
    )
    from app.schemas.ask import AskRequest
    from app.services.answer import get_answer_system_prompt
    from app.services.data_source import GraphDataSource

    live_settings = Settings(_env_file=REPO_ROOT / ".env", offline=False)
    live_settings.require_neo4j()
    live_settings.require_llm()

    embedder = get_embedding_provider(cfg=live_settings)
    assert isinstance(embedder, SentenceTransformersProvider), (
        "live test needs the real embedder: install the embeddings extra and set OFFLINE=0"
    )

    script = _check_script()
    source = GraphDataSource(live_settings)
    try:
        for name, question, entity_id in script.QUESTIONS:
            payload = {"question": question}
            if entity_id:
                payload["entity_id"] = entity_id
            response = source.ask(REPO, AskRequest(**payload))

            outcome, reason_code = EXPECTED[name]
            assert response.outcome == outcome, (
                f"{name}: expected outcome {outcome!r}, got {response.outcome!r} "
                f"(reason {response.reason_code!r})"
            )
            assert response.reason_code == reason_code, (
                f"{name}: expected reason {reason_code!r}, got {response.reason_code!r}"
            )

            if name == "http2-revert":
                numbers = {
                    script.source_number_from_url(c.source_url)
                    for c in response.citations
                }
                assert HTTP2_CITATIONS <= numbers, (
                    "the HTTP/2 answer must cite both the addition (#3456) and the "
                    f"revert (#3466); it cited {sorted(numbers)}"
                )

            if name == "injection":
                leaked = get_answer_system_prompt()
                assert leaked not in (response.answer or ""), (
                    "the injection answer echoed the system prompt"
                )
                assert "system prompt" not in (response.answer or "").lower(), (
                    "the injection answer claims to reveal the system prompt"
                )

        # The single-decision scenario is answered when the repository holds an
        # entity with exactly one decision and one verified quote, and the check
        # says so plainly when it does not. Both are acceptable; a refusal is not.
        repo_graph = source.get_graph(REPO, None).model_dump()
        partial = script.pick_single_quote_entity(
            repo_graph,
            lambda eid: (200, source.get_graph(REPO, eid).model_dump()),
        )
        if partial is not None:
            response = source.ask(
                REPO, AskRequest(question=f"Why was {partial['path']} changed?")
            )
            assert response.outcome in {"full", "partial"}, (
                f"the single-decision entity {partial['entity_id']} must be answered, "
                f"got {response.outcome!r} (reason {response.reason_code!r})"
            )
    finally:
        store = getattr(source, "store", None)
        if store is not None:
            store.close()
