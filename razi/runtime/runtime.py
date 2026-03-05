import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Dict, Any

from jsonschema import validate, ValidationError

from .evidence import run_evidence_index
from .synthesis import SynthesisEngine, MaxAttemptsExceeded
from .trace import Tracer
from .policy import apply_authoritative_merge
from razi.spec.loader import load_json
from razi.providers.base import Provider
from razi.providers.openai_provider import OpenAIProvider

class RunError(Exception):
    pass

def execute_run(build_dir: Path, input_path: Path, output_base: Path, provider: Optional[Provider] = None):
    """
    Core executor that manages the strictly ordered DAG run and
    artifact emission for offline replay.
    """
    # 1. Load artifacts
    try:
        ir: Dict[str, Any] = load_json(str(build_dir / "ir.json"))
        dag: List[Dict[str, Any]] = load_json(str(build_dir / "dag.json"))  # type: ignore
        policy: Dict[str, Any] = load_json(str(build_dir / "policy.json"))
        lock: Dict[str, Any] = load_json(str(build_dir / "lock.json"))
        with open(input_path, "r") as f:
            raw_input = f.read()
            input_data = json.loads(raw_input)
    except Exception as e:
        raise RunError(f"Failed to load build artifacts or input: {str(e)}")

    # 2. Validate input JSON against schema
    base_dir = build_dir.parent.parent
    input_schema_path = base_dir / ir["input_schema"]
    input_schema = load_json(str(input_schema_path))
    try:
        validate(instance=input_data, schema=input_schema)
    except ValidationError as e:
        raise RunError(f"Input JSON validation failed: {str(e)}")

    # 3. Compute run_id
    spec_name = ir["name"]
    utc_str = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    hash_input = raw_input + json.dumps(lock, sort_keys=True)
    short_hash = hashlib.sha256(hash_input.encode('utf-8')).hexdigest()[:8]
    run_id = f"{spec_name}__{utc_str}__{short_hash}"

    run_dir = output_base / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    # Re-save artifacts to run dir
    with open(run_dir / "input.json", "w") as f:
        f.write(raw_input)
    with open(run_dir / "lock_snapshot.json", "w") as f:
        json.dump(lock, f, indent=2)

    tracer = Tracer(run_dir / "trace.jsonl", run_id)
    if provider is None:
        provider = OpenAIProvider()
    
    # Extract nodes (DAG is linear)
    evidence_node = next((n for n in dag if n["op"] == "evidence.index"), None)
    synth_node = next(n for n in dag if n["op"] == "synth.json")

    # 4. Execute evidence.index (if present)
    evidence_index: List[Dict[str, Any]] = []
    if evidence_node:
        tracer.step_start(evidence_node["id"])

        # New canonical format: fields is a list of {key, source, governed} dicts
        # Legacy format: fields is a list of strings
        fields = evidence_node.get("params", {}).get("fields", [])

        evidence_index = run_evidence_index(input_data, fields)
        with open(run_dir / "evidence_index.json", "w") as f:
            json.dump(evidence_index, f, indent=2)
        tracer.artifact_written(evidence_node["id"], None, str(run_dir / "evidence_index.json"))
        tracer.step_end(evidence_node["id"])

    # Fix schema reference path for synthesis logic
    synth_params = synth_node.get("params", {})
    if "output_schema_ref" not in synth_params:
        synth_params["output_schema_ref"] = ir["output_schema"]
    elif synth_params["output_schema_ref"] == "output":
         synth_params["output_schema_ref"] = ir["output_schema"]
    # 5. Execute synth.json
    engine = SynthesisEngine(provider, tracer, base_dir, run_dir)
    try:
        parsed_model_output, policy_result = engine.synthesize(
            step_id=synth_node["id"],
            params=synth_params,
            input_data=input_data,
            evidence_index=evidence_index,
            policy_config=policy,
            lockfile=lock
        )
    except MaxAttemptsExceeded as e:
        with open(run_dir / "status.json", "w") as f:
            json.dump({"status": "FAILURE", "reason": "MAX_ATTEMPTS_EXCEEDED"}, f)
        raise e

    # 6. Authoritative Merge
    final_output = apply_authoritative_merge(
        model_output=parsed_model_output,
        compliant=policy_result["compliant"],
        violations=policy_result["violations"]
    )

    with open(run_dir / "policy_eval_final.json", "w") as f:
        json.dump(policy_result, f, indent=2)
    
    with open(run_dir / "final_output.json", "w") as f:
        json.dump(final_output, f, indent=2)

    with open(run_dir / "status.json", "w") as f:
        json.dump({"status": "SUCCESS"}, f)
        
    return run_dir
