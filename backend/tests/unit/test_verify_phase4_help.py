"""The Phase 4 verification script must explain itself before it runs.

`-h` is what a reader tries first. It must print usage and exit 0 without
opening the graph or calling a model, so the script can be read safely before
it is pointed at a live repository.
"""

from __future__ import annotations

import pytest

import scripts.verify_phase4 as verify_phase4


def test_help_prints_usage_and_exits_zero_without_the_graph(monkeypatch, capsys):
    def unreachable(*args, **kwargs):
        raise AssertionError("help must not construct the live data source")

    monkeypatch.setattr(verify_phase4, "GraphDataSource", unreachable)

    with pytest.raises(SystemExit) as excinfo:
        verify_phase4.main(["-h"])

    assert excinfo.value.code == 0
    captured = capsys.readouterr()
    assert "usage" in captured.out.lower()
    assert "verify_phase4" in captured.out or "Phase 4" in captured.out
