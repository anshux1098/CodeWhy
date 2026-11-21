from __future__ import annotations

from app.schemas.common import CitationKind, SourceType
from app.schemas.decisions import Citation
from app.services.answer import provenance_from_citations, temporal_consistency_from_bundle
from app.services.retrieval import EvidenceBundle


def _cit(source_type: SourceType, author: str | None = "alice", idx: int = 1) -> Citation:
    return Citation(
        id=f"c{idx}",
        decision_id="d1",
        kind=CitationKind.SOURCE,
        quote="Because mobile timeouts.",
        source_url=f"https://github.com/acme/app/pull/{idx}",
        source_type=source_type,
        author=author,
    )


def test_provenance_from_citations_varies_by_source_type_and_attribution():
    doc_cit = _cit(SourceType.DOCUMENT, "alice")
    pr_cit = _cit(SourceType.PULL_REQUEST, "alice")
    commit_cit = _cit(SourceType.COMMIT, None)

    assert provenance_from_citations([doc_cit]) > provenance_from_citations([pr_cit])
    assert provenance_from_citations([pr_cit]) > provenance_from_citations([commit_cit])
    assert provenance_from_citations([], []) == 0.50


def test_temporal_consistency_reflects_drift_and_contradiction():
    clean = EvidenceBundle(
        question="Why?",
        resolved_entity={"id": "e1", "name": "f.py"},
        decisions=[{"id": "d1", "state": "ACTIVE"}],
    )
    drifted = EvidenceBundle(
        question="Why?",
        resolved_entity={"id": "e1", "name": "f.py"},
        decisions=[{"id": "d1", "state": "ACTIVE"}],
        current_value_differs=True,
    )
    contradicted = EvidenceBundle(
        question="Why?",
        resolved_entity={"id": "e1", "name": "f.py"},
        decisions=[{"id": "d1", "state": "UNRESOLVED"}],
        has_contradiction=True,
    )
    assert temporal_consistency_from_bundle(clean) == 1.0
    assert temporal_consistency_from_bundle(drifted) == 0.80
    assert temporal_consistency_from_bundle(contradicted) == 0.75
