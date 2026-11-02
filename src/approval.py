import logging
import os

from langgraph.types import interrupt

from src import audit
from src.recovery_core import DecisionResult

log = logging.getLogger("secops.approval")
_warned = False


def _auto_approve() -> bool:
    return os.getenv("AUTO_APPROVE", "").strip().lower() in {"1", "true", "yes"}


def approval_gate(state: dict, config) -> dict:
    tid = audit.thread_id_of(config)
    decision: DecisionResult = state["decision"]
    trace = state.get("trace", [])

    if _auto_approve():
        global _warned
        if not _warned:
            _warned = True
            log.warning("AUTO_APPROVE is on: approvals are logged to the audit file but no human is asked")
        audit.record("approval", tid, approved=True, approver="auto")
        return {"approved": True, "approver": "auto", "trace": trace + ["approval -> auto-approved"]}


    facts = state["facts"]
    answer = interrupt({
        "question": "Approve this restore?",
        "resource": facts.resource.value,
        "snapshot_date": facts.snapshot_date,
        "policy_reason": decision.reason,
    })
    answer = answer if isinstance(answer, dict) else {}
    approved = answer.get("approved") is True
    approver = str(answer.get("approver", "unknown"))
    audit.record("approval", tid, approved=approved, approver=approver)

    if approved:
        return {"approved": True, "approver": approver, "trace": trace + [f"approval -> approved by {approver}"]}
    denied = DecisionResult(
        verdict="APPROVAL_DENIED",
        reason=f"The restore was not approved by {approver}.",
        days_elapsed=decision.days_elapsed,
        hot_window=decision.hot_window,
    )
    return {"approved": False, "approver": approver, "decision": denied, "trace": trace + [f"approval -> denied by {approver}"]}