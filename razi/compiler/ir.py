from typing import Dict, Any
from pathlib import Path


def generate_ir(spec: Dict[str, Any], base_dir: Path) -> Dict[str, Any]:
    """Extract canonical mappings from the spec for runtime use."""
    # Find the synth operator to get template, max_attempts, confidence_threshold
    synth_op = next(
        (op for op in spec["operators"] if op["type"] == "synth.json"), None
    )
    template = synth_op.get("template", "") if synth_op else ""

    # Resolve schema paths relative to spec base dir if they don't already include a subdir
    input_schema = spec["input_schema"]
    output_schema = spec["output_schema"]

    return {
        "name": spec["name"],
        "version": str(spec["version"]),
        "input_schema": input_schema,
        "output_schema": output_schema,
        "template": template,
        "operators": spec["operators"],
    }
