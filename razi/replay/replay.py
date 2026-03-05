import json
from datetime import datetime, timezone
from pathlib import Path

from jsonschema import validate, ValidationError

from razi.spec.loader import load_json
from razi.spec.validator import hash_file
from razi.runtime.policy import evaluate_policy, apply_authoritative_merge
from .store import RunStore

class ReplayMismatch(Exception):
    pass

def execute_replay(run_dir: Path, base_dir: Path, ignore_template_drift: bool = False):
    """
    Deterministically re-validates a stored run without calling the LLM.
    Outputs a replay_report.json.
    """
    store = RunStore(run_dir)
    
    # Load required artifacts
    lock = store.load_json("lock_snapshot.json")
    input_data = store.load_json("input.json")
    evidence_index: list[dict] = store.load_json("evidence_index.json") # type: ignore
    stored_final_policy = store.load_json("policy_eval_final.json")
    stored_final_output = store.load_json("final_output.json")
    
    # 1. Load the model output from the final attempt
    model_output = store.load_last_attempt_output()

    mismatches: list[str] = []
    
    # 2. Re-run Schema Validation (Load the live schema matching the lockfile hash)
    # Note: To be fully disconnected, replay assumes the base_dir has the schema, but we must verify its hash
    # In a full system we'd persist the schema in the run_dir, but for wedge v1 we rely on the live file.
    # Actually, the EDD says we just check schema validation again. We'll load the live schemas mapped from lockfile?
    # Wait, the lockfile doesn't store the *paths*, only the hashes. So we assume the user hasn't deleted them from project root.
    # We will search the project root for a schema that matches the hash, or just expect the paths to be standard.
    # For now, we'll try to load them by inferring they are in examples/schemas/
    
    schema_matched = False
    try:
        # Re-evaluating Schema requires the schema. The lockfile only has the hash.
        # This is a v1 limitation: we'll load the live schema and verify its hash matches lock, then validate.
        output_schema_path = base_dir / "examples" / "schemas" / "escalation_decision.schema.json"
        if not output_schema_path.exists():
             mismatches.append("Could not locate output schema to re-validate.")
        else:
             live_schema_hash = hash_file(output_schema_path)
             if live_schema_hash != lock["output_schema_hash"]:
                 mismatches.append(f"Output schema drift detected. Lockfile: {lock['output_schema_hash']}, Live: {live_schema_hash}")
             else:
                 live_schema = load_json(str(output_schema_path))
                 validate(instance=model_output, schema=live_schema)
                 schema_matched = True
    except ValidationError as e:
        mismatches.append(f"Schema validation failed during replay: {str(e)}")
        
    # 3. Evidence ID Existence
    cited = model_output.get("evidence_ids", [])
    valid_ids = {e["eid"] for e in evidence_index}
    invalid = [eid for eid in cited if eid not in valid_ids]
    if invalid:
        mismatches.append(f"Evidence validation failed during replay. Unknown IDs: {invalid}")
        
    # 4. Re-run Policy Engine
    # Note: Replay must re-evaluate policy deterministically based on input and evidence.
    # In v1, we use the hardcoded enterprise_support_v1 engine.
    # We will construct a synthetic policy config to pass to the engine.
    synthetic_policy_config = {
        "preset": "enterprise_support_v1",
        "rules": {
            "sla_escalation": {"enabled": True},
            "no_internal_disclosure": {"enabled": True, "sources": ["internal_notes"]},
            "evidence_required": {"enabled": True},
            "severity_downgrade_protection": {"enabled": True},
            "min_confidence": {"enabled": True, "threshold": 0.6}
        }
    }
    
    is_compliant, violations = evaluate_policy(
        policy_config=synthetic_policy_config,
        input_data=input_data,
        model_output=model_output,
        evidence_index=evidence_index
    )
    
    # 5. Compare computed policy result with stored policy result
    policy_matched = True
    if is_compliant != stored_final_policy["compliant"]:
        mismatches.append(f"Policy compliance mismatch. Stored: {stored_final_policy['compliant']}, Recomputed: {is_compliant}")
        policy_matched = False
    
    if set(violations) != set(stored_final_policy["violations"]):
        mismatches.append(f"Policy violations mismatch. Stored: {stored_final_policy['violations']}, Recomputed: {violations}")
        policy_matched = False

    # 6. Re-compute Authoritative Merge
    recomputed_final = apply_authoritative_merge(
        model_output=model_output,
        compliant=is_compliant,
        violations=violations
    )

    # 7. Confirm final output equals stored final output
    final_output_match = (recomputed_final == stored_final_output)
    if not final_output_match:
         mismatches.append("Authoritative merge mismatch: Recomputed final_output.json differs from stored.")

    # 8. Template Hash Drift
    template_path = base_dir / lock["template_path"]
    template_hash_match = False
    if template_path.exists():
        live_template_hash = hash_file(template_path)
        template_hash_match = (live_template_hash == lock["template_sha256"])
        if not template_hash_match and not ignore_template_drift:
            mismatches.append(f"Template drift detected. Lockfile: {lock['template_sha256']}, Live: {live_template_hash}")
    else:
        mismatches.append("Template file missing.")
        
    result_status = "PASS" if not mismatches else "FAIL"

    report = {
        "run_id": run_dir.name,
        "replay_timestamp": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "schema_match": schema_matched,
        "policy_match": policy_matched,
        "template_hash_match": template_hash_match,
        "final_output_match": final_output_match,
        "result": result_status,
        "mismatches": mismatches
    }

    report_path = run_dir / "replay_report.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)

    if result_status == "FAIL":
        raise ReplayMismatch(f"Replay failed: {mismatches}")
        
    return report_path
