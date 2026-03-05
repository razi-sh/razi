import json
import hashlib
from typing import Dict, Any, Tuple
from pathlib import Path

from jsonschema import validate, ValidationError
from .loader import load_json, SpecLoadError


class SpecValidationError(Exception):
    pass


def get_schema_path() -> Path:
    """Return the path to the internal spec_schema.json."""
    return Path(__file__).parent / "spec_schema.json"


def validate_spec(spec: Dict[str, Any], base_dir: Path) -> Tuple[str, str]:
    """
    Validate an .aispec dict against the schema and constraints.
    Returns (canonical_json_string, spec_sha256).
    """
    schema_path = get_schema_path()
    try:
        schema = load_json(str(schema_path))
    except SpecLoadError as e:
        raise SpecValidationError(f"Could not load internal schema: {e}")

    # 1. JSON Schema Validation
    try:
        validate(instance=spec, schema=schema)
    except ValidationError as e:
        raise SpecValidationError(f"Schema validation failed: {str(e)}")

    # 2. Semantic validations on `operators`
    operators = spec.get("operators", [])
    types = [op.get("type") for op in operators]

    if types.count("evidence.index") > 1:
        raise SpecValidationError("operators can contain at most one 'evidence.index'.")
    if types.count("synth.json") != 1:
        raise SpecValidationError("operators must contain exactly one 'synth.json'.")

    # Policy is validated at compile time by generate_policy() in policy_compile.py

    # 3. Resolve template path from synth operator
    synth_op = next(op for op in operators if op["type"] == "synth.json")
    template = synth_op.get("template", "")

    input_schema_path = base_dir / spec["input_schema"]
    output_schema_path = base_dir / spec["output_schema"]
    template_path = base_dir / template

    if not input_schema_path.exists():
        raise SpecValidationError(f"Input schema not found: {input_schema_path}")
    if not output_schema_path.exists():
        raise SpecValidationError(f"Output schema not found: {output_schema_path}")
    if template and not template_path.exists():
        raise SpecValidationError(f"Prompt template file not found at {template_path}")

    # Canonicalize and hash
    canonical = json.dumps(spec, sort_keys=True, separators=(",", ":"))
    spec_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    return canonical, spec_hash


def hash_file(path: Path) -> str:
    """Compute sha256 of a file."""
    sha256_hash = hashlib.sha256()
    with open(path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()
