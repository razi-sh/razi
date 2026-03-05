from typing import Dict, Any, List, Tuple


def evaluate_policy(
    policy_config: Dict[str, Any],
    input_data: Dict[str, Any],
    model_output: Dict[str, Any],
    evidence_index: List[Dict[str, Any]]
) -> Tuple[bool, List[str]]:
    """
    Evaluates configured policy rules against the model's output.

    The engine is preset-agnostic — it evaluates whatever rules are present
    in `policy_config["rules"]` and enabled. The preset name is informational only.

    Returns (is_compliant, list_of_violations).
    """
    rules = policy_config.get("rules", {})
    violations: List[str] = []

    # --- evidence_required ---
    if rules.get("evidence_required", {}).get("enabled"):
        cited_ids = model_output.get("evidence_ids", [])
        if not cited_ids:
            violations.append("evidence_required: No evidence IDs cited.")
        else:
            valid_ids = {e["eid"] for e in evidence_index}
            invalid = [eid for eid in cited_ids if eid not in valid_ids]
            if invalid:
                violations.append(
                    f"evidence_required: Cited non-existent evidence IDs: {invalid}"
                )

    # --- no_hallucinated_evidence (always on when evidence index is non-empty) ---
    cited_all = model_output.get("evidence_ids", [])
    if cited_all and evidence_index:
        valid_ids = {e["eid"] for e in evidence_index}
        hallucinated = [eid for eid in cited_all if eid not in valid_ids]
        if hallucinated:
            violations.append(
                f"no_hallucinated_evidence: Cited IDs not in evidence index: {hallucinated}"
            )

    # --- min_confidence ---
    min_conf_rule = rules.get("min_confidence", {})
    if min_conf_rule.get("enabled"):
        threshold = min_conf_rule.get("threshold", 0.6)
        conf = model_output.get("confidence", 0.0)
        if conf < threshold:
            violations.append(
                f"min_confidence: {conf} is below threshold {threshold}"
            )

    # --- no_internal_disclosure ---
    no_disclosure = rules.get("no_internal_disclosure", {})
    if no_disclosure.get("enabled"):
        justification = model_output.get("justification", "")
        sources = no_disclosure.get("sources", ["internal_notes"])
        for source_field in sources:
            source_data = input_data.get(source_field)
            if not source_data:
                continue
            items = source_data if isinstance(source_data, list) else [str(source_data)]
            for item in items:
                if item and item in justification:
                    violations.append(
                        f"no_internal_disclosure: Justification contains exact text "
                        f"from '{source_field}'."
                    )
                    break

    # --- sla_escalation ---
    if rules.get("sla_escalation", {}).get("enabled"):
        is_enterprise = input_data.get("account_tier") == "enterprise"
        time_open = input_data.get("time_open_hours", 0)
        sla = input_data.get("sla_hours", 9999)
        if is_enterprise and time_open > sla:
            rec_sev = model_output.get("recommended_severity")
            if rec_sev not in ["S1", "S2"]:
                violations.append(
                    "sla_escalation: Enterprise SLA breach requires S1 or S2 severity."
                )

    # --- severity_downgrade_protection ---
    if rules.get("severity_downgrade_protection", {}).get("enabled"):
        if input_data.get("current_severity") == "S1":
            rec_sev = model_output.get("recommended_severity")
            if rec_sev in ["S3", "S4"]:
                violations.append(
                    "severity_downgrade_protection: Cannot downgrade an S1 to S3/S4."
                )

    return len(violations) == 0, violations


def apply_authoritative_merge(
    model_output: Dict[str, Any],
    compliant: bool,
    violations: List[str]
) -> Dict[str, Any]:
    """
    Overwrites the model's self-assessed compliance fields with the actual engine result.
    The model's own policy_compliant and violations values are never trusted.
    """
    final_output = dict(model_output)
    final_output["policy_compliant"] = compliant
    final_output["violations"] = violations
    return final_output
