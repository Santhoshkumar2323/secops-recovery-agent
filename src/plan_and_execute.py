import logging

from langgraph.graph import END, START, StateGraph

from src import policy
from src.plan_nodes import execute_node, plan_node, replan_node, route_on_plan, summarize_node
from src.plan_state import ResearchState

g = StateGraph(ResearchState)
g.add_node("plan", plan_node)
g.add_node("execute", execute_node)
g.add_node("replan", replan_node)
g.add_node("summarize", summarize_node)
g.add_edge(START, "plan")
g.add_conditional_edges("plan", route_on_plan, {"execute": "execute", "summarize": "summarize"})
g.add_edge("execute", "replan")
g.add_conditional_edges("replan", route_on_plan, {"execute": "execute", "summarize": "summarize"})
g.add_edge("summarize", END)
research_app = g.compile()  

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    names = policy.resource_names()
    task = f"Compare recovery paths when a {names[0]} vs a {names[-1]} is older than its hot retention window."
    out = research_app.invoke({"task": task})
    print("=== PLAN-AND-EXECUTE TRACE ===")
    for t in out["trace"]:
        print(" •", t)
    print("\n=== FINAL REPORT ===\n" + out["report"])