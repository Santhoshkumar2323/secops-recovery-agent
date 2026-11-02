from src import policy
from src.plan_nodes import NO_FINDINGS, route_on_plan, summarize_node
from src.plan_state import build_kb


def test_kb_is_built_from_the_policy_file():
    kb = build_kb()
    assert all(name in kb for name in policy.resource_names())


def test_empty_plan_routes_to_summary():
    assert route_on_plan({"plan": []}) == "summarize"
    assert route_on_plan({"plan": ["look something up"]}) == "execute"


def test_summary_without_findings_makes_no_llm_call():
    out = summarize_node({"task": "anything", "findings": []})
    assert out["report"] == NO_FINDINGS