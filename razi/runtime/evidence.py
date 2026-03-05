from typing import Dict, Any, List, Union


def _resolve_source(source: str, input_data: Dict[str, Any]) -> Any:
    """
    Resolve a `source` dotted path like `input.customer_message` against input_data.
    Only `input.*` sources are supported in v1.
    """
    if source.startswith("input."):
        key = source[len("input."):]
        return input_data.get(key)
    # Fallback: treat as a top-level key
    return input_data.get(source)


def run_evidence_index(
    input_data: Dict[str, Any],
    fields: Union[List[str], List[Dict[str, Any]]]
) -> List[Dict[str, Any]]:
    """
    Deterministic Evidence Indexing.

    Supports two field formats:
    - Legacy: fields is a list of strings (top-level input keys)
      e.g.  fields: ["customer_messages", "internal_notes"]
    - New canonical: fields is a list of {key, source, governed} dicts
      e.g.  fields: [{key: customer_message, source: input.customer_message}]
    """
    evidence: List[Dict[str, Any]] = []
    eid_counter = 1

    for field_spec in fields:
        if isinstance(field_spec, str):
            # Legacy format — field is a top-level key name
            field_name = field_spec
            data = input_data.get(field_name)
            governed = False
        else:
            # New canonical format — field is a {key, source, [governed]} dict
            field_name = field_spec.get("key", "")
            data = _resolve_source(field_spec.get("source", f"input.{field_name}"), input_data)
            governed = field_spec.get("governed", False)

        if data is None:
            continue

        if isinstance(data, list):
            for idx, item in enumerate(data):
                entry: Dict[str, Any] = {
                    "eid": f"E{eid_counter}",
                    "source": field_name,
                    "locator": idx,
                    "text": str(item)
                }
                if governed:
                    entry["governed"] = True
                evidence.append(entry)
                eid_counter += 1

        elif isinstance(data, dict):
            for key in sorted(data.keys()):
                entry = {
                    "eid": f"E{eid_counter}",
                    "source": field_name,
                    "locator": key,
                    "text": f"{key}: {data[key]}"
                }
                if governed:
                    entry["governed"] = True
                evidence.append(entry)
                eid_counter += 1

        else:
            entry = {
                "eid": f"E{eid_counter}",
                "source": field_name,
                "locator": field_name,
                "text": str(data)
            }
            if governed:
                entry["governed"] = True
            evidence.append(entry)
            eid_counter += 1

    return evidence
