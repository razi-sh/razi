# .aispec Format Reference

## Overview

The `.aispec` file is the core interface for defining Razi governance workflows. It declares:
- Which model to use
- What input/output schemas define the data contract
- What policy preset to enforce
- What workflow operators to execute

## Minimal Valid Spec

```yaml
name: my_workflow
version: "1.0"

models:
  reasoning:
    provider: openai
    model: gpt-4o
    temperature: 0.2

input_schema: schemas/input.schema.json
output_schema: schemas/output.schema.json
template: templates/my_prompt.txt

policy:
  preset: enterprise_support_v1
  rules:
    sla_escalation: { enabled: true }
    no_internal_disclosure:
      enabled: true
      sources: [internal_notes]
    evidence_required: { enabled: true }
    severity_downgrade_protection: { enabled: true }
    min_confidence:
      enabled: true
      threshold: 0.6

workflow:
  - id: build_evidence
    op: evidence.index
    with:
      from:
        - customer_messages
        - internal_notes

  - id: synthesize
    op: synth.json
    with:
      output_schema_ref: output
      evidence_ref: build_evidence
      strategy:
        max_attempts: 3

verify:
  schema: true
  policy: true
  evidence_ids_exist: true
  deterministic_replay: true
```

## Fields

| Field | Type | Required | Description |
|---|---|---|---|
| `name` | string | ✅ | Unique identifier for the workflow. Used for run directory naming. |
| `version` | string | ✅ | Must be `"1.0"`. |
| `models.reasoning.provider` | string | ✅ | Model provider. Currently supports `openai`. |
| `models.reasoning.model` | string | ✅ | Model identifier (e.g., `gpt-4o`). |
| `models.reasoning.temperature` | number | ✅ | Sampling temperature (0.0–1.0). |
| `input_schema` | path | ✅ | Path to JSON Schema file for input validation. |
| `output_schema` | path | ✅ | Path to JSON Schema file for output validation. |
| `template` | path | ✅ | Path to the prompt template file. |
| `policy.preset` | string | ✅ | Policy preset name. Use `enterprise_support_v1`. |
| `workflow` | array | ✅ | Ordered list of operator nodes to execute. |
| `verify` | object | ✅ | Verification configuration. |

## Operators

### `evidence.index`
Builds a deterministic evidence index from input fields.

```yaml
op: evidence.index
with:
  from:
    - customer_messages
    - internal_notes
```

`from` accepts any top-level field name from the input JSON. Lists are expanded to individual evidence items. Objects are expanded key-by-key (sorted alphabetically for determinism). Strings are added as a single evidence item.

### `synth.json`
Invokes the model with a governed synthesis state machine.

```yaml
op: synth.json
with:
  output_schema_ref: output
  evidence_ref: build_evidence
  strategy:
    max_attempts: 3
```

## Template Variables

Inside your prompt template file, use these variables:

| Variable | Description |
|---|---|
| `{{INPUT_JSON}}` | Full JSON-serialized input data |
| `{{EVIDENCE_LIST}}` | Formatted evidence index with IDs |
| `{{OUTPUT_SCHEMA}}` | Full JSON schema of the expected output |
