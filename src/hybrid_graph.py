import datetime as dt
import logging
import uuid
from typing import Literal

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from src import policy
from src.approval import approval_gate
from src.dr_tools import check_glacier_vault, list_dr_alternatives
from src.llm import get_fast
from src.recovery_core import get_today
from src.recovery_workflow import SERDE
from src.workflow_nodes import DRAFT_PROMPT, State, decide_node, escalate, extract, route

log = logging.getLogger("secops.hybrid")


class HState(State, total=False):
    resolution_notes: str
    tool_calls: int
    tools_used: list[str]


def resolve(state: HState, config: RunnableConfig) -> dict:
    facts = state["facts"]
    name, date = facts.resource.value, facts.snapshot_date
    plan = [(list_dr_alternatives, {"resource": name})]
    if date and policy.get(name).glacier_days is not None:
        plan.append((check_glacier_vault, {"resource": name, "snapshot_date": date}))
    notes = " ".join(tool.invoke(args, config=config) for tool, args in plan)
    used = [tool.name for tool, _ in plan]
    return {
        "resolution_notes": notes,
        "tool_calls": len(plan),
        "tools_used": used,
        "trace": state.get("trace", []) + [f"resolve -> tools={used}"],
    }


def draft_h(state: HState, config: RunnableConfig) -> dict:
    res, notes = state["decision"], state.get("resolution_notes", "")
    system = DRAFT_PROMPT.format(verdict=res.verdict, reason=res.reason)
    if notes:
        system += f" Mention these verified recovery options: {notes}"
    try:
        reply = get_fast(0.2).invoke([("system", system), ("human", state["message"])], config=config).content
        status = "draft_h -> complete"
    except Exception as e:
        log.exception("draft failed; using the plain policy text")
        reply, status = f"{res.verdict}: {res.reason} {notes}".strip(), f"draft_h_fallback ({type(e).__name__})"
    return {"reply": reply, "trace": state.get("trace", []) + [status]}


def route_h(state: HState) -> Literal["approval", "resolve", "draft"]:
    verdict = state["decision"].verdict
    return "approval" if verdict == "ELIGIBLE" else "resolve" if verdict == "NOT_ELIGIBLE" else "draft"


def build_hybrid(checkpointer=None):
    h = StateGraph(HState)
    for name, fn in [("extract", extract), ("decide", decide_node), ("approval", approval_gate),
                     ("resolve", resolve), ("draft_h", draft_h), ("escalate", escalate)]:
        h.add_node(name, fn)
    h.add_edge(START, "extract")
    h.add_conditional_edges("extract", route, {"decide": "decide", "escalate": "escalate"})
    h.add_conditional_edges("decide", route_h, {"approval": "approval", "resolve": "resolve", "draft": "draft_h"})
    h.add_edge("approval", "draft_h")
    h.add_edge("resolve", "draft_h")
    h.add_edge("draft_h", END)
    h.add_edge("escalate", END)
    return h.compile(checkpointer=checkpointer or MemorySaver(serde=SERDE))


hybrid = build_hybrid()  

if __name__ == "__main__":
    when = (get_today() - dt.timedelta(days=58)).strftime("%d %B %Y")
    cfg = {"configurable": {"thread_id": f"hybrid-{uuid.uuid4().hex[:8]}"}}
    out = hybrid.invoke({"message": f"Our compliance team needs an audit_log restore from {when}."}, config=cfg)
    print("Trace:", out["trace"])
    print("Tools:", out.get("tool_calls"), out.get("tools_used"))
    print("Reply:", out["reply"])