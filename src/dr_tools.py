import datetime as dt
from typing import TYPE_CHECKING, Literal

from langchain_core.tools import tool

from src import notify, policy
from src.recovery_core import get_today

if TYPE_CHECKING:
    ResourceName = str
else:
    ResourceName = Literal[tuple(policy.resource_names())]  # type: ignore[valid-type]


def _age_in_days(snapshot_date: str) -> int:
    return (get_today() - dt.date.fromisoformat(snapshot_date)).days


@tool
def check_hot_restore_eligibility(resource: ResourceName, snapshot_date: str = "") -> str:
    """Decide whether an instant hot-tier restore is allowed. ALWAYS call this before stating
    any restore decision. snapshot_date must be YYYY-MM-DD; leave it empty only for resources
    that can never be restored."""
    rule = policy.get(resource)
    if not rule.restorable:
        return f"NOT_ELIGIBLE: {resource} is volatile and cannot be restored."
    try:
        days = _age_in_days(snapshot_date)
    except ValueError:
        return "ERROR: snapshot_date must be in YYYY-MM-DD format."
    if days < 0:
        return f"NEEDS_MORE_INFO: snapshot_date {snapshot_date} is in the future."
    verdict = "ELIGIBLE" if days <= rule.hot_days else "NOT_ELIGIBLE"
    return f"{verdict}: {days} days since snapshot, hot retention window is {rule.hot_days} days."


@tool
def check_glacier_vault(resource: ResourceName, snapshot_date: str) -> str:
    """Check whether an expired hot resource is still preserved in the cold Glacier compliance vault.
    snapshot_date must be YYYY-MM-DD."""
    try:
        days = _age_in_days(snapshot_date)
    except ValueError:
        return "ERROR: snapshot_date must be in YYYY-MM-DD format."
    if days < 0:
        return f"ERROR: snapshot_date {snapshot_date} is in the future."
    in_vault, left = policy.glacier_status(resource, days)
    return f"IN_GLACIER_VAULT: {left} days of cold retention remain." if in_vault else "NOT_IN_GLACIER_VAULT."


@tool
def list_dr_alternatives(resource: ResourceName) -> str:
    """List the Disaster Recovery (DR) fallback options when an instant hot-tier restore is denied."""
    return policy.get(resource).dr_alternative


@tool
def escalate_to_secops(reason: str) -> str:
    """Page the human on-call SecOps engineer when resource type or snapshot date is missing."""
    result = notify.page(reason)
    if result.delivered:
        return f"NEEDS_MORE_INFO: Escalation recorded via {result.channel} ({reason})"
    return f"NEEDS_MORE_INFO: Escalation could NOT be delivered ({reason}). Tell the user to contact SecOps directly."


if __name__ == "__main__":
    name = policy.resource_names()[0]
    sample = (get_today() - dt.timedelta(days=40)).isoformat()
    print("Hot     :", check_hot_restore_eligibility.invoke({"resource": name, "snapshot_date": sample}))
    print("Glacier :", check_glacier_vault.invoke({"resource": name, "snapshot_date": sample}))
    print("DR      :", list_dr_alternatives.invoke({"resource": name}))