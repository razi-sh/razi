"""
Tests for the replay module.
Validates that replay re-evaluates schema, evidence, and policy deterministically
without calling the model.
"""
import json
import pytest
from pathlib import Path
from unittest.mock import patch
from razi.compiler.compile import compile_spec
from razi.runtime.runtime import execute_run
from razi.replay.replay import execute_replay


BASE_DIR = Path(__file__).parent.parent
SLA_BREACH_INPUT = BASE_DIR / "examples/inputs/sla_breach.json"

_SYNTHESIZE_PATH = "razi.providers.openai_provider.OpenAIProvider.synthesize"


@pytest.fixture(autouse=True)
def set_api_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-mock")


def _compliant_response():
    return json.dumps({
        "recommended_severity": "S1",
        "confidence": 0.9,
        "justification": "SLA breach detected. Enterprise account exceeded SLA.",
        "evidence_ids": ["E1"],
        "policy_compliant": True,
        "violations": [],
    })


def _run_once(tmp_path):
    """Helper: compile + run once with a mock provider, return run_dir."""
    build_dir = compile_spec("examples/escalation.aispec", BASE_DIR)
    with patch(_SYNTHESIZE_PATH, return_value=_compliant_response()):
        return execute_run(build_dir, SLA_BREACH_INPUT, tmp_path)


def test_replay_produces_report(tmp_path):
    """razi replay must produce replay_report.json."""
    run_dir = _run_once(tmp_path)
    report_path = execute_replay(run_dir, BASE_DIR, ignore_template_drift=True)
    assert report_path.exists()


def test_replay_passes_on_compliant_run(tmp_path):
    """Replay of a compliant run must return PASS result."""
    run_dir = _run_once(tmp_path)
    report_path = execute_replay(run_dir, BASE_DIR, ignore_template_drift=True)
    with open(report_path) as f:
        report = json.load(f)
    assert report["result"] == "PASS"


def test_replay_confirms_policy_match(tmp_path):
    """Replay must confirm policy evaluation matches stored result."""
    run_dir = _run_once(tmp_path)
    report_path = execute_replay(run_dir, BASE_DIR, ignore_template_drift=True)
    with open(report_path) as f:
        report = json.load(f)
    assert report["policy_match"] is True


def test_replay_confirms_final_output_match(tmp_path):
    """Replay must confirm final output matches stored output."""
    run_dir = _run_once(tmp_path)
    report_path = execute_replay(run_dir, BASE_DIR, ignore_template_drift=True)
    with open(report_path) as f:
        report = json.load(f)
    assert report["final_output_match"] is True
