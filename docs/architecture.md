# Razi Architecture

## Overview

Razi separates three concerns that standard LLM wrappers conflate:

```
Specification → what must be true     (.aispec)
Synthesis     → what the model proposes (synth.json operator)
Authority     → what is allowed to execute (policy engine)
```

The policy engine is the **final arbiter**. It does not make recommendations. It overwrites the model's self-assessment. Every run produces a deterministic artifact set that is replayable offline without calling the model.

## Component Map

```
razi/
├── cli.py                   Entry points: validate, build, run, replay
├── spec/
│   ├── loader.py            YAML .aispec parser
│   └── validator.py         JSON Schema validation + hash computation
├── compiler/
│   └── compile.py           .aispec → immutable IR + DAG + lockfile
├── runtime/
│   ├── runtime.py           DAG execution engine
│   ├── evidence.py          Deterministic evidence index builder
│   ├── synthesis.py         Model synthesis state machine (retry logic)
│   ├── policy.py            Policy rule enforcement engine
│   └── trace.py             JSONL audit trail writer
├── replay/
│   ├── replay.py            Offline deterministic replay engine
│   └── store.py             Run artifact reader
└── providers/
    ├── base.py              Provider interface
    ├── openai_provider.py   OpenAI adapter
    └── ollama_provider.py   Local Ollama adapter (test mode)
```

## Execution Flow

```
razi run <spec> --input <file>
         │
         ▼
1. Load + Validate Input JSON against input_schema
         │
         ▼
2. evidence.index operator
   Builds a deterministic evidence index.
   Each piece of evidence gets a stable ID (E1, E2, ...).
   Lists → one item per element
   Dicts → one item per key (sorted alphabetically)
   Strings → one item
         │
         ▼
3. synth.json operator (attempt loop, max 3)
   a. Render prompt from template + {{INPUT_JSON}} + {{EVIDENCE_LIST}}
   b. Call model provider (OpenAI by default)
   c. Parse and validate JSON output against output_schema
   d. Check evidence IDs exist in the index
   e. Run policy engine against output
   f. If any failure: construct reprompt with specific failures and retry
   g. If all pass: continue
   h. If max attempts exhausted: raise MaxAttemptsExceeded → safe failure
         │
         ▼
4. Authoritative Merge
   policy_compliant = policy engine result (NOT model's self-report)
   violations = policy engine violations (NOT model's self-report)
         │
         ▼
5. Write final_output.json, trace.jsonl, replay artifacts
```

## Run Artifacts

Every run produces a fully self-contained artifact directory:

```
runs/<name>__<timestamp>__<hash>/
  input.json               Original input
  lock_snapshot.json       Build lockfile at time of run
  evidence_index.json      Deterministic evidence index
  attempts/
    attempt_1/
      prompt.txt           Exact prompt sent to model
      model_raw.txt        Raw model response
      parsed_model_output.json
      policy_eval.json
    attempt_N/ ...
  final_output.json        Final governed output
  policy_eval_final.json   Authoritative policy result
  status.json              SUCCESS or FAILURE
  trace.jsonl              Full event audit trail
  replay_report.json       Written by razi replay
```

## Determinism Contract

Given:
- The same `.aispec` (same spec hash and template hash in lockfile)
- The same `input.json`
- The same stored `model_raw.txt` artifacts

`razi replay` re-runs schema validation, evidence ID validation, and the policy engine — without calling the model — and verifies the result matches `final_output.json`. This is your audit proof.

## Policy Engine Design

Rules are evaluated **after** model synthesis, not inside the prompt. The prompt may instruct the model to follow rules, but the harness enforces them structurally regardless of what the model says. The model cannot "trick" the harness into passing a non-compliant output by claiming `policy_compliant: true` in its response — the runtime always overwrites those fields.
