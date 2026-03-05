import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List

class Tracer:
    """Manages appending trace.jsonl events."""
    
    def __init__(self, trace_file: Path, run_id: str):
        self.trace_file = trace_file
        self.run_id = run_id
        
    def _emit(self, event_type: str, step_id: Optional[str] = None, attempt: Optional[int] = None, **kwargs):
        event = {
            "timestamp": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
            "run_id": self.run_id,
            "event_type": event_type,
            "step_id": step_id,
            "attempt": attempt
        }
        event.update(kwargs)
        
        with self.trace_file.open("a") as f:
            f.write(json.dumps(event) + "\n")
            
    def step_start(self, step_id: str):
        self._emit("step_start", step_id=step_id)
        
    def step_end(self, step_id: str):
        self._emit("step_end", step_id=step_id)
        
    def attempt_start(self, step_id: str, attempt: int):
        self._emit("attempt_start", step_id=step_id, attempt=attempt)
        
    def attempt_end(self, step_id: str, attempt: int):
        self._emit("attempt_end", step_id=step_id, attempt=attempt)
        
    def failure_classified(self, step_id: str, attempt: int, failures: List[str]):
        self._emit("failure_classified", step_id=step_id, attempt=attempt, failures=failures)
        
    def policy_evaluated(self, step_id: str, attempt: int, compliant: bool, violations: List[str]):
        self._emit("policy_evaluated", step_id=step_id, attempt=attempt, compliant=compliant, violations=violations)
        
    def artifact_written(self, step_id: str, attempt: Optional[int], path: str):
        self._emit("artifact_written", step_id=step_id, attempt=attempt, path=path)
