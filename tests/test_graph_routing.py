import json
from types import SimpleNamespace

import pytest
from langgraph.types import Command

from src import llm
from src.hybrid_graph import build_hybrid
from src.recovery_core import IncidentFacts, ResourceType
from src.recovery_workflow import build_graph


class FakeLLM:
    def __init__(self, facts=None, fail=False):
        self.facts, self.fail = facts, fail

    def with_structured_output(self, schema):
        return self

    def with_retry(self, **kwargs):
        return self

    def invoke(self, messages, config=None):
        if self.fail:
            raise RuntimeError("model down")
        return self.facts if self.facts is not None else SimpleNamespace(content="fake reply")


@pytest.fixture(autouse=True)
def fresh_llm():
    llm.reset()
    yield
    llm.reset()


def _use(resource=None, date=None, large_fails=False, fast_fails=False):
    facts = IncidentFacts(reasoning="t", resource=resource, snapshot_date=date, wants_restore=True) if resource else None
    llm.override("large", FakeLLM(facts=facts, fail=large_fails))
    llm.override("fast", FakeLLM(fail=fast_fails))


def _cfg(name):
    return {"configurable": {"thread_id": name}}


def _events(tmp_path):
    path = tmp_path / "audit.jsonl"
    return [json.loads(line)["event"] for line in path.read_text().splitlines()] if path.exists() else []


def test_eligible_restore_pauses_then_resumes_when_approved(tmp_path):
    _use(ResourceType.sandbox_env, "2026-10-25")
    graph, cfg = build_graph(), _cfg("t-ok")
    graph.invoke({"message": "restore please"}, config=cfg)
    assert graph.get_state(cfg).next == ("approval",)
    graph.invoke(Command(resume={"approved": True, "approver": "alice"}), config=cfg)
    final = graph.get_state(cfg).values
    assert graph.get_state(cfg).next == () and final["decision"].verdict == "ELIGIBLE"
    assert final["approver"] == "alice" and final["reply"] == "fake reply"
    assert "approval" in _events(tmp_path)


def test_denied_approval_changes_the_verdict():
    _use(ResourceType.sandbox_env, "2026-10-25")
    graph, cfg = build_graph(), _cfg("t-no")
    graph.invoke({"message": "restore please"}, config=cfg)
    graph.invoke(Command(resume={"approved": False, "approver": "bob"}), config=cfg)
    assert graph.get_state(cfg).values["decision"].verdict == "APPROVAL_DENIED"


def test_denied_restore_skips_the_approval_gate(tmp_path):
    _use(ResourceType.audit_log, "2026-09-01")
    graph, cfg = build_graph(), _cfg("t-skip")
    graph.invoke({"message": "restore please"}, config=cfg)
    assert graph.get_state(cfg).next == ()
    assert graph.get_state(cfg).values["decision"].verdict == "NOT_ELIGIBLE"
    assert "approval" not in _events(tmp_path)


def test_extraction_failure_escalates_and_writes_an_alert(tmp_path):
    _use(large_fails=True)
    graph, cfg = build_graph(), _cfg("t-esc")
    graph.invoke({"message": "restore please"}, config=cfg)
    final = graph.get_state(cfg).values
    assert final["decision"].verdict == "ESCALATE_TO_SECOPS"
    assert len((tmp_path / "alerts.jsonl").read_text().splitlines()) == 1


def test_writer_failure_falls_back_to_policy_text():
    _use(ResourceType.audit_log, "2026-09-01", fast_fails=True)
    graph, cfg = build_graph(), _cfg("t-fb")
    graph.invoke({"message": "restore please"}, config=cfg)
    assert graph.get_state(cfg).values["reply"].startswith("NOT_ELIGIBLE:")


def test_hybrid_calls_tools_directly_only_when_needed():
    _use(ResourceType.audit_log, "2026-09-01")
    out = build_hybrid().invoke({"message": "x"}, config=_cfg("h-1"))
    assert out["tools_used"] == ["list_dr_alternatives", "check_glacier_vault"]
    assert "IN_GLACIER_VAULT" in out["resolution_notes"]
    _use(ResourceType.db_snapshot, "2026-10-01")
    out = build_hybrid().invoke({"message": "x"}, config=_cfg("h-2"))
    assert out["tools_used"] == ["list_dr_alternatives"] and out["tool_calls"] == 1