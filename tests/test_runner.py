"""
Tests for the runner (runtime) module.
Validates execution against mock providers without hitting a real LLM.
"""
import json
import pytest
from pathlib import Path
from unittest.mock import patch
from razi.compiler.compile import compile_spec
from razi.runtime.runtime import execute_run


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


def test_runner_produces_final_output():
    """Successful run must produce final_output.json."""
    build_dir = compile_spec("examples/escalation.aispec", BASE_DIR)
    with patch(_SYNTHESIZE_PATH, return_value=_compliant_response()):
        run_dir = execute_run(build_dir, SLA_BREACH_INPUT, BASE_DIR)
    assert (run_dir / "final_output.json").exists()


def test_runner_produces_evidence_index():
    """Successful run must produce evidence_index.json."""
    build_dir = compile_spec("examples/escalation.aispec", BASE_DIR)
    with patch(_SYNTHESIZE_PATH, return_value=_compliant_response()):
        run_dir = execute_run(build_dir, SLA_BREACH_INPUT, BASE_DIR)
    assert (run_dir / "evidence_index.json").exists()


def test_runner_produces_trace():
    """Successful run must produce trace.jsonl."""
    build_dir = compile_spec("examples/escalation.aispec", BASE_DIR)
    with patch(_SYNTHESIZE_PATH, return_value=_compliant_response()):
        run_dir = execute_run(build_dir, SLA_BREACH_INPUT, BASE_DIR)
    assert (run_dir / "trace.jsonl").exists()


def test_runner_authoritative_merge_overwrites_model():
    """Runtime must overwrite policy_compliant — model cannot self-certify."""
    build_dir = compile_spec("examples/escalation.aispec", BASE_DIR)
    # Attempt 1: Model lies (S3 on enterprise SLA breach)
    # Attempt 2: Model corrects to S1
    lying_response = json.dumps({
        "recommended_severity": "S3",
        "confidence": 0.9,
        "justification": "Looks fine.",
        "evidence_ids": ["E1"],
        "policy_compliant": True,
        "violations": [],
    })
    with patch(_SYNTHESIZE_PATH, side_effect=[lying_response, _compliant_response()]):
        run_dir = execute_run(build_dir, SLA_BREACH_INPUT, BASE_DIR)
    with open(run_dir / "final_output.json") as f:
        out = json.load(f)
    assert out["recommended_severity"] == "S1"
