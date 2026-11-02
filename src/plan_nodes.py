import logging
import os
from typing import Literal

from src.llm import get_fast, get_large
from src.plan_state import PlanSchema, ReplanDecision, ResearchState, build_kb

log = logging.getLogger("secops.plan")
MAX_STEPS = int(os.getenv("PLAN_MAX_STEPS", "3"))
NO_FINDINGS = "No findings could be gathered automatically. Escalate to the on-call SecOps engineer."


def plan_node(state: ResearchState) -> dict:
    try:
        res = get_large().with_structured_output(PlanSchema).invoke([
            ("system", f"Break the SecOps question into at most {MAX_STEPS} lookup steps. Each step must be answerable "
                       f"ONLY from this knowledge base. Never plan steps about anything it does not cover "
                       f"(for example latency, cost or data fidelity).\n{build_kb()}"),
            ("human", state["task"]),
        ])
        steps = [s for s in res.steps if s.strip()][:MAX_STEPS]
    except Exception:
        log.exception("planning failed")
        steps = []
    return {"plan": steps, "step_count": 0, "trace": [f"PLAN ({len(steps)} steps): {steps}"]}


def execute_node(state: ResearchState) -> dict:
    step, idx = state["plan"][0], state.get("step_count", 0) + 1
    try:
        finding = get_fast().invoke([
            ("system", f"Answer the step concisely (max 35 words) using ONLY this SecOps KB:\n{build_kb()}\n"
                       "If the KB does not contain the answer, reply exactly: NOT_IN_KB"),
            ("human", f"Step: {step}"),
        ]).content.strip()
    except Exception as e:
        log.exception("execute failed")
        finding = f"LOOKUP_FAILED ({type(e).__name__})"
    return {
        "plan": state["plan"][1:],
        "findings": [f"[Step {idx}: {step}] -> {finding}"],
        "step_count": idx,
        "trace": [f"EXECUTE #{idx}: {step} -> {finding[:55]}..."],
    }


def replan_node(state: ResearchState) -> dict:
    if state.get("step_count", 0) >= state.get("max_steps", MAX_STEPS) or not state.get("plan"):
        return {"plan": [], "trace": ["REPLAN: budget reached or plan empty -> summarize"]}
    try:
        d = get_fast().with_structured_output(ReplanDecision).invoke([
            ("system", "Check if the gathered findings fully answer the task. If yes, set is_complete=True."),
            ("human", f"Task: {state['task']}\nFindings: {state['findings']}\nRemaining plan: {state['plan']}"),
        ])
    except Exception:
        log.exception("replan failed; keeping the existing plan")
        return {"trace": ["REPLAN: failed, keeping plan"]}
    return {
        "plan": [] if d.is_complete else d.updated_remaining_steps,
        "trace": [f"REPLAN (complete={d.is_complete}): {d.reasoning}"],
    }


def summarize_node(state: ResearchState) -> dict:
    notes = "\n".join(state.get("findings", []))
    if not notes:
        return {"report": NO_FINDINGS, "trace": ["SUMMARIZE: no findings, fallback report"]}
    try:
        report = get_large(0.2).invoke([
            ("system", "Write a crisp SecOps Incident Runbook Summary (max 90 words, plain text, no headings) based "
                       "strictly on the findings. Never add facts that are not in the findings. If a finding says "
                       "NOT_IN_KB, end with one line naming what the runbook does not cover."),
            ("human", f"Task: {state['task']}\n\nFindings:\n{notes}"),
        ]).content.strip()
    except Exception:
        log.exception("summary failed")
        report = f"Summary unavailable. Raw findings:\n{notes}"
    return {"report": report, "trace": ["SUMMARIZE: runbook report compiled."]}


def route_on_plan(state: ResearchState) -> Literal["execute", "summarize"]:
    return "execute" if state.get("plan") else "summarize"