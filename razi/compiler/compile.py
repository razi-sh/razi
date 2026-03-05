import json
from pathlib import Path

from razi.spec.loader import load_spec
from razi.spec.validator import validate_spec, hash_file
from .ir import generate_ir
from .dag import generate_dag
from .policy_compile import generate_policy
from .lock import generate_lockfile

class CompileError(Exception):
    pass

def compile_spec(spec_path: str, base_dir: Path) -> Path:
    """
    Given a spec file, validate it and emit build artifacts.
    Returns the path to the build directory.
    """
    raw_spec = load_spec(spec_path)
    
    spec_name = raw_spec.get("name")
    if not spec_name:
        raise CompileError("Spec is missing 'name' field.")

    canonical_json, spec_hash = validate_spec(raw_spec, base_dir)

    build_dir = base_dir / "build" / spec_name
    build_dir.mkdir(parents=True, exist_ok=True)

    # 1. IR Map
    ir = generate_ir(raw_spec, base_dir)
    with open(build_dir / "ir.json", "w") as f:
        json.dump(ir, f, indent=2)

    # 2. DAG
    dag = generate_dag(raw_spec)
    with open(build_dir / "dag.json", "w") as f:
        json.dump(dag, f, indent=2)

    # 3. Policy
    policy = generate_policy(raw_spec)
    with open(build_dir / "policy.json", "w") as f:
        json.dump(policy, f, indent=2)

    # 4. Lockfile
    input_hash = hash_file(base_dir / ir['input_schema'])
    output_hash = hash_file(base_dir / ir['output_schema'])
    template_path = base_dir / ir['template']
    template_hash = hash_file(template_path)

    lock = generate_lockfile(
        raw_spec=raw_spec,
        spec_hash=spec_hash,
        input_hash=input_hash,
        output_hash=output_hash,
        template_hash=template_hash,
        template_path=ir['template']
    )
    with open(build_dir / "lock.json", "w") as f:
        json.dump(lock, f, indent=2)

    # 5. Manifest
    manifest = {
        "spec_name": spec_name,
        "spec_hash": spec_hash,
        "artifacts": ["ir.json", "dag.json", "policy.json", "lock.json"]
    }
    with open(build_dir / "manifest.json", "w") as f:
        json.dump(manifest, f, indent=2)

    return build_dir
