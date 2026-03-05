from razi.runtime.evidence import run_evidence_index

def test_evidence_determinism():
    input_data = {
        "customer_messages": ["A", "B"],
        "usage_metrics": {"z_metric": 10, "a_metric": 5},
        "ticket_id": "T-1",
        "account_tier": "enterprise",
        "internal_notes": ["Note 1"]
    }
    
    fields = ["customer_messages", "usage_metrics", "internal_notes"]
    
    # Run multiple times to ensure exact same ordering
    run1 = run_evidence_index(input_data, fields)
    run2 = run_evidence_index(input_data, fields)
    
    assert run1 == run2
    
    # Expected explicit order:
    # 1. Customer messages (list items)
    assert run1[0]["text"] == "A"
    assert run1[0]["eid"] == "E1"
    assert run1[1]["text"] == "B"
    assert run1[1]["eid"] == "E2"
    
    # 2. usage_metrics sorted alphabetically (a_metric before z_metric)
    assert run1[2]["locator"] == "a_metric"
    assert run1[2]["eid"] == "E3"
    assert run1[3]["locator"] == "z_metric"
    assert run1[3]["eid"] == "E4"
    
    # 3. Internal notes
    assert run1[4]["text"] == "Note 1"
    assert run1[4]["eid"] == "E5"
