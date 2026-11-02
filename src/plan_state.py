import operator
from typing import Annotated, TypedDict

from pydantic import BaseModel, Field

from src import policy

class PlanSchema(BaseModel):
    steps: list[str] = Field(description="Ordered SecOps runbook lookup steps.")


class ReplanDecision(BaseModel):
    reasoning: str = Field(description="Assessment of gathered findings vs remaining gaps.")
    is_complete: bool = Field(description="True if we have all facts needed to write the runbook report.")
    updated_remaining_steps: list[str] = Field(default_factory=list)


class ResearchState(TypedDict, total=False):
    task: str
    plan: list[str]
    findings: Annotated[list[str], operator.add]
    step_count: int
    max_steps: int
    report: str
    trace: Annotated[list[str], operator.add]


def build_kb() -> str:
    lines = []
    for p in policy.load_policy().values():
        hot = f"hot restore window {p.hot_days} days" if p.restorable else "never restorable"
        vault = f"Glacier retention {p.glacier_days} days" if p.glacier_days is not None else "no Glacier copy"
        lines.append(f"- {p.name}: {hot}; {vault}; fallback: {p.dr_alternative}")
    return "\n".join(lines)