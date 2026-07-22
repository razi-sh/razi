"""
Offline test for razi_adapter.RaziGovernor.

No network access, no GOOGLE_API_KEY, and no real ADK Runner/agent loop are
needed: this test fabricates minimal fake `tool` / `tool_context` objects
that match the shape RaziGovernor's callbacks read (`tool.name`,
`tool_context.state`), drives the governor directly through a
reject -> reject -> accept sequence, and asserts the recorded run replays
clean via Razi's own (unmodified) `execute_replay`.

Deliberately NOT placed under the repo's top-level `tests/` directory:
core CI (`.github/workflows/ci.yml`) runs `pytest tests/ -v` across a
Python 3.9-3.12 matrix with only `pip install -e '.[dev]'`, and google-adk
requires Python >=3.10 and is never installed there. Keeping this file
under `examples/adk_escalation_agent/tests/` keeps it out of that
discovery path; the `importorskip` below is defense-in-depth in case
someone runs bare `pytest` from the repo root instead.

Run with:
    pytest examples/adk_escalation_agent/tests/test_adapter_offline.py -v
"""
import json
import shutil
import sys
from pathlib import Path

import pytest

pytest.importorskip("google.adk")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from razi_adapter import RaziGovernor, REPO_ROOT  # noqa: E402
from razi.replay.replay import execute_replay  # noqa: E402


class FakeTool:
    def __init__(self, name: str):
        self.name = name


class FakeToolContext:
    def __init__(self):
        self.state = {}


TICKET_CONTEXT = {
    "ticket_id": "TEST-1",
    "account_tier": "enterprise",
    "current_severity": "S2",
    "sla_hours": 4,
    "time_open_hours": 10.0,
    "customer_messages": ["Help, this is broken."],
    "internal_notes": ["Confidential: root cause was our bug."],
}
ACCOUNT_USAGE = {
    "usage_metrics": {"error_rate_pct": 20.0},
    "open_incidents": 1,
    "contract_value": 500000.0,
}


def _gather_context(governor: RaziGovernor, ctx: FakeToolContext) -> None:
    governor.before_tool_callback(FakeTool("get_ticket_context"), {"ticket_id": "TEST-1"}, ctx)
    governor.after_tool_callback(FakeTool("get_ticket_context"), {}, ctx, TICKET_CONTEXT)
    governor.before_tool_callback(FakeTool("get_account_usage"), {"ticket_id": "TEST-1"}, ctx)
    governor.after_tool_callback(FakeTool("get_account_usage"), {}, ctx, ACCOUNT_USAGE)


def _cleanup(run_id: str) -> None:
    shutil.rmtree(REPO_ROOT / "runs" / run_id, ignore_errors=True)


def test_reject_then_accept_replays_clean():
    governor = RaziGovernor(scenario_name="test_offline")
    ctx = FakeToolContext()
    _gather_context(governor, ctx)
    decision_tool = FakeTool("submit_escalation_decision")

    # Attempt 1: SLA-breached enterprise ticket downgraded to S3 -> violates
    # sla_escalation. Must be rejected, real tool must not have run.
    result = governor.before_tool_callback(
        decision_tool,
        {
            "recommended_severity": "S3",
            "confidence": 0.8,
            "evidence_ids": ["E1"],
            "justification": "Minor issue, see E1.",
        },
        ctx,
    )
    assert result is not None
    assert result["status"] == "REJECTED"
    assert any("sla_escalation" in v for v in result["violations"])

    # Attempt 2: corrected severity, but cites a non-existent evidence ID.
    result2 = governor.before_tool_callback(
        decision_tool,
        {
            "recommended_severity": "S1",
            "confidence": 0.9,
            "evidence_ids": ["E99"],
            "justification": "SLA breach, see E99.",
        },
        ctx,
    )
    assert result2 is not None
    assert result2["status"] == "REJECTED"
    assert any("E99" in v for v in result2["violations"])

    # Attempt 3: fully compliant -> real tool executes (before_tool_callback
    # returns None) and the run is finalized as SUCCESS.
    result3 = governor.before_tool_callback(
        decision_tool,
        {
            "recommended_severity": "S1",
            "confidence": 0.9,
            "evidence_ids": ["E1"],
            "justification": "SLA breach for enterprise account, per E1.",
        },
        ctx,
    )
    assert result3 is None

    run_id = ctx.state["razi_run_id"]
    run_dir = REPO_ROOT / "runs" / run_id
    try:
        assert (run_dir / "status.json").exists()
        assert json.loads((run_dir / "status.json").read_text()) == {"status": "SUCCESS"}
        assert (run_dir / "attempts" / "attempt_1").exists()
        assert (run_dir / "attempts" / "attempt_2").exists()
        assert (run_dir / "attempts" / "attempt_3" / "parsed_model_output.json").exists()

        # The real proof: the stock, unmodified `razi replay` CLI code path
        # replays this agent-produced run offline, with no model call.
        report_path = execute_replay(run_dir, REPO_ROOT, ignore_template_drift=False)
        report = json.loads(report_path.read_text())
        assert report["result"] == "PASS", report
        assert report["policy_match"] is True
        assert report["final_output_match"] is True
    finally:
        _cleanup(run_id)


def test_max_attempts_exhausted_fails_safe():
    governor = RaziGovernor(scenario_name="test_offline_failsafe", max_attempts=2)
    ctx = FakeToolContext()
    _gather_context(governor, ctx)
    decision_tool = FakeTool("submit_escalation_decision")

    bad_args = {
        "recommended_severity": "S3",
        "confidence": 0.8,
        "evidence_ids": ["E1"],
        "justification": "Minor issue, see E1.",
    }
    r1 = governor.before_tool_callback(decision_tool, bad_args, ctx)
    assert r1["status"] == "REJECTED"

    r2 = governor.before_tool_callback(decision_tool, bad_args, ctx)
    assert r2["status"] == "REJECTED_FINAL"
    assert ctx.state["razi_closed"] is True

    run_id = r2["run_id"]
    run_dir = REPO_ROOT / "runs" / run_id
    try:
        status = json.loads((run_dir / "status.json").read_text())
        assert status == {"status": "FAILURE", "reason": "MAX_ATTEMPTS_EXCEEDED"}

        # Fail-safe: once closed, further calls are rejected without even
        # re-evaluating -- no non-compliant output is ever authorized.
        r3 = governor.before_tool_callback(decision_tool, bad_args, ctx)
        assert r3["status"] == "REJECTED_FINAL"
    finally:
        _cleanup(run_id)


def test_missing_evidence_is_rejected_before_any_tool_call():
    """Calling submit_escalation_decision before gathering ticket context
    must be rejected -- no evidence, no decision."""
    governor = RaziGovernor(scenario_name="test_offline_no_evidence")
    ctx = FakeToolContext()
    decision_tool = FakeTool("submit_escalation_decision")

    result = governor.before_tool_callback(
        decision_tool,
        {
            "recommended_severity": "S1",
            "confidence": 0.9,
            "evidence_ids": ["E1"],
            "justification": "No context gathered.",
        },
        ctx,
    )
    assert result["status"] == "REJECTED"
    assert "razi_run_id" not in ctx.state
