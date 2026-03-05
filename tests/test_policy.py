import pytest
from razi.runtime.policy import evaluate_policy, apply_authoritative_merge

@pytest.fixture
def base_policy():
    return {
        "preset": "enterprise_support_v1",
        "rules": {
            "sla_escalation": {"enabled": True},
            "no_internal_disclosure": {"enabled": True, "sources": ["internal_notes"]},
            "evidence_required": {"enabled": True},
            "severity_downgrade_protection": {"enabled": True},
            "min_confidence": {"enabled": True, "threshold": 0.6}
        }
    }

@pytest.fixture
def evidence_index():
    return [{"eid": "E1", "text": "foo"}]

def test_sla_escalation_violation(base_policy, evidence_index):
    input_data = {"account_tier": "enterprise", "time_open_hours": 10, "sla_hours": 4}
    model_output = {"recommended_severity": "S3", "evidence_ids": ["E1"], "confidence": 0.8}
    
    compliant, violations = evaluate_policy(base_policy, input_data, model_output, evidence_index)
    assert not compliant
    assert any("sla_escalation" in v for v in violations)

def test_sla_escalation_pass(base_policy, evidence_index):
    input_data = {"account_tier": "enterprise", "time_open_hours": 10, "sla_hours": 4}
    model_output = {"recommended_severity": "S2", "evidence_ids": ["E1"], "confidence": 0.8}
    
    compliant, violations = evaluate_policy(base_policy, input_data, model_output, evidence_index)
    assert compliant

def test_internal_disclosure_violation(base_policy, evidence_index):
    input_data = {"internal_notes": ["secret password 123"]}
    model_output = {
        "recommended_severity": "S3", 
        "evidence_ids": ["E1"], 
        "confidence": 0.8,
        "justification": "The issue was caused by secret password 123."
    }
    
    compliant, violations = evaluate_policy(base_policy, input_data, model_output, evidence_index)
    assert not compliant
    assert any("no_internal_disclosure" in v for v in violations)

def test_evidence_required_violation_fabricated(base_policy, evidence_index):
    # Cited E2, but index only has E1
    model_output = {
        "recommended_severity": "S3", 
        "evidence_ids": ["E2"], 
        "confidence": 0.8
    }
    compliant, violations = evaluate_policy(base_policy, {}, model_output, evidence_index)
    assert not compliant
    assert any("E2" in v for v in violations)

def test_authoritative_merge():
    model_output = {"policy_compliant": True, "violations": []}
    
    # Engine says NO
    final = apply_authoritative_merge(model_output, compliant=False, violations=["Bad"])
    
    assert final["policy_compliant"] is False
    assert final["violations"] == ["Bad"]
