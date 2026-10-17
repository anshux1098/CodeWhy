"""The live-answer check must say which number is which.

The old line printed ``number=cit_ev_...``, which is the citation's own id, not the
pull request it points at. A reader could not tell a citation id from a source
number. The output now prints the confidence label and score for every answer, and
for each citation prints its id and the real source number as separate, labelled
fields with a legend explaining the difference.
"""

from __future__ import annotations

from scripts.check_live_answers import pick_single_quote_entity, print_ask

ENTRY = {
    "status": 200,
    "request": {"question": "Why was HTTP/2 TLS support reverted?"},
    "response": {
        "outcome": "full",
        "reason_code": None,
        "fixture": False,
        "entity": {"id": "file:urllib3/urllib3:src/urllib3/util/ssl_.py", "label": "src/urllib3/util/ssl_.py"},
        "answer": "It was reverted because the TLS settings broke other clients.",
        "confidence": {
            "label": "HIGH",
            "score": 0.86,
            "signals": {
                "directness": 1.0,
                "provenance": 0.8,
                "agreement": 0.7,
                "relevance": 0.88,
                "temporal_consistency": 1.0,
                "contradiction": 0.0,
            },
        },
        "decisions": [{"id": "dec_ce303eb845540d38", "summary": "Revert the addition of TLS settings for HTTP/2"}],
        "citations": [{
            "id": "cit_ev_19d0f0f0",
            "decision_id": "dec_ce303eb845540d38",
            "kind": "SOURCE",
            "source_type": "PullRequest",
            "source_url": "https://github.com/urllib3/urllib3/pull/3466",
            "quote": "This reverts the HTTP/2 TLS changes.",
            "author": "reviewer",
            "timestamp": "2023-01-01T00:00:00Z",
        }],
    },
}


def test_print_ask_reports_confidence_label_and_score(capsys) -> None:
    print_ask("http2-revert", ENTRY)
    out = capsys.readouterr().out
    assert "CONFIDENCE label=HIGH score=0.86" in out


def test_print_ask_reports_the_confidence_components(capsys) -> None:
    """The label and score alone hide which signal drove them, so the read-only
    component breakdown is printed for every answered scenario."""
    print_ask("http2-revert", ENTRY)
    out = capsys.readouterr().out
    assert "components:" in out
    assert '"directness": 1.0' in out
    assert '"relevance": 0.88' in out
    assert '"contradiction": 0.0' in out


def test_print_ask_separates_citation_id_from_source_number(capsys) -> None:
    print_ask("http2-revert", ENTRY)
    out = capsys.readouterr().out
    assert "id=cit_ev_19d0f0f0" in out
    assert "source_number=3466" in out
    # The old, ambiguous label must be gone.
    assert "number=cit_ev_19d0f0f0" not in out


def test_print_ask_explains_the_two_numbers(capsys) -> None:
    print_ask("http2-revert", ENTRY)
    out = capsys.readouterr().out
    assert "citation id" in out
    assert "source number" in out


def _node(node_id: str, kind: str, label: str) -> dict:
    return {"id": node_id, "type": kind, "label": label, "props": {}}


def _edge(source: str, target: str, kind: str) -> dict:
    return {"source": source, "target": target, "type": kind, "rule": None}


def test_pick_single_quote_entity_wants_exactly_one_decision_and_one_quote() -> None:
    """The story is simplest when one decision with one quote governs the file.

    The repository-wide /graph view is capped and can fill with code entities,
    decisions and pull requests, so it may carry no SUPPORTED_BY edge at all.
    Discovery must therefore read each entity's own subgraph, reached with
    /graph?entity_id=, where the supporting evidence is actually present.
    """
    good = "file:urllib3/urllib3:src/urllib3/util/url.py"
    two_quotes = "file:urllib3/urllib3:src/urllib3/connection.py"
    two_decisions = "file:urllib3/urllib3:src/urllib3/util/ssl_.py"
    repo_graph = {
        "nodes": [
            _node(good, "CodeEntity", "src/urllib3/util/url.py"),
            _node(two_quotes, "CodeEntity", "src/urllib3/connection.py"),
            _node(two_decisions, "CodeEntity", "src/urllib3/util/ssl_.py"),
        ],
        # No SUPPORTED_BY edges here: the capped view does not reach the evidence.
        "edges": [
            _edge("dec_a", good, "GOVERNS"),
            _edge("dec_b", two_quotes, "GOVERNS"),
            _edge("dec_c", two_decisions, "GOVERNS"),
            _edge("dec_d", two_decisions, "GOVERNS"),
        ],
    }
    per_entity = {
        good: {
            "nodes": [_node(good, "CodeEntity", "src/urllib3/util/url.py")],
            "edges": [
                _edge("dec_a", good, "GOVERNS"),
                _edge("dec_a", "ev_a1", "SUPPORTED_BY"),
            ],
        },
        two_quotes: {
            "nodes": [_node(two_quotes, "CodeEntity", "src/urllib3/connection.py")],
            "edges": [
                _edge("dec_b", two_quotes, "GOVERNS"),
                _edge("dec_b", "ev_b1", "SUPPORTED_BY"),
                _edge("dec_b", "ev_b2", "SUPPORTED_BY"),
            ],
        },
        two_decisions: {
            "nodes": [_node(two_decisions, "CodeEntity", "src/urllib3/util/ssl_.py")],
            "edges": [
                _edge("dec_c", two_decisions, "GOVERNS"),
                _edge("dec_d", two_decisions, "GOVERNS"),
                _edge("dec_c", "ev_c1", "SUPPORTED_BY"),
                _edge("dec_d", "ev_d1", "SUPPORTED_BY"),
            ],
        },
    }

    picked = pick_single_quote_entity(repo_graph, lambda eid: (200, per_entity[eid]))

    assert picked is not None
    assert picked["entity_id"] == good
    assert picked["path"] == "src/urllib3/util/url.py"
    assert picked["decision_id"] == "dec_a"


def test_pick_single_quote_entity_returns_none_when_nothing_qualifies() -> None:
    e1 = "file:urllib3/urllib3:src/a.py"
    repo_graph = {"nodes": [_node(e1, "CodeEntity", "src/a.py")], "edges": []}

    def fetch(entity_id: str):
        return 200, {
            "nodes": [_node(e1, "CodeEntity", "src/a.py"), _node("d1", "Decision", "x")],
            "edges": [_edge("d1", e1, "GOVERNS")],  # no SUPPORTED_BY quote at all
        }

    assert pick_single_quote_entity(repo_graph, fetch) is None


def test_pick_single_quote_entity_skips_entities_it_cannot_read() -> None:
    """A per-entity lookup that fails must not abort the search for a good one."""
    ok = "file:urllib3/urllib3:src/urllib3/http2/connection.py"
    broken = "file:urllib3/urllib3:src/broken.py"
    repo_graph = {
        "nodes": [_node(broken, "CodeEntity", "src/broken.py"),
                  _node(ok, "CodeEntity", "src/urllib3/http2/connection.py")],
        "edges": [],
    }

    def fetch(entity_id: str):
        if entity_id == broken:
            return 404, {"detail": "not found"}
        return 200, {
            "nodes": [_node(ok, "CodeEntity", "src/urllib3/http2/connection.py")],
            "edges": [_edge("dec_a", ok, "GOVERNS"), _edge("dec_a", "ev", "SUPPORTED_BY")],
        }

    picked = pick_single_quote_entity(repo_graph, fetch)
    assert picked is not None
    assert picked["entity_id"] == ok
