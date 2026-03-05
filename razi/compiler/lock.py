from typing import Dict, Any


def generate_lockfile(
    raw_spec: Dict[str, Any],
    spec_hash: str,
    input_hash: str,
    output_hash: str,
    template_hash: str,
    template_path: str
) -> Dict[str, Any]:
    """Generate the deterministic build lockfile."""
    model = raw_spec.get("model", {})

    return {
        "model": model.get("id"),
        "temperature": model.get("temperature"),
        "provider": model.get("provider"),
        "template_path": template_path,
        "template_sha256": template_hash,
        "spec_hash": spec_hash,
        "input_schema_hash": input_hash,
        "output_schema_hash": output_hash
    }
