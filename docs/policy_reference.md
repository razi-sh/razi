# Razi Policy System

## Overview

Razi enforces governance through **policy presets** — named bundles of rules registered in `razi/compiler/policy_compile.py`. When your `.aispec` declares:

```yaml
policy: enterprise_support_v1
```

The compiler looks up the preset name in the registry, expands it into a full rule config, and writes it to `build/policy.json`. At runtime, the policy engine reads that config and evaluates each enabled rule structurally — **the engine itself is preset-agnostic**. The preset name is just a label.

**Rules are not prompts.** The engine runs *after* the model responds and overwrites `policy_compliant` and `violations` — the model cannot self-certify compliance.

---

## Available Presets

### `enterprise_support_v1`

Designed for AI workflows that make consequential decisions about customer support cases — escalation qualification, troubleshooting plans, severity classification, etc.

Enables 5 hard rules by default. Any rule can be individually tuned per-spec.

---

## Rule Reference

### `evidence_required`
**Condition**: The model must cite at least one valid evidence ID from the run's evidence index.

**Applies to**: Any workflow where claims must be grounded in the input data (not hallucinated).

**Violation**: `"evidence_required: No evidence IDs cited."`

---

### `no_hallucinated_evidence`
**Condition**: Every ID in `evidence_ids` must exist in the current run's evidence index.

**Applies to**: All evidence-indexed workflows.

**Violation**: `"no_hallucinated_evidence: Cited IDs not in evidence index: [...]"`

---

### `min_confidence`
**Condition**: The model's self-reported `confidence` score must meet or exceed the configured threshold.

**Default threshold**: `0.6`

**Applies to**: Any workflow that requires the model to score its own confidence (e.g., classification, routing, triage).

**Violation**: `"min_confidence: <x> is below threshold <y>"`

---

### `no_internal_disclosure`
**Condition**: The output `justification` must not contain verbatim content from any field in `sources`.

**Applies to**: Workflows where AI output is customer-facing but informed by internal-only data.

**Configuration**:
```yaml
no_internal_disclosure:
  sources: [internal_notes, ops_comments]
```

**Violation**: `"no_internal_disclosure: Justification contains exact text from '<field>'."`

---

### `sla_escalation`
**Condition**: If `account_tier` is `enterprise` and `time_open_hours` exceeds `sla_hours`, the recommended severity must be `S1` or `S2`.

**Applies to**: Support escalation workflows with contractual SLA commitments.

**Violation**: `"sla_escalation: Enterprise SLA breach requires S1 or S2 severity."`

---

### `severity_downgrade_protection`
**Condition**: If `current_severity` is `S1`, the `recommended_severity` cannot be `S3` or `S4`.

**Applies to**: Incident management workflows where severity regression is a safety risk.

**Violation**: `"severity_downgrade_protection: Cannot downgrade an S1 to S3/S4."`

---

## Adding a New Preset

Add an entry to `_PRESETS` in `razi/compiler/policy_compile.py`:

```python
_PRESETS["my_workflow_v1"] = {
    "preset": "my_workflow_v1",
    "rules": {
        "evidence_required": {"enabled": True},
        "min_confidence": {"enabled": True, "threshold": 0.8},
        "no_internal_disclosure": {
            "enabled": True,
            "sources": ["private_data", "internal_comments"]
        },
        # Disable support-specific rules for non-support workflows:
        "sla_escalation": {"enabled": False},
        "severity_downgrade_protection": {"enabled": False},
    }
}
```

That's it. No changes to the policy engine are needed — it evaluates whatever rules are enabled in the config. Use the preset in your spec:

```yaml
policy: my_workflow_v1
```

See [CONTRIBUTING.md](../CONTRIBUTING.md) to submit new presets upstream.
