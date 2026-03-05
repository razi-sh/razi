import json
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional
from jsonschema import validate, ValidationError

from .policy import evaluate_policy
from .trace import Tracer
from razi.providers.base import Provider

class MaxAttemptsExceeded(Exception):
    pass

class SynthesisEngine:
    def __init__(self, provider: Provider, tracer: Tracer, base_dir: Path, run_dir: Path):
        self.provider = provider
        self.tracer = tracer
        self.base_dir = base_dir
        self.run_dir = run_dir

    def synthesize(self, 
                   step_id: str,
                   params: Dict[str, Any], 
                   input_data: Dict[str, Any], 
                   evidence_index: List[Dict[str, Any]],
                   policy_config: Dict[str, Any],
                   lockfile: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """
        Executes the synthesis state machine with retry loops.
        Returns (parsed_json, policy_result).
        """
        strat = params.get("strategy", {})
        max_attempts = strat.get("max_attempts", 3)
        # Note: we must map this to actual path in runtime.py if lockfile.get("output_schema_hash") is needed later
        # Load output schema
        with open(self.base_dir / params["output_schema_ref"], "r") as f:
            output_schema = json.load(f)

        # Load Template
        template_path = self.base_dir / lockfile["template_path"]
        with open(template_path, "r") as f:
            base_template = f.read()

        attempts_dir = self.run_dir / "attempts"
        attempts_dir.mkdir(parents=True, exist_ok=True)

        schema_errors: List[str] = []
        evidence_errors: List[str] = []
        policy_violations: List[str] = []
        low_confidence = False

        self.tracer.step_start(step_id)

        for attempt in range(1, max_attempts + 1):
            self.tracer.attempt_start(step_id, attempt)
            
            attempt_dir = attempts_dir / f"attempt_{attempt}"
            attempt_dir.mkdir(exist_ok=True)

            # 1. Render Prompt
            prompt = self._render_prompt(
                base_template=base_template,
                input_data=input_data,
                evidence_index=evidence_index,
                output_schema=output_schema,
                schema_errors=schema_errors,
                evidence_errors=evidence_errors,
                policy_violations=policy_violations,
                low_confidence=low_confidence
            )
            
            prompt_file = attempt_dir / "prompt.txt"
            with open(prompt_file, "w") as f:
                f.write(prompt)
            self.tracer.artifact_written(step_id, attempt, str(prompt_file))

            # 2. Call Provider
            model_raw = self.provider.synthesize(
                prompt=prompt, 
                schema=output_schema, 
                model_config=lockfile
            )
            
            raw_file = attempt_dir / "model_raw.txt"
            with open(raw_file, "w") as f:
                f.write(model_raw)
            self.tracer.artifact_written(step_id, attempt, str(raw_file))

            # Reset tracking for this attempt
            schema_errors = []
            evidence_errors = []
            policy_violations = []
            low_confidence = False
            failures: List[str] = []
            parsed_json: Optional[Dict[str, Any]] = None

            # 3. Parse and Validate Schema
            try:
                parsed_json = json.loads(model_raw)
                validate(instance=parsed_json, schema=output_schema)
                
                with open(attempt_dir / "parsed_model_output.json", "w") as f:
                    json.dump(parsed_json, f, indent=2)
                self.tracer.artifact_written(step_id, attempt, str(attempt_dir / "parsed_model_output.json"))
                
            except json.JSONDecodeError as e:
                schema_errors.append(f"Output is not valid JSON: {str(e)}")
                failures.append("SCHEMA_FAILURE")
            except ValidationError as e:
                schema_errors.append(f"JSON does not match schema: {str(e)}")
                failures.append("SCHEMA_FAILURE")

            if parsed_json:
                # 4. Validate Evidence existence
                cited = parsed_json.get("evidence_ids", [])
                valid_ids = {e["eid"] for e in evidence_index}
                invalid = [eid for eid in cited if eid not in valid_ids]
                if invalid:
                    evidence_errors.append(f"You cited IDs that do NOT exist in the evidence index: {invalid}. You must remove them.")
                    failures.append("EVIDENCE_FAILURE")

                # 5. Policy Engine
                is_compliant, violations = evaluate_policy(
                    policy_config=policy_config,
                    input_data=input_data,
                    model_output=parsed_json,
                    evidence_index=evidence_index
                )
                
                policy_result = {
                    "compliant": is_compliant,
                    "violations": violations
                }
                with open(attempt_dir / "policy_eval.json", "w") as f:
                    json.dump(policy_result, f, indent=2)
                self.tracer.artifact_written(step_id, attempt, str(attempt_dir / "policy_eval.json"))
                self.tracer.policy_evaluated(step_id, attempt, is_compliant, violations)

                if not is_compliant:
                    policy_violations = violations
                    failures.append("POLICY_VIOLATION")

                # 6. Confidence Check (handled largely by policy, but we can flag it)
                threshold = policy_config.get("rules", {}).get("min_confidence", {}).get("threshold", 0.6)
                if parsed_json.get("confidence", 0.0) < threshold:
                    low_confidence = True
                    failures.append("LOW_CONFIDENCE")

            if failures:
                self.tracer.failure_classified(step_id, attempt, failures)
                self.tracer.attempt_end(step_id, attempt)
                # Loop continues to next attempt built on these failures
            else:
                self.tracer.attempt_end(step_id, attempt)
                self.tracer.step_end(step_id)
                return parsed_json or {}, policy_result

        # Exhausted
        self.tracer.step_end(step_id)
        raise MaxAttemptsExceeded("Maximum attempts exhausted without synthesizing a compliant output.")

    def _render_prompt(self, base_template: str, input_data: Dict, evidence_index: List[Dict], output_schema: Dict,
                      schema_errors: List[str], evidence_errors: List[str], policy_violations: List[str], low_confidence: bool) -> str:
        
        # Format evidence list
        ev_lines = []
        for e in evidence_index:
            ev_lines.append(f"- [{e['eid']}] ({e['source']} - {e['locator']}): {e['text']}")
        ev_str = "\n".join(ev_lines)
        
        p = base_template.replace("{{INPUT_JSON}}", json.dumps(input_data, indent=2))
        p = p.replace("{{EVIDENCE_LIST}}", ev_str)
        p = p.replace("{{OUTPUT_SCHEMA}}", json.dumps(output_schema, indent=2))
        
        # If there are failures from previous attempt, append the reprompt block
        if schema_errors or evidence_errors or policy_violations or low_confidence:
            reprompt = "\n=== VALIDATION FAILURES FROM PREVIOUS ATTEMPT ===\n\n"
            
            if schema_errors:
                reprompt += "SCHEMA ERRORS:\n" + "\n".join(schema_errors) + "\n\n"
                
            # If JSON is unparseable, do not include subsequent logical errors because they are meaningless
            if not any("not valid JSON" in e for e in schema_errors):
                if evidence_errors:
                    reprompt += "EVIDENCE ERRORS:\n" + "\n".join(evidence_errors) + "\n\n"
                if policy_violations:
                    reprompt += "POLICY VIOLATIONS:\n" + "\n".join(policy_violations) + "\n\n"
                if low_confidence:
                    reprompt += "LOW CONFIDENCE NOTICE:\nYour confidence score was too low. Provide stricter reasoning.\n\n"
                    
            reprompt += "You must correct ALL issues above in this response.\nReturn corrected JSON only."
            p += reprompt
            
        return p
