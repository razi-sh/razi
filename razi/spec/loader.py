import json
import yaml
from pathlib import Path
from typing import Dict, Any

class SpecLoadError(Exception):
    pass

def load_yaml(path: str) -> Dict[str, Any]:
    """Load a YAML file into a Python dict."""
    p = Path(path)
    if not p.exists():
        raise SpecLoadError(f"File not found: {path}")
    try:
        with p.open('r') as f:
            return yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise SpecLoadError(f"YAML parsing error: {str(e)}")

def load_json(path: str) -> Dict[str, Any]:
    """Load a JSON file into a Python dict."""
    p = Path(path)
    if not p.exists():
        raise SpecLoadError(f"File not found: {path}")
    try:
        with p.open('r') as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        raise SpecLoadError(f"JSON parsing error: {str(e)}")

def load_spec(spec_path: str) -> Dict[str, Any]:
    """Load an .aispec file."""
    if not spec_path.endswith(".aispec"):
        raise SpecLoadError(f"Spec file must have .aispec extension: {spec_path}")
    return load_yaml(spec_path)
