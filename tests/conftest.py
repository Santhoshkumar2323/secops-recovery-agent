import datetime as dt

import pytest

from src import policy

PINNED_TODAY = "2026-10-29"

@pytest.fixture(autouse=True)
def pinned_today(monkeypatch, tmp_path):
    monkeypatch.setenv("RECOVERY_REFERENCE_DATE", PINNED_TODAY)
    monkeypatch.setenv("AUDIT_FILE", str(tmp_path / "audit.jsonl"))
    monkeypatch.setenv("ALERT_FILE", str(tmp_path / "alerts.jsonl"))
    for name in ("SECOPS_POLICY_PATH", "AUTO_APPROVE", "ALERT_WEBHOOK_URL"):
        monkeypatch.delenv(name, raising=False)
    policy.reload()


@pytest.fixture
def today() -> dt.date:
    return dt.date.fromisoformat(PINNED_TODAY)