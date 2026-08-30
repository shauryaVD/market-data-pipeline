from __future__ import annotations

from market_data_pipeline.db import build_failure_summary


def test_failure_summary_contains_runbook_steps():
    summary = build_failure_summary(ValueError("bad file"))

    assert summary["error_type"] == "ValueError"
    assert summary["summary"] == "bad file"
    assert summary["diagnosis"]
    assert summary["mitigation"]
    assert summary["escalation"]
