[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![CI](https://github.com/razi-sh/razi/actions/workflows/ci.yml/badge.svg)](https://github.com/razi-sh/razi/actions/workflows/ci.yml)
[![PyPI version](https://badge.fury.io/py/razi.svg)](https://pypi.org/project/razi/)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)

# Razi — Deterministic Governance Harness for AI Workflows

> The model proposes. The harness authorizes.

Razi wraps AI-driven reasoning inside a constraint-governed runtime that enforces schema compliance, policy rules, evidence traceability, and deterministic replay — for any workflow where the output must be trusted.

Standard LLM wrappers have no governance layer. Prompt engineering alone cannot guarantee that outputs are schema-valid, policy-compliant, and traceable. When AI makes a consequential decision, there is no audit trail and no way to prove what happened six months later.

Razi solves this by separating three concerns:

```
Specification → what must be true     (.aispec)
Synthesis     → what the model proposes (synth.json operator)
Authority     → what is allowed to execute (policy engine)
```

## Example Use Cases

Razi is a general-purpose governance harness. It is not limited to a single workflow type. Any AI task that requires deterministic, auditable, policy-enforced output is a good fit.

| Workflow | What Razi Governs |
|---|---|
| **Support Escalation** | SLA compliance, severity bounds, no internal note leakage, evidence-backed decisions |
| **Zendesk Troubleshooting** | Schema-valid troubleshooting plans with cited evidence from ticket history |
| **Customer Sentiment Analysis** | Structured, schema-validated sentiment output with retry on malformed responses |
| **Clinical Summarization** *(planned)* | HIPAA-compliant output with no PII disclosure, evidence-required citations |
| **Financial Decisions** *(planned)* | SOX-controlled decision outputs with full audit trail |

## Quick Start

```bash
pip install razi

export OPENAI_API_KEY=sk-...

# Clone and run the reference escalation workflow
git clone https://github.com/razi-sh/razi
cd razi

razi validate examples/escalation.aispec
razi build    examples/escalation.aispec
razi run      examples/escalation.aispec --input examples/inputs/sla_breach.json

# Replay the run offline (no model call)
razi replay   escalation_qualification__<run_id>
```

## How It Works

### 1. You write a `.aispec`
Declare your policy rules, model binding, evidence fields, and output schema. One file describes the entire governed workflow.

### 2. `razi build` compiles it deterministically
Produces an immutable IR + DAG + lockfile. The lockfile hashes the spec and template so every run is tied to an exact compiled state.

### 3. `razi run` enforces policy on every execution
- Builds a deterministic evidence index (every claim gets an evidence ID)
- Calls the model and validates the JSON output against your schema
- Checks every configured policy rule
- If any rule fails: constructs a targeted reprompt and retries
- If attempts are exhausted: fails safely — no non-compliant output passes
- Overwrites `policy_compliant` and `violations` — the model's self-assessment is never trusted

### 4. `razi replay` proves determinism
Re-evaluate schema, evidence, and policy offline, without hitting the model. This is your audit proof — run it against any historical `run_id`.

## Writing a Spec

A `.aispec` file describes your governed workflow in YAML:

```yaml
name: zendesk_troubleshooter
version: 1.0.0
policy: enterprise_support_v1

model:
  provider: openai
  id: gpt-4o-mini
  temperature: 0.1

input_schema:  examples/schemas/zendesk_input.json
output_schema: examples/schemas/zendesk_output.json

operators:
  - type: evidence.index
    id: evidence
    fields:
      - key: subject       source: input.subject
      - key: description   source: input.description
      - key: comments      source: input.injected_comments

  - type: synth.json
    id: synthesis
    evidence_ref: evidence
    template: examples/templates/zendesk_troubleshoot.txt
    max_attempts: 3
    confidence_threshold: 0.7
```

See [docs/spec_reference.md](docs/spec_reference.md) for the full format reference.

## Policy Presets

Razi governs AI output through **policy presets** — named rule bundles declared in one line of your `.aispec`:

```yaml
policy: enterprise_support_v1
```

The runtime enforces rules *after* the model responds. `policy_compliant` and `violations` are always written by the runtime — the model cannot self-certify. Each rule within a preset can be individually tuned per-workflow.

v1 ships with one preset: `enterprise_support_v1`. It covers 6 rules applicable to any workflow where AI decisions must be evidence-backed, bounded by severity constraints, and free of internal data leakage:

| Rule | What It Enforces |
|---|---|
| `evidence_required` | At least 1 valid evidence ID must be cited |
| `no_hallucinated_evidence` | Every cited ID must exist in the evidence index |
| `min_confidence` | AI confidence must meet configured threshold (default: 0.6) |
| `no_internal_disclosure` | Output cannot contain content from configured internal-only fields |
| `sla_escalation` | SLA breach → must recommend S1 or S2 *(support workflows)* |
| `severity_downgrade_protection` | S1 cannot be downgraded to S3/S4 *(incident management)* |

See [docs/policy_reference.md](docs/policy_reference.md) for per-rule documentation and how to add new presets.

## CLI Reference

```
razi validate <spec>              Validate .aispec syntax and schema links
razi build    <spec>              Compile to immutable build artifact
razi run      <spec> --input <f>  Execute with governance enforcement
razi replay   <run_id>            Replay offline — no model call
```

Run artifacts are written to:
```
runs/<name>__<timestamp>__<hash>/
  evidence_index.json
  attempts/
    attempt_1/ {prompt.txt, model_raw.txt, parsed_model_output.json, policy_eval.json}
    attempt_2/ ...
  final_output.json
  trace.jsonl
  replay_report.json
```

## Design Principles

**The runtime is the authority, not the model.** `policy_compliant` and `violations` are always set by the runtime. The model's self-assessment is overwritten. This is not optional.

**Determinism over flexibility.** v1 has exactly two operators, one policy preset, and one model provider. Generalization is explicitly deferred. Razi is a wedge, not a platform.

**Governance through structure, not prompting.** Rules are not embedded in prompts and hoped to be followed. They are compiled into the runtime and enforced structurally on every execution.

**Replay is not optional.** Every run is replayable offline. If your AI makes a consequential decision, you must be able to prove what happened six months later without calling the model again.

## What Razi Is Not (v1 Scope)

Razi v1 is intentionally minimal. The following are explicitly out of scope:

- Python SDK / programmatic API (Python is the substrate, not the product)
- UI / dashboard
- Branching, map/reduce, or multi-step DAG logic
- Multiple model providers
- Plugin system or general-purpose operators
- Streaming outputs

If you need these things, Razi is not the right tool yet. If you need deterministic governance on any AI workflow, it is.

## Roadmap

**v1.0 (Now)**
- `evidence.index` + `synth.json` operators
- `enterprise_support_v1` policy preset
- `razi build` / `validate` / `run` / `replay` CLI
- Deterministic run artifacts and offline replay
- Reference specs: escalation qualification, Zendesk troubleshooting, sentiment analysis

**v1.1**
- Additional example workflows
- Improved reprompt failure diagnostics
- Policy rule unit test harness

**v1.2**
- `hipaa_clinical_summary_v1` policy preset (in development)
- Second model provider (Anthropic)

**v2.0**
- Managed governance service (invite-only beta)
- Central spec registry + cross-team replay index

PRs welcome. See [CONTRIBUTING.md](CONTRIBUTING.md).
