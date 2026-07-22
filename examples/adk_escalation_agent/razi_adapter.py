"""
Razi governance adapter for a Google ADK agent.

This module is the "Razi adapter" for the escalation triage agent in this
example folder: an ADK `before_tool_callback` / `after_tool_callback` pair
that intercepts the agent's proposed final decision, runs it through Razi's
*existing, unmodified* evidence-index and policy-evaluation engine
(`razi.evidence.run_evidence_index`, `razi.policy.evaluate_policy`,
`razi.policy.apply_authoritative_merge`), and on violation rejects the tool
call so the agent retries with the specific failures fed back as the tool's
own response.

This is Razi's single-shot reprompt loop
(`razi/runtime/synthesis.py:SynthesisEngine.synthesize`), transplanted onto
ADK's native tool-response feedback channel instead of prompt-string
splicing: in core Razi, a rejected attempt causes the harness to re-render a
prompt with a "VALIDATION FAILURES" block appended and call the model again.
Here, a rejected `submit_escalation_decision` call causes
`before_tool_callback` to return a dict (per ADK's callback contract, this
skips the real tool entirely and that dict *becomes* the tool's result) that
carries the same violations — the agent sees that as its tool's response and
retries by calling the tool again with corrected arguments, exactly as the
model does in core Razi's loop.

Every decision is recorded to `runs/<run_id>/` in Razi's existing run
artifact convention (see docs/architecture.md's "Run Artifacts" section) so
the stock `razi replay <run_id>` CLI command -- unmodified -- can replay an
agent's decision offline, with no model call. See README.md's "Known
Limitations" section for the couplings this relies on, in particular why
every attempt's `parsed_model_output.json` is written as the *merged*
output (model's proposal + harness's authoritative verdict) rather than the
model's raw proposal, which core Razi's own convention does not do.
"""
from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from jsonschema import validate as jsonschema_validate, ValidationError

from razi.evidence import run_evidence_index
from razi.policy import evaluate_policy, apply_authoritative_merge
from razi.runtime.trace import Tracer
from razi.spec.validator import hash_file

# ---------------------------------------------------------------------------
# Paths. REPO_ROOT is resolved from this file's location, not from process
# cwd, so `razi replay <run_id>` (which resolves `runs/` relative to *its*
# cwd) and this adapter always agree on where `runs/` lives when both are
# invoked from the repo root, and so this file works regardless of the
# caller's cwd.
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMAS_DIR = REPO_ROOT / "examples" / "schemas"
INPUT_SCHEMA_PATH = SCHEMAS_DIR / "escalation_input.schema.json"
OUTPUT_SCHEMA_PATH = SCHEMAS_DIR / "escalation_decision.schema.json"
TEMPLATE_PATH = Path(__file__).resolve().parent / "agent_instruction.txt"

# Repo-root-relative paths, as recorded in lock_snapshot.json -- these are
# what razi/replay/replay.py resolves against `base_dir` (the repo root).
TEMPLATE_REL_PATH = "examples/adk_escalation_agent/agent_instruction.txt"
INPUT_SCHEMA_REL_PATH = "examples/schemas/escalation_input.schema.json"
OUTPUT_SCHEMA_REL_PATH = "examples/schemas/escalation_decision.schema.json"

MAX_ATTEMPTS = 3
DECISION_TOOL_NAME = "submit_escalation_decision"
FETCH_TOOL_NAMES = {"get_ticket_context", "get_account_usage"}

# A literal copy of razi/compiler/policy_compile.py's
# `_PRESETS["enterprise_support_v1"]` rule set. Not re-derived via
# `generate_policy()` because that function expects a full `.aispec`-shaped
# spec dict, and this agent has no `.aispec` -- but the *rules themselves*
# are the real, unmodified enterprise_support_v1 preset, not a re-invention.
# This must be kept in sync with razi/compiler/policy_compile.py by hand if
# that preset's rules ever change (there is no import-time guard against
# drift -- see README.md's Known Limitations).
ENTERPRISE_SUPPORT_V1: Dict[str, Any] = {
    "preset": "enterprise_support_v1",
    "rules": {
        "evidence_required": {"enabled": True},
        "no_internal_disclosure": {"enabled": True, "sources": ["internal_notes"]},
        "min_confidence": {"enabled": True, "threshold": 0.6},
        "sla_escalation": {"enabled": True},
        "severity_downgrade_protection": {"enabled": True},
    },
}

# Evidence field spec, mirrors examples/escalation.aispec's evidence.index
# operator, with one correction: the shipped .aispec uses
# `source: input.customer_message` (singular) while the schema and every
# fixture use `customer_messages` (plural array) -- razi/runtime/evidence.py's
# `_resolve_source` silently returns None for the singular key against a
# plural-keyed input, so that field is dropped from the evidence index in
# the shipped reference example. We use the corrected plural key here. See
# README.md's Known Limitations section -- this is a pre-existing bug in
# examples/escalation.aispec, not something this adapter fixes upstream.
EVIDENCE_FIELDS: List[Dict[str, Any]] = [
    {"key": "customer_messages", "source": "input.customer_messages"},
    {"key": "account_tier", "source": "input.account_tier"},
    {"key": "current_severity", "source": "input.current_severity"},
    {"key": "sla_hours", "source": "input.sla_hours"},
    {"key": "time_open", "source": "input.time_open_hours"},
    {"key": "internal_notes", "source": "input.internal_notes", "governed": True},
]

# Registry of live RunRecorders keyed by run_id. Kept out of ADK session
# state deliberately: session state is meant to hold small, serializable
# values (and some session-service backends persist it), while a
# RunRecorder wraps open-ended filesystem paths and a Tracer. Only string
# identifiers go into `tool_context.state`; the heavyweight object lives
# here, process-local, for the lifetime of the run.
_RUN_RECORDERS: Dict[str, "RunRecorder"] = {}


def _load_json(path: Path) -> Dict[str, Any]:
    with open(path, "r") as f:
        return json.load(f)


def _derive_proposal_schema(decision_schema: Dict[str, Any]) -> Dict[str, Any]:
    """
    Derive the schema the agent's tool call is validated against: the full
    `escalation_decision.schema.json`, minus `policy_compliant`/`violations`.

    Per Razi's core design principle (razi/runtime/policy.py:
    apply_authoritative_merge), the model must never self-certify
    compliance -- only the harness may set those two fields. The
    `submit_escalation_decision` tool signature reflects that by not
    accepting them as parameters at all; this derived schema is what its
    arguments are validated against. Derived programmatically at import
    time (not hand-duplicated into a second schema file) so it can never
    silently drift from the real output schema.
    """
    proposal = copy.deepcopy(decision_schema)
    proposal["required"] = [
        k for k in proposal.get("required", [])
        if k not in ("policy_compliant", "violations")
    ]
    proposal.setdefault("properties", {})
    proposal["properties"].pop("policy_compliant", None)
    proposal["properties"].pop("violations", None)
    return proposal


_INPUT_SCHEMA = _load_json(INPUT_SCHEMA_PATH)
_OUTPUT_SCHEMA = _load_json(OUTPUT_SCHEMA_PATH)
_PROPOSAL_SCHEMA = _derive_proposal_schema(_OUTPUT_SCHEMA)


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


class RunRecorder:
    """
    Writes one agent decision to `runs/<run_id>/`, in exactly the artifact
    shape core Razi's `execute_run` (razi/runtime/runtime.py) produces, so
    the stock `razi replay <run_id>` CLI command can replay it offline,
    unmodified:

        runs/<run_id>/
          input.json, lock_snapshot.json, input_schema.json,
          output_schema.json, evidence_index.json,
          attempts/attempt_N/{prompt.txt, model_raw.txt,
                               parsed_model_output.json, policy_eval.json},
          final_output.json, policy_eval_final.json, status.json,
          trace.jsonl
    """

    def __init__(
        self,
        scenario_name: str,
        ticket_input_data: Dict[str, Any],
        output_base: Optional[Path] = None,
    ):
        self.scenario_name = scenario_name
        self.ticket_id = ticket_input_data.get("ticket_id", "unknown")
        output_base = output_base or REPO_ROOT
        utc = _utc_stamp()
        # input.json must hold the FULL merged ticket context, not just a
        # scenario/ticket_id stub -- razi/replay/replay.py's execute_replay
        # re-runs evaluate_policy() using exactly what it finds in
        # input.json, so anything less than the complete input Razi's
        # policy rules read (account_tier, sla_hours, internal_notes, ...)
        # would make replay's recomputed policy result silently diverge
        # from what was actually evaluated live.
        raw_input = json.dumps(ticket_input_data, sort_keys=True)
        short_hash = hashlib.sha256((raw_input + TEMPLATE_REL_PATH + utc).encode("utf-8")).hexdigest()[:8]
        self.run_id = f"{scenario_name}__{utc}__{short_hash}"
        self.run_dir = output_base / "runs" / self.run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.attempts_dir = self.run_dir / "attempts"
        self.attempts_dir.mkdir(exist_ok=True)

        with open(self.run_dir / "input.json", "w") as f:
            f.write(raw_input)

        template_hash = hash_file(TEMPLATE_PATH)
        input_hash = hash_file(INPUT_SCHEMA_PATH)
        output_hash = hash_file(OUTPUT_SCHEMA_PATH)
        # There is no .aispec for this agent, so there's no real spec to
        # hash. This is a stable hash of the agent's own governing
        # configuration (policy preset + template identity) -- a synthetic
        # but genuine fingerprint, not a placeholder constant.
        spec_hash = hashlib.sha256(
            json.dumps(
                {
                    "name": "escalation_agent",
                    "policy": "enterprise_support_v1",
                    "template": TEMPLATE_REL_PATH,
                },
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()

        self.lock: Dict[str, Any] = {
            "model": "gemini-2.5-flash",
            "temperature": None,
            "provider": "google-adk",
            "template_path": TEMPLATE_REL_PATH,
            "template_sha256": template_hash,
            "spec_hash": spec_hash,
            "input_schema_hash": input_hash,
            "output_schema_hash": output_hash,
            "input_schema_path": INPUT_SCHEMA_REL_PATH,
            "output_schema_path": OUTPUT_SCHEMA_REL_PATH,
        }
        with open(self.run_dir / "lock_snapshot.json", "w") as f:
            json.dump(self.lock, f, indent=2)

        # Persisted schema copies -- razi/replay/replay.py's
        # _resolve_output_schema() prefers these over live-file lookup, and
        # input_schema.json is written for parity with core's convention
        # even though replay.py never reads it back (only output_schema_hash
        # / output_schema.json are actually used during replay).
        for src, name in (
            (INPUT_SCHEMA_PATH, "input_schema.json"),
            (OUTPUT_SCHEMA_PATH, "output_schema.json"),
        ):
            with open(src, "r") as sf, open(self.run_dir / name, "w") as df:
                df.write(sf.read())

        self.tracer = Tracer(self.run_dir / "trace.jsonl", self.run_id)
        self.tracer.step_start("evidence")
        self._evidence_step_closed = False

    def write_evidence_index(self, evidence_index: List[Dict[str, Any]]) -> None:
        with open(self.run_dir / "evidence_index.json", "w") as f:
            json.dump(evidence_index, f, indent=2)
        self.tracer.artifact_written("evidence", None, str(self.run_dir / "evidence_index.json"))
        if not self._evidence_step_closed:
            self.tracer.step_end("evidence")
            self.tracer.step_start("synthesis")
            self._evidence_step_closed = True

    def write_attempt(
        self,
        attempt: int,
        effective_prompt: str,
        proposed_args: Dict[str, Any],
        merged_output: Dict[str, Any],
        policy_result: Dict[str, Any],
        failures: List[str],
    ) -> None:
        attempt_dir = self.attempts_dir / f"attempt_{attempt}"
        attempt_dir.mkdir(exist_ok=True)
        self.tracer.attempt_start("synthesis", attempt)

        with open(attempt_dir / "prompt.txt", "w") as f:
            f.write(effective_prompt)
        self.tracer.artifact_written("synthesis", attempt, str(attempt_dir / "prompt.txt"))

        with open(attempt_dir / "model_raw.txt", "w") as f:
            f.write(json.dumps(proposed_args))
        self.tracer.artifact_written("synthesis", attempt, str(attempt_dir / "model_raw.txt"))

        # NB: written as the *merged* (proposal + authoritative verdict)
        # output on every attempt, not the model's raw self-report -- see
        # module docstring and README.md's Known Limitations.
        with open(attempt_dir / "parsed_model_output.json", "w") as f:
            json.dump(merged_output, f, indent=2)
        self.tracer.artifact_written("synthesis", attempt, str(attempt_dir / "parsed_model_output.json"))

        with open(attempt_dir / "policy_eval.json", "w") as f:
            json.dump(policy_result, f, indent=2)
        self.tracer.artifact_written("synthesis", attempt, str(attempt_dir / "policy_eval.json"))
        self.tracer.policy_evaluated("synthesis", attempt, policy_result["compliant"], policy_result["violations"])

        if failures:
            self.tracer.failure_classified("synthesis", attempt, failures)
        self.tracer.attempt_end("synthesis", attempt)

    def finalize_success(self, final_output: Dict[str, Any], policy_result: Dict[str, Any]) -> None:
        with open(self.run_dir / "policy_eval_final.json", "w") as f:
            json.dump(policy_result, f, indent=2)
        with open(self.run_dir / "final_output.json", "w") as f:
            json.dump(final_output, f, indent=2)
        with open(self.run_dir / "status.json", "w") as f:
            json.dump({"status": "SUCCESS"}, f)
        self.tracer.step_end("synthesis")

    def finalize_failure(self, reason: str) -> None:
        with open(self.run_dir / "status.json", "w") as f:
            json.dump({"status": "FAILURE", "reason": reason}, f)
        self.tracer.step_end("synthesis")


class RaziGovernor:
    """
    ADK callback pair that makes Razi the governance layer for an agent's
    tool calls. Register `before_tool_callback` / `after_tool_callback` on
    the `LlmAgent` (see agent.py).

    All mutable state (attempt counters, cached ticket context and evidence
    index, the pending run_id, and a `razi_closed` fail-safe flag once
    `max_attempts` is exhausted) lives in `tool_context.state`, keyed by
    string. `RaziGovernor` itself holds no per-invocation instance state, so
    a single instance is safe to reuse across agent invocations and
    scenarios within one process.
    """

    def __init__(self, scenario_name: str = "escalation_agent", max_attempts: int = MAX_ATTEMPTS):
        self.scenario_name = scenario_name
        self.max_attempts = max_attempts

    # ------------------------------------------------------------------
    # before_tool_callback(tool, args, tool_context) -> Optional[dict]
    #   None            -> real tool executes with these args
    #   dict            -> real tool is SKIPPED; this dict becomes the
    #                      tool's result, which the model sees as the
    #                      response to its own tool call
    # ------------------------------------------------------------------
    def before_tool_callback(self, tool, args: Dict[str, Any], tool_context) -> Optional[Dict[str, Any]]:
        name = getattr(tool, "name", str(tool))

        if name != DECISION_TOOL_NAME:
            # Fetch tools (get_ticket_context, get_account_usage) are
            # read-only and ungoverned -- analogous to Razi's evidence.index
            # operator, which also isn't subject to the retry loop.
            return None

        state = tool_context.state

        if state.get("razi_closed"):
            return {
                "status": "REJECTED_FINAL",
                "message": (
                    "Governance already closed this ticket after exhausting "
                    "max attempts. No further escalation decisions will be "
                    "authorized for this invocation."
                ),
            }

        ticket_input_data = state.get("razi_ticket_input_data")
        if not ticket_input_data:
            return {
                "status": "REJECTED",
                "attempt": 0,
                "violations": ["evidence_required: No ticket context gathered yet."],
                "instruction": (
                    "Call get_ticket_context and get_account_usage first, "
                    "then retry submit_escalation_decision."
                ),
            }

        attempt = int(state.get("razi_attempt", 0)) + 1
        state["razi_attempt"] = attempt

        recorder = self._get_recorder(state, ticket_input_data)

        evidence_index = state.get("razi_evidence_index")
        if evidence_index is None:
            evidence_index = run_evidence_index(ticket_input_data, EVIDENCE_FIELDS)
            state["razi_evidence_index"] = evidence_index
            recorder.write_evidence_index(evidence_index)

        failures: List[str] = []
        schema_errors: List[str] = []
        evidence_errors: List[str] = []

        try:
            jsonschema_validate(instance=args, schema=_PROPOSAL_SCHEMA)
        except ValidationError as e:
            schema_errors.append(f"Output does not match schema: {e.message}")
            failures.append("SCHEMA_FAILURE")

        cited = args.get("evidence_ids", [])
        cited = cited if isinstance(cited, list) else []
        valid_ids = {e["eid"] for e in evidence_index}
        invalid = [eid for eid in cited if eid not in valid_ids]
        if invalid:
            evidence_errors.append(f"Cited evidence IDs that do not exist: {invalid}")
            failures.append("EVIDENCE_FAILURE")

        # The same evaluate_policy() Razi's own synth.json operator calls
        # (razi/runtime/synthesis.py) -- unmodified, imported directly.
        compliant, violations = evaluate_policy(
            policy_config=ENTERPRISE_SUPPORT_V1,
            input_data=ticket_input_data,
            model_output=args,
            evidence_index=evidence_index,
        )
        if not compliant:
            failures.append("POLICY_VIOLATION")

        merged_output = apply_authoritative_merge(args, compliant, violations)
        policy_result = {"compliant": compliant, "violations": violations}
        all_violations = schema_errors + evidence_errors + violations

        recorder.write_attempt(
            attempt=attempt,
            effective_prompt=self._render_effective_prompt(ticket_input_data, evidence_index, attempt, all_violations),
            proposed_args=args,
            merged_output=merged_output,
            policy_result=policy_result,
            failures=failures,
        )

        if failures:
            if attempt >= self.max_attempts:
                recorder.finalize_failure("MAX_ATTEMPTS_EXCEEDED")
                state["razi_closed"] = True
                return {
                    "status": "REJECTED_FINAL",
                    "attempt": attempt,
                    "violations": all_violations,
                    "message": (
                        "Maximum attempts exhausted. Escalation NOT "
                        "authorized -- the harness is refusing to authorize "
                        "a non-compliant decision."
                    ),
                    "run_id": recorder.run_id,
                }
            return {
                "status": "REJECTED",
                "attempt": attempt,
                "violations": all_violations,
                "instruction": (
                    "Fix ALL issues above and call submit_escalation_decision "
                    "again with corrected values."
                ),
            }

        recorder.finalize_success(merged_output, policy_result)
        state["razi_final_output"] = merged_output
        state["razi_run_id"] = recorder.run_id
        return None  # compliant -- let the real tool execute

    # ------------------------------------------------------------------
    # after_tool_callback(tool, args, tool_context, tool_response)
    #   None -> the LLM sees the real tool's response unchanged
    #   dict -> the LLM sees this dict instead
    # ------------------------------------------------------------------
    def after_tool_callback(
        self, tool, args: Dict[str, Any], tool_context, tool_response: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        name = getattr(tool, "name", str(tool))
        state = tool_context.state

        if name in FETCH_TOOL_NAMES:
            merged = dict(state.get("razi_ticket_input_data") or {})
            merged.update(tool_response)
            state["razi_ticket_input_data"] = merged
            return None

        if name == DECISION_TOOL_NAME:
            final_output = state.get("razi_final_output")
            if final_output is not None:
                # Only reached when before_tool_callback returned None
                # (compliant), so the real tool actually ran.
                modified = dict(tool_response)
                modified["status"] = "ACCEPTED"
                modified["run_id"] = state.get("razi_run_id")
                modified["final_output"] = final_output
                modified["replay_hint"] = f"razi replay {state.get('razi_run_id')}"
                return modified
            return None

        return None

    # ------------------------------------------------------------------
    def _get_recorder(self, state, ticket_input_data: Dict[str, Any]) -> RunRecorder:
        pending_id = state.get("razi_run_id_pending")
        if pending_id and pending_id in _RUN_RECORDERS:
            return _RUN_RECORDERS[pending_id]
        recorder = RunRecorder(self.scenario_name, ticket_input_data)
        _RUN_RECORDERS[recorder.run_id] = recorder
        state["razi_run_id_pending"] = recorder.run_id
        return recorder

    @staticmethod
    def _render_effective_prompt(
        ticket_input_data: Dict[str, Any],
        evidence_index: List[Dict[str, Any]],
        attempt: int,
        violations: List[str],
    ) -> str:
        """
        Reconstructs a human-readable snapshot of "what the agent had to
        work with" for this attempt -- modeled closely on
        razi/runtime/synthesis.py's `_render_prompt`, for continuity with
        core Razi's audit artifacts, even though ADK is actually delivering
        the retry feedback natively via the tool-response channel rather
        than by literally re-sending this text as a prompt.
        """
        base = TEMPLATE_PATH.read_text()
        ev_lines = [f"- [{e['eid']}] ({e['source']} - {e['locator']}): {e['text']}" for e in evidence_index]
        prompt = base
        prompt += "\n=== TICKET INPUT (gathered via tool calls) ===\n" + json.dumps(ticket_input_data, indent=2)
        prompt += "\n=== EVIDENCE INDEX ===\n" + "\n".join(ev_lines)
        if attempt > 1 and violations:
            prompt += "\n\n=== VALIDATION FAILURES FROM PREVIOUS ATTEMPT ===\n" + "\n".join(violations)
            prompt += "\nYou must correct ALL issues above in this response.\n"
        return prompt
