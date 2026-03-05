from typing import Dict, Any

# --- Preset Registry ---
# Each entry maps a preset name to its default rule configuration.
# The policy engine (policy.py) is preset-agnostic — it just reads the rules dict.
# Add new presets here and register them in generate_policy().

_PRESETS: Dict[str, Dict[str, Any]] = {
    "enterprise_support_v1": {
        "preset": "enterprise_support_v1",
        "rules": {
            "evidence_required": {"enabled": True},
            "no_internal_disclosure": {
                "enabled": True,
                "sources": ["internal_notes"]
            },
            "min_confidence": {"enabled": True, "threshold": 0.6},
            "sla_escalation": {"enabled": True},
            "severity_downgrade_protection": {"enabled": True},
        }
    },
    # Future presets:
    # "hipaa_clinical_v1": { ... },
    # "financial_audit_v1": { ... },
}


def generate_policy(spec: Dict[str, Any]) -> Dict[str, Any]:
    """
    Generate the compiled policy configuration from a spec.

    The spec declares a preset by name (e.g. `policy: enterprise_support_v1`).
    This function expands the name to its full rule config using the preset registry.
    The policy engine itself is preset-agnostic — it evaluates whatever rules
    are present and enabled in the resulting config dict.
    """
    policy = spec["policy"]
    if isinstance(policy, str):
        if policy not in _PRESETS:
            known = ", ".join(_PRESETS.keys())
            raise ValueError(
                f"Unknown policy preset: '{policy}'. "
                f"Registered presets: {known}. "
                f"Add new presets to razi/compiler/policy_compile.py."
            )
        return dict(_PRESETS[policy])
    # Legacy object format — pass through unchanged (backwards compatibility)
    return policy
