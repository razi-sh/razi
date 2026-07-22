"""
The escalation triage agent: a small Google ADK agent, backed by Gemini,
with three tools. Governance is not implemented in this file -- it is
delegated entirely to `razi_adapter.RaziGovernor`, registered below as the
agent's `before_tool_callback` / `after_tool_callback`.

Tools:
  - get_ticket_context(ticket_id)     read-only, ungoverned
  - get_account_usage(ticket_id)      read-only, ungoverned
  - submit_escalation_decision(...)   the one consequential action; every
                                       call is intercepted by RaziGovernor
                                       before it is allowed to execute
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List

from razi_adapter import RaziGovernor

try:
    from google.adk.agents import Agent
except ImportError as e:  # pragma: no cover
    raise ImportError(
        "google-adk is not installed. Run "
        "`pip install -r examples/adk_escalation_agent/requirements.txt` "
        "from the repo root first."
    ) from e

_HERE = Path(__file__).resolve().parent
_FIXTURES_PATH = _HERE / "fixtures" / "tickets.json"
_INSTRUCTION = (_HERE / "agent_instruction.txt").read_text()


def _load_ticket(ticket_id: str) -> dict:
    with open(_FIXTURES_PATH, "r") as f:
        tickets = json.load(f)
    if ticket_id not in tickets:
        raise ValueError(
            f"Unknown ticket_id: {ticket_id!r}. Known tickets: {sorted(tickets)}"
        )
    return tickets[ticket_id]


def get_ticket_context(ticket_id: str) -> dict:
    """Look up a support ticket's customer-facing messages, current
    severity, SLA terms, and internal notes.

    Args:
        ticket_id: The ticket identifier, e.g. "TCK-1001".

    Returns:
        A dict with ticket_id, account_tier, current_severity, sla_hours,
        time_open_hours, customer_messages, and internal_notes.
    """
    t = _load_ticket(ticket_id)
    return {
        "ticket_id": t["ticket_id"],
        "account_tier": t["account_tier"],
        "current_severity": t["current_severity"],
        "sla_hours": t["sla_hours"],
        "time_open_hours": t["time_open_hours"],
        "customer_messages": t["customer_messages"],
        "internal_notes": t["internal_notes"],
    }


def get_account_usage(ticket_id: str) -> dict:
    """Look up usage metrics, open incident count, and contract value for
    the account associated with a ticket.

    Args:
        ticket_id: The ticket identifier, e.g. "TCK-1001".

    Returns:
        A dict with usage_metrics, open_incidents, and contract_value.
    """
    t = _load_ticket(ticket_id)
    return {
        "usage_metrics": t["usage_metrics"],
        "open_incidents": t["open_incidents"],
        "contract_value": t["contract_value"],
    }


def submit_escalation_decision(
    recommended_severity: str,
    confidence: float,
    evidence_ids: List[str],
    justification: str,
) -> dict:
    """Submit a final escalation severity decision for governance review.

    This is the one consequential action this agent can take. Note that it
    does not accept a self-reported compliance field: Razi's governance
    layer (registered as this agent's before_tool_callback) is the sole
    authority on whether a decision is authorized, never the model. If the
    decision is rejected, the tool's response will explain exactly why --
    fix the listed issues and call this tool again.

    Args:
        recommended_severity: One of "S1", "S2", "S3", "S4".
        confidence: Confidence in this recommendation, from 0.0 to 1.0.
        evidence_ids: Evidence IDs (e.g. "E1") backing the justification.
            Every ID must come from the evidence you were actually given.
        justification: Explanation citing evidence_ids. Must never quote or
            paraphrase internal notes.

    Returns:
        A dict describing whether the decision was accepted or rejected.
    """
    # This body only runs when RaziGovernor.before_tool_callback returns
    # None (the proposed decision is compliant) -- otherwise ADK never
    # calls this function at all; the callback's returned dict is used as
    # the tool's result instead. So there is deliberately nothing to
    # validate here: by the time this code runs, the decision has already
    # been authorized.
    return {
        "recommended_severity": recommended_severity,
        "confidence": confidence,
        "evidence_ids": evidence_ids,
        "justification": justification,
    }


def build_agent(scenario_name: str = "escalation_agent", max_attempts: int = 3) -> Agent:
    """Construct the escalation triage agent with Razi wired in as its
    governance layer."""
    governor = RaziGovernor(scenario_name=scenario_name, max_attempts=max_attempts)
    return Agent(
        name="escalation_triage_agent",
        model="gemini-3.6-flash",
        description="Triages support tickets into a governed escalation severity decision.",
        instruction=_INSTRUCTION,
        tools=[get_ticket_context, get_account_usage, submit_escalation_decision],
        before_tool_callback=governor.before_tool_callback,
        after_tool_callback=governor.after_tool_callback,
    )
