import pytest
from pathlib import Path
import json

def test_full_cli_flow(tmp_path):
    # This acts as an integration test assuming razi is in path
    
    # Needs OPENAI_API_KEY mock. But running the CLI hit the real provider.
    # We will mock the provider for integration tests using pytest-mock, or just write an inner python test that mocks it.
    pass

# We will implement the integration test via python calls rather than subprocess 
# to easily mock the OpenAIProvider.

@pytest.fixture
def mock_openai(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-mock")
    from unittest.mock import patch
    patcher = patch("razi.providers.openai_provider.OpenAIProvider.synthesize")
    mock = patcher.start()
    yield mock
    patcher.stop()

def test_integration_sla_breach(mock_openai, tmp_path):
    from razi.compiler.compile import compile_spec
    from razi.runtime.runtime import execute_run
    from razi.replay.replay import execute_replay
    
    base_dir = Path("/Users/ehsan/Desktop/razi") # using absolute for simplicity in this generated codebase
    
    # Setup mock returns
    mock_openai.return_value = json.dumps({
        "recommended_severity": "S1",
        "confidence": 0.9,
        "justification": "SLA breached for enterprise.",
        "evidence_ids": ["E1"], # We must make sure E1 exists
        "policy_compliant": True,
        "violations": [],
    })

    build_dir = compile_spec("examples/escalation.aispec", base_dir)
    
    run_dir = execute_run(build_dir, base_dir / "examples/inputs/sla_breach.json", base_dir)
    
    assert run_dir.exists()
    
    final_out_path = run_dir / "final_output.json"
    assert final_out_path.exists()
    
    with open(final_out_path, "r") as f:
        final_out = json.load(f)
        
    assert final_out["recommended_severity"] == "S1"
    assert final_out["policy_compliant"] is True
    
    # Test Replay
    report_path = execute_replay(run_dir, base_dir)
    
    with open(report_path, "r") as f:
        report = json.load(f)
        
    assert report["result"] == "PASS"
    assert report["schema_match"] is True
    assert report["policy_match"] is True

def test_integration_policy_catch_and_retry(mock_openai):
    from razi.compiler.compile import compile_spec
    from razi.runtime.runtime import execute_run
    
    base_dir = Path("/Users/ehsan/Desktop/razi")
    
    # Attempt 1: Returns a severity SLA violation (S3 on enterprise)
    # Attempt 2: Corrects it to S2
    mock_openai.side_effect = [
        json.dumps({
            "recommended_severity": "S3",
            "confidence": 0.9,
            "justification": "Trying an S3.",
            "evidence_ids": ["E1"],
            "policy_compliant": True, # Model lies
            "violations": [],
        }),
        json.dumps({
            "recommended_severity": "S2",
            "confidence": 0.9,
            "justification": "Corrected to S2.",
            "evidence_ids": ["E1"],
            "policy_compliant": True,
            "violations": [],
        })
    ]
    
    build_dir = compile_spec("examples/escalation.aispec", base_dir)
    run_dir = execute_run(build_dir, base_dir / "examples/inputs/sla_breach.json", base_dir)
    
    with open(run_dir / "final_output.json", "r") as f:
        final_out = json.load(f)
        
    assert final_out["recommended_severity"] == "S2"
    assert mock_openai.call_count == 2
