import datetime as dt
import logging
import uuid

from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from src.approval import approval_gate
from src.recovery_core import get_today
from src.workflow_nodes import State, decide_node, draft, escalate, extract, route, route_after_decide

SERDE = JsonPlusSerializer(allowed_msgpack_modules=[
    ("src.recovery_core", "ResourceType"),
    ("src.recovery_core", "IncidentFacts"),
    ("src.recovery_core", "DecisionResult"),
])

def build_graph(checkpointer=None):
    g = StateGraph(State)
    for name, fn in [("extract", extract), ("decide", decide_node), ("approval", approval_gate),
                     ("draft", draft), ("escalate", escalate)]:
        g.add_node(name, fn)
    g.add_edge(START, "extract")
    g.add_conditional_edges("extract", route, {"decide": "decide", "escalate": "escalate"})
    g.add_conditional_edges("decide", route_after_decide, {"approval": "approval", "draft": "draft"})
    g.add_edge("approval", "draft")
    g.add_edge("draft", END)
    g.add_edge("escalate", END)
    return g.compile(checkpointer=checkpointer or MemorySaver(serde=SERDE))


app = build_graph() 

if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    when = (get_today() - dt.timedelta(days=4)).strftime("%d %B %Y")
    cfg = {"configurable": {"thread_id": f"demo-{uuid.uuid4().hex[:8]}"}}
    app.invoke({"message": f"We need to restore a sandbox_env from {when} after a bad deploy."}, config=cfg)
    if app.get_state(cfg).next: 
        yes = input("Approve this restore? [y/N] ").strip().lower() == "y"
        app.invoke(Command(resume={"approved": yes, "approver": "local-demo"}), config=cfg)
    out = app.get_state(cfg).values
    print("Trace  :", out["trace"])
    print("Verdict:", out["decision"].verdict)
    print("Reply  :", out["reply"])