import datetime as dt
import os
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

from src import policy
from src.dates import to_iso

def get_today() -> dt.date:
    override = os.getenv("RECOVERY_REFERENCE_DATE")
    return dt.date.fromisoformat(override) if override else dt.date.today()


ResourceType = Enum(
    "ResourceType",
    {name: name for name in [*policy.resource_names(), "unknown"]},
    type=str,
    module=__name__,
)


class IncidentFacts(BaseModel):
    reasoning: str = Field(
        description="Step-by-step note on where the resource type and target snapshot/incident date appear."
    )
    resource: ResourceType  # pyright: ignore[reportInvalidTypeForm]
    snapshot_date: Optional[str] = Field(
        default=None,
        description="YYYY-MM-DD target date for restoration, or null if no full date is stated. Never guess.",
    )
    wants_restore: bool = Field(
        description="True if the user is requesting a data restore, rollback, or snapshot recovery."
    )

    @field_validator("snapshot_date", mode="before")
    @classmethod
    def validate_iso_date(cls, v: Optional[str]) -> Optional[str]:
        return to_iso(v)  

class DecisionResult(BaseModel):
    verdict: Literal["NO_RESTORE_REQUESTED", "NEEDS_MORE_INFO", "ELIGIBLE", "NOT_ELIGIBLE", "ESCALATE_TO_SECOPS", "APPROVAL_DENIED"]
    reason: str
    days_elapsed: Optional[int] = None
    hot_window: Optional[int] = None


def decide(facts: IncidentFacts, today: dt.date) -> DecisionResult:
    if not facts.wants_restore:
        return DecisionResult(
            verdict="NO_RESTORE_REQUESTED",
            reason="Engineer asked a general question and did not request a snapshot restore.",
        )
    if facts.resource is ResourceType.unknown:
        missing = ["resource type"] + (["target snapshot date (YYYY-MM-DD)"] if facts.snapshot_date is None else [])
        return DecisionResult(verdict="NEEDS_MORE_INFO", reason=f"Missing required triage parameters: {', '.join(missing)}.")

    rule = policy.get(facts.resource.value)
    if not rule.restorable:
        return DecisionResult(
            verdict="NOT_ELIGIBLE",
            reason=f"{rule.name} is volatile and has no backup tier, so it cannot be restored.",
        )
    if facts.snapshot_date is None:
        return DecisionResult(
            verdict="NEEDS_MORE_INFO",
            reason="Missing required triage parameters: target snapshot date (YYYY-MM-DD).",
        )

    days = (today - dt.date.fromisoformat(facts.snapshot_date)).days
    if days < 0:
        return DecisionResult(
            verdict="NEEDS_MORE_INFO",
            reason=f"Requested snapshot date {facts.snapshot_date} is in the future relative to {today.isoformat()}.",
        )
    if days <= rule.hot_days:
        return DecisionResult(
            verdict="ELIGIBLE",
            reason=f"Target date is {days} days old (within the {rule.hot_days}-day hot-tier window for {rule.name}).",
            days_elapsed=days,
            hot_window=rule.hot_days,
        )
    return DecisionResult(
        verdict="NOT_ELIGIBLE",
        reason=f"Target date is {days} days old, exceeding the {rule.hot_days}-day hot-tier window for {rule.name}.",
        days_elapsed=days,
        hot_window=rule.hot_days,
    )