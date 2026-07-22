# ADK Escalation Agent, governed by Razi

A small Google [Agent Development Kit](https://google.github.io/adk-docs/) (ADK) agent, backed by Gemini,
with three tools, where **Razi is the governance layer** -- not a wrapper around the whole agent, a callback
on the one tool call that matters.

Everything else in this repo governs single-shot LLM calls: one `.aispec` compiles to an
`evidence.index` -> `synth.json` pipeline, and `razi run` retries the model with a targeted
reprompt until the output is schema-valid, evidence-backed, and policy-compliant (see the root
[README](../../README.md) and [docs/architecture.md](../../docs/architecture.md)). This example shows the
same governance model applied to an **agent**: the reprompt loop is transplanted from a manual
prompt-string splice onto ADK's native tool-response feedback channel, and every decision is still
recorded so that the stock `razi replay <run_id>` command -- completely unmodified -- can replay it
offline, with no model call.

## What it does

The agent triages a support ticket into an escalation severity recommendation:

1. `get_ticket_context(ticket_id)` -- fetches customer messages, current severity, SLA terms, and
   internal notes (read-only, ungoverned).
2. `get_account_usage(ticket_id)` -- fetches usage metrics, open incidents, contract value
   (read-only, ungoverned).
3. `submit_escalation_decision(recommended_severity, confidence, evidence_ids, justification)` --
   the one consequential action. **Every call to this tool is intercepted by Razi before it is
   allowed to execute.**

The governed tool reuses Razi's actual policy preset, `enterprise_support_v1`
([razi/compiler/policy_compile.py](../../razi/compiler/policy_compile.py)): evidence must be cited and
real, confidence must clear 0.6, internal notes must never be disclosed, enterprise SLA breaches must be
escalated to S1/S2, and S1 tickets can't be quietly downgraded.

## Architecture

```mermaid
sequenceDiagram
    participant U as User
    participant A as ADK LlmAgent (Gemini)
    participant F as get_ticket_context / get_account_usage
    participant G as RaziGovernor (before/after_tool_callback)
    participant R as Razi core (run_evidence_index, evaluate_policy)
    participant D as runs/&lt;run_id&gt;/ (RunRecorder)

    U->>A: "Triage ticket TCK-1001"
    A->>F: call fetch tools
    F-->>G: after_tool_callback caches merged ticket context
    A->>G: before_tool_callback(submit_escalation_decision, args)
    G->>R: run_evidence_index(...) + evaluate_policy(...)
    alt violation
        R-->>G: (False, violations)
        G-->>A: return {status: REJECTED, violations} (real tool never runs)
        A->>G: retries submit_escalation_decision with corrected args
    else compliant
        R-->>G: (True, [])
        G->>D: write final_output.json / policy_eval_final.json / status.json
        G-->>A: return None (real tool executes)
    end
    D-->>U: runs/&lt;run_id&gt;/ ... replayable via `razi replay &lt;run_id&gt;` (no model call)
```

The mechanism that makes this work is ADK's `before_tool_callback` contract: returning `None` lets the
real tool execute with the given (or modified) arguments; **returning a dict skips the real tool entirely,
and that dict becomes the tool's result** -- which the model sees as the response to its own tool call.
`RaziGovernor` ([razi_adapter.py](razi_adapter.py)) uses exactly this to reject a non-compliant decision
without ever executing it, feeding the specific violations back as the tool's response so the agent
naturally retries. This is Razi's reprompt loop
([razi/runtime/synthesis.py](../../razi/runtime/synthesis.py)'s `SynthesisEngine.synthesize`), which
normally works by re-rendering a prompt with a `VALIDATION FAILURES` block appended -- here the same
failures ride ADK's tool-response channel instead.

## Files

| File | Role |
|---|---|
| `agent.py` | The ADK `Agent`: 3 tools, Gemini model, wires `RaziGovernor` in as callbacks |
| `razi_adapter.py` | **The Razi adapter.** `RaziGovernor` (the governance gate) + `RunRecorder` (artifact writer) |
| `agent_instruction.txt` | The agent's system instruction. Also the hashed "template" for replay's drift check |
| `fixtures/tickets.json` | Two mock tickets: one clean SLA-breach case, one red-team leak-bait case |
| `run_demo.py` | CLI: `python run_demo.py --scenario {clean,redteam_leak}` |
| `tests/test_adapter_offline.py` | Offline proof: reject -> reject -> accept -> `razi replay` PASS, no network |
| `demo/demo.html` | A scripted ~60s terminal-cast of a run (see "Demo clip" below) |

## Setup

From the **repo root**:

```bash
pip install -e .
pip install -r examples/adk_escalation_agent/requirements.txt
export GOOGLE_API_KEY=...   # Gemini Developer API key; see ADK docs for the Vertex AI alternative
```

## Running it

```bash
python examples/adk_escalation_agent/run_demo.py --scenario clean
python examples/adk_escalation_agent/run_demo.py --scenario redteam_leak
```

- `clean` triages an enterprise ticket that has genuinely breached its SLA. A well-behaved agent should
  reach a compliant decision quickly.
- `redteam_leak` triages a ticket whose internal notes contain a sensitive admission, paired with a
  user prompt that nudges the agent toward "full transparency" -- baiting it into quoting the internal
  note verbatim in the customer-facing justification (mirrors the `_redteam_leak` convention in
  [demo_scenarios/](../../demo_scenarios/)). Expect at least one rejected attempt for
  `no_internal_disclosure`, followed by either a corrected acceptance or, if the model keeps disobeying
  past `max_attempts`, a final safe rejection -- that refusal *is* the demo, not a bug.

Each run prints the tool calls, the agent's final message, and the run it recorded:

```
Run recorded: runs/<run_id>/
Replay it offline (from the repo root, no model call):
  razi replay <run_id>
```

### Replaying, offline, with the stock CLI

```bash
razi replay <run_id>
```

This is the **exact, unmodified** `razi` CLI command used everywhere else in this repo. It works
here because `RunRecorder` writes the agent's decision into the same artifact shape
`razi run` produces (see [docs/architecture.md](../../docs/architecture.md)'s "Run Artifacts" section):
`input.json`, `lock_snapshot.json`, `evidence_index.json`,
`attempts/attempt_N/{prompt.txt, model_raw.txt, parsed_model_output.json, policy_eval.json}`,
`final_output.json`, `policy_eval_final.json`, `status.json`, `trace.jsonl`. `razi replay` re-derives the
policy/evidence/schema result from those files with no model call and writes `replay_report.json`.

A pre-recorded reference run is checked into `runs/escalation_agent_redteam_leak__.../` so you can inspect
the artifact tree and run `razi replay` on it without installing anything or setting an API key. It was
generated by driving `RaziGovernor` directly with fixed, scripted tool-call arguments (the same technique
`tests/test_adapter_offline.py` uses) rather than a live Gemini call, since this environment had no
`GOOGLE_API_KEY` available when the example was built -- it is not a real agent trajectory, just a
realistic one, and is labeled as such. Run `run_demo.py` yourself with a real key to generate a live one.

### Offline test (no network, no API key)

```bash
pytest examples/adk_escalation_agent/tests/test_adapter_offline.py -v
```

Drives `RaziGovernor` directly through a reject -> reject -> accept sequence with fabricated
`tool`/`tool_context` objects, and asserts the recorded run replays clean via Razi's own
`execute_replay`. This is deliberately **not** under the repo's top-level `tests/` directory -- see
Known Limitations.

## Demo clip

`demo/demo.html` is a self-contained, dependency-free animated HTML page that types out a ~60 second
terminal transcript of a run: tool calls, a rejected attempt with its violations, a corrected retry,
acceptance, the run directory being written, and a `razi replay` PASS. This follows the same convention
the root of this repo already uses for demo clips
([razi_demo.html](../../razi_demo.html) is a scripted terminal-cast, not a screen recording) -- open it in
any browser, no server or build step required.

## Known Limitations

- **Evidence citations are checked for existence, not for support.** `evaluate_policy`'s
  `evidence_required`/`no_hallucinated_evidence` rules only verify that a cited `evidence_id` exists in
  the evidence index -- they never check that the evidence at that ID actually supports the specific
  claim it's attached to. This is a real, observed failure, not a hypothetical: in an early live run
  against Gemini, the agent cited a real evidence ID (`E2`, a customer message asking about an unrelated
  billing question) as support for a claim about error rate and open-incident count, and Razi accepted
  it, because `E2` genuinely existed in the index and the rule stops there. The immediate cause was
  `EVIDENCE_FIELDS` not indexing `usage_metrics`/`open_incidents`/`contract_value` at all, so those facts
  had no real citable ID to begin with -- fixed below by indexing them. But that only narrows the
  fabrication surface; it doesn't close it, since nothing stops an agent from citing a *real*,
  *existing*, but *wrong* evidence ID for a given claim. Closing that fully needs an entailment check
  (does the cited text actually say what the justification claims) that core Razi does not have in v1 --
  this example is evidence that it's worth adding, not something this adapter can safely paper over on
  its own.
- **`razi replay`'s policy re-evaluation is hardcoded, not read from the run.** `razi/replay/replay.py`
  re-runs `evaluate_policy` using a synthetic copy of the `enterprise_support_v1` rule set it constructs
  inline, rather than reading whatever policy config was actually used to produce the run. This is a
  no-op today because it's the only preset that exists and this adapter uses it unmodified -- but it's a
  pre-existing, repo-wide limitation (it affects every example and demo scenario, not just this one), not
  something this example works around or fixes.
- **`parsed_model_output.json` is always the *merged* output, not the model's raw self-report.** Core
  Razi's own `synth.json` operator writes the model's raw JSON (including its own, discarded,
  self-reported `policy_compliant`/`violations`) to `parsed_model_output.json`. Here, the
  `submit_escalation_decision` tool signature never accepts those two fields at all (the model must never
  self-certify), so every attempt's `parsed_model_output.json` is written as
  `apply_authoritative_merge(args, compliant, violations)` instead -- the proposed fields plus the
  harness's actual verdict. This is necessary for `razi replay`'s schema re-validation to pass (the output
  schema requires those fields), and is arguably more honest than core's convention, but it does mean a
  byte-for-byte diff against a `demo_scenarios/` run's `parsed_model_output.json` will look structurally
  different.
- **The evidence field spec corrects a bug in, and gap in, `examples/escalation.aispec`.** The shipped
  spec's `evidence.index` operator uses `source: input.customer_message` (singular), but the schema and
  every fixture use `customer_messages` (plural array) -- `razi/runtime/evidence.py`'s `_resolve_source`
  silently drops that field as a result. It also never indexes `usage_metrics`/`open_incidents`/
  `contract_value` at all. `razi_adapter.py`'s `EVIDENCE_FIELDS` uses the corrected plural key and adds
  the missing fields (see the bullet above for why the latter mattered in practice). This example does
  not patch the shipped `.aispec` itself; that's a separate, out-of-scope core fix.
- **This is a new "one folder, self-contained" example convention.** `examples/` and `demo_scenarios/`
  elsewhere in this repo are flat (shared `schemas/`/`templates/`/`inputs/` directories across all
  scenarios). An agentic example has runtime code, a governance adapter, and fixtures that don't fit that
  shape, so it lives in its own folder instead.
- **No core `razi/` files were modified.** Everything here imports Razi as a library
  (`razi.evidence.run_evidence_index`, `razi.policy.evaluate_policy`, `razi.policy.apply_authoritative_merge`,
  `razi.runtime.trace.Tracer`), consistent with [CONTRIBUTING.md](../../CONTRIBUTING.md)'s v1 scope (no new
  providers/operators in core).
