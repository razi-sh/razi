import pytest
import json

from razi.runtime.synthesis import SynthesisEngine, MaxAttemptsExceeded
from razi.runtime.trace import Tracer
from razi.providers.base import Provider

class MockProvider(Provider):
    def __init__(self, responses):
        self.responses = responses
        self.call_count = 0
        self.prompts = []

    def synthesize(self, prompt, schema, model_config):
        self.prompts.append(prompt)
        res_idx = min(self.call_count, len(self.responses) - 1)
        res = self.responses[res_idx]
        self.call_count += 1
        return res

@pytest.fixture
def base_dir(tmp_path):
    # Setup dummy paths
    (tmp_path / "schemas").mkdir()
    with open(tmp_path / "schemas" / "out.json", "w") as f:
        json.dump({
            "type": "object", 
            "properties": {
                "a": {"type": "string"},
                "evidence_ids": {"type": "array", "items": {"type": "string"}},
                "confidence": {"type": "number"}
            }, 
            "required": ["a", "evidence_ids", "confidence"]
        }, f)
    
    (tmp_path / "templates").mkdir()
    with open(tmp_path / "templates" / "t.txt", "w") as f:
        f.write("Base Template\n{{INPUT_JSON}}\n{{EVIDENCE_LIST}}\n{{OUTPUT_SCHEMA}}")
        
    return tmp_path

def test_synthesis_auto_correct_schema(base_dir):
    run_dir = base_dir / "runs" / "r1"
    run_dir.mkdir(parents=True)
    
    tracer = Tracer(run_dir / "trace.jsonl", "r1")
    
    # Attempt 1 returns totally invalid JSON string
    # Attempt 2 returns valid JSON
    provider = MockProvider([
        "Not a json",
        json.dumps({
            "a": "valid",
            "evidence_ids": ["E1"],
            "confidence": 0.9
        })
    ])
    
    engine = SynthesisEngine(provider, tracer, base_dir, run_dir)
    
    params = {"strategy": {"max_attempts": 3}, "output_schema_ref": "schemas/out.json"}
    lock = {"template_path": "templates/t.txt", "output_schema_hash": "xxx"}
    
    out, pol = engine.synthesize("step_1", params, {}, [{"eid": "E1", "text": "foo", "source": "s", "locator": "l"}], {"preset": "enterprise_support_v1"}, lock)
    
    assert provider.call_count == 2
    
    # Check that attempt 2 prompt had the schema error reprompt
    assert "VALIDATION FAILURES FROM PREVIOUS ATTEMPT" in provider.prompts[1]
    assert "SCHEMA ERRORS:" in provider.prompts[1]
    assert "Not a json" not in provider.prompts[1] # the error from python is "Expecting value..."
    
    assert out["a"] == "valid"

def test_synthesis_max_attempts_exceeded(base_dir):
    run_dir = base_dir / "runs" / "r2"
    run_dir.mkdir(parents=True)
    tracer = Tracer(run_dir / "trace.jsonl", "r2")
    
    # Max attempts = 2, both invalid
    provider = MockProvider([
        "Not json 1",
        "Not json 2"
    ])
    
    engine = SynthesisEngine(provider, tracer, base_dir, run_dir)
    params = {"strategy": {"max_attempts": 2}, "output_schema_ref": "schemas/out.json"}
    lock = {"template_path": "templates/t.txt", "output_schema_hash": "xxx"}
    
    with pytest.raises(MaxAttemptsExceeded):
        engine.synthesize("step_1", params, {}, [], {"preset": "enterprise_support_v1"}, lock)
        
    assert provider.call_count == 2
