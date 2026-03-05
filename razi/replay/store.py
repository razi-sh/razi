import json
from pathlib import Path
from typing import Dict, Any

class RunStoreError(Exception):
    pass

class RunStore:
    def __init__(self, run_dir: Path):
        self.run_dir = run_dir
        if not self.run_dir.exists():
            raise RunStoreError(f"Run directory not found: {run_dir}")

    def load_json(self, filename: str) -> Dict[str, Any]:
        p = self.run_dir / filename
        if not p.exists():
            raise RunStoreError(f"Required artifact not found: {filename}")
        with open(p, "r") as f:
            return json.load(f)

    def load_last_attempt_output(self) -> Dict[str, Any]:
        attempts_dir = self.run_dir / "attempts"
        if not attempts_dir.exists():
            raise RunStoreError("Attempts directory missing.")
        
        # Sort sequentially to find the last attempt
        attempt_dirs = []
        for d in attempts_dir.iterdir():
            if d.is_dir() and d.name.startswith("attempt_"):
                num = int(d.name.split("_")[1])
                attempt_dirs.append((num, d))
        
        if not attempt_dirs:
            raise RunStoreError("No attempts found.")
            
        attempt_dirs.sort(key=lambda x: x[0])
        last_attempt = attempt_dirs[-1][1]
        
        parsed_file = last_attempt / "parsed_model_output.json"
        if not parsed_file.exists():
            raise RunStoreError(f"Parsed model output missing from last attempt: {last_attempt.name}")
            
        with open(parsed_file, "r") as f:
            return json.load(f)
