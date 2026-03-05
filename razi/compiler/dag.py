from typing import Dict, Any, List


def generate_dag(spec: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Extract execution DAG from the new `operators` format.
    For v1, this is strictly a linear, 2-step sequence.
    """
    operators = spec["operators"]
    dag = []

    # Optional evidence.index operator
    evidence_ops = [op for op in operators if op["type"] == "evidence.index"]
    evidence_op = evidence_ops[0] if evidence_ops else None

    if evidence_op:
        dag.append({
            "id": evidence_op["id"],
            "op": "evidence.index",
            "depends_on": [],
            "params": {
                "fields": evidence_op.get("fields", [])
            }
        })

    # Required synth.json operator
    synth_op = next(op for op in operators if op["type"] == "synth.json")
    dag.append({
        "id": synth_op["id"],
        "op": "synth.json",
        "depends_on": [evidence_op["id"]] if evidence_op else [],
        "params": {
            "evidence_ref": synth_op.get("evidence_ref"),
            "output_schema_ref": "output",
            "max_attempts": synth_op.get("max_attempts", 3),
            "confidence_threshold": synth_op.get("confidence_threshold", 0.6),
            "strategy": {
                "max_attempts": synth_op.get("max_attempts", 3),
                "on_schema_failure": "auto_correct",
                "on_policy_violation": "reprompt_with_violations",
                "on_missing_evidence": "reprompt_require_evidence",
                "on_low_confidence": "reprompt_stricter_reasoning"
            }
        }
    })

    return dag
