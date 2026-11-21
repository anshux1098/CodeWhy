from __future__ import annotations

import json

from app.providers.llm_provider import MockLLMProvider
from app.services.extraction import extract_decisions_from_source
from app.services.quote_check import expand_ellipsis_quote, verify_quote


def test_expand_ellipsis_quote_deterministic_span():
    source = (
        "When mobile clients kept timing out on flaky cellular networks, "
        "the global retry budget was raised from 3 to 5 per host so transient "
        "connection resets do not fail the request."
    )
    abridged = "When mobile clients kept timing out ... connection resets do not fail the request."
    expanded = expand_ellipsis_quote(abridged, source)
    assert expanded == source
    assert verify_quote(abridged, source).is_verified is True

    # Too short on one side (< 20 chars) -> refused
    assert expand_ellipsis_quote("When mobile ... connection resets do not fail the request.", source) is None


def test_per_section_quote_attribution_attributes_comment_author():
    payload = json.dumps({
        "decisions": [
            {
                "summary": "Enforce strict TLS 1.3 minimum",
                "decision_type": "Security",
                "rationale": "Legacy TLS 1.1 ciphers fail compliance audits.",
                "supporting_evidence": [
                    {
                        "quote": "Legacy TLS 1.1 ciphers fail compliance audits and must be disabled.",
                        "claim": "Compliance audit requirement",
                    }
                ],
            }
        ]
    })
    provider = MockLLMProvider(canned_response=payload)
    records = extract_decisions_from_source(
        provider=provider,
        source_id="pr:acme/net#88",
        source_type="pull_request",
        source_url="https://github.com/acme/net/pull/88",
        repo="acme/net",
        title="Update TLS defaults",
        body="Updating cipher defaults.",
        author="pr_author",
        created_at="2025-01-01T00:00:00Z",
        comments=[
            {
                "author": "security_reviewer",
                "body": "Legacy TLS 1.1 ciphers fail compliance audits and must be disabled.",
                "createdAt": "2025-01-02T10:30:00Z",
            }
        ],
    )
    assert len(records) == 1
    assert records[0].quote_verified is True
    ev = records[0].evidence[0]
    assert ev.author == "security_reviewer"
    assert ev.timestamp == "2025-01-02T10:30:00Z"
