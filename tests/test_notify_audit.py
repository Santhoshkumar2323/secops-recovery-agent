import json

from src import audit, notify
from src.approval import approval_gate
from src.recovery_core import DecisionResult
from src.workflow_nodes import escalate

CFG = {"configurable": {"thread_id": "t-1"}}


def _rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_page_writes_an_alert(tmp_path):
    result = notify.page("model down", "t-1", "restore please")
    assert result.delivered
    assert _rows(tmp_path / "alerts.jsonl")[0]["reason"] == "model down"


def test_page_reports_failure_honestly(tmp_path, monkeypatch):
    monkeypatch.setenv("ALERT_FILE", str(tmp_path))  
    result = notify.page("model down")
    assert not result.delivered and result.channel == "none"


def test_audit_appends_one_json_line_per_event(tmp_path):
    assert audit.record("decision", "t-1", verdict="ELIGIBLE")
    assert audit.record("approval", "t-1", approved=True)
    rows = _rows(tmp_path / "audit.jsonl")
    assert [r["event"] for r in rows] == ["decision", "approval"]
    assert rows[0]["thread_id"] == "t-1"


def test_auto_approve_is_audited(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTO_APPROVE", "true")
    out = approval_gate({"decision": DecisionResult(verdict="ELIGIBLE", reason="ok")}, CFG)
    assert out["approved"] is True and out["approver"] == "auto"
    assert _rows(tmp_path / "audit.jsonl")[0]["approver"] == "auto"


def test_escalation_claims_delivery_only_when_true(tmp_path, monkeypatch):
    assert "recorded" in escalate({"message": "x"}, CFG)["reply"]
    monkeypatch.setenv("ALERT_FILE", str(tmp_path))
    failed = escalate({"message": "x"}, CFG)
    assert "contact SecOps directly" in failed["reply"]
    assert failed["decision"].verdict == "ESCALATE_TO_SECOPS"