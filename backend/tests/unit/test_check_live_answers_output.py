"""The live-answer check must say which number is which.

The old line printed ``number=cit_ev_...``, which is the citation's own id, not the
pull request it points at. A reader could not tell a citation id from a source
number. The output now prints the confidence label and score for every answer, and
for each citation prints its id and the real source number as separate, labelled
fields with a legend explaining the difference.
"""

from __future__ import annotations

from scripts.check_live_answers import print_ask

ENTRY = {
    "status": 200,
    "request": {"question": "Why was HTTP/2 TLS support reverted?"},
    "response": {
        "outcome": "full",
        "reason_code": None,
        "fixture": False,
        "entity": {"id": "file:urllib3/urllib3:src/urllib3/util/ssl_.py", "label": "src/urllib3/util/ssl_.py"},
        "answer": "It was reverted because the TLS settings broke other clients.",
        "confidence": {"label": "HIGH", "score": 0.86},
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
