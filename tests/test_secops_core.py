import datetime as dt
import json

import pytest
from pydantic import ValidationError

from src import policy
from src.dr_tools import check_glacier_vault, check_hot_restore_eligibility, list_dr_alternatives
from src.recovery_core import IncidentFacts, ResourceType, decide


def _facts(resource, date_str, wants_restore=True):
    return IncidentFacts(reasoning="unit test", resource=resource, snapshot_date=date_str, wants_restore=wants_restore)


@pytest.mark.parametrize("resource,date_str,wants_restore,expected", [
    (ResourceType.sandbox_env, "2026-10-25", True, "ELIGIBLE"),            
    (ResourceType.audit_log, "2026-09-01", True, "NOT_ELIGIBLE"),         
    (ResourceType.db_snapshot, "2026-10-01", True, "NOT_ELIGIBLE"),       
    (ResourceType.ephemeral_cache, "2026-10-29", True, "NOT_ELIGIBLE"),    
    (ResourceType.ephemeral_cache, "2026-10-20", True, "NOT_ELIGIBLE"),
    (ResourceType.ephemeral_cache, None, True, "NOT_ELIGIBLE"),            
    (ResourceType.unknown, "2026-10-25", True, "NEEDS_MORE_INFO"),
    (ResourceType.db_snapshot, None, True, "NEEDS_MORE_INFO"),
    (ResourceType.audit_log, "2026-11-15", True, "NEEDS_MORE_INFO"),       
    (ResourceType.db_snapshot, "2026-10-25", False, "NO_RESTORE_REQUESTED"),
])
def test_policy_matrix(today, resource, date_str, wants_restore, expected):
    assert decide(_facts(resource, date_str, wants_restore), today).verdict == expected


def test_boundaries_follow_the_policy_file(today):
    """Edge of every restorable window, derived from config rather than typed in."""
    for name, rule in policy.load_policy().items():
        if not rule.restorable:
            continue
        for age, expected in ((rule.hot_days, "ELIGIBLE"), (rule.hot_days + 1, "NOT_ELIGIBLE")):
            date_str = (today - dt.timedelta(days=age)).isoformat()
            assert decide(_facts(ResourceType(name), date_str), today).verdict == expected, (name, age)


def test_common_date_formats_are_normalised():
    assert _facts(ResourceType.audit_log, "1 September 2026").snapshot_date == "2026-09-01"
    assert _facts(ResourceType.audit_log, "September 1, 2026").snapshot_date == "2026-09-01"


def test_unreadable_date_is_rejected():
    with pytest.raises(ValidationError):
        _facts(ResourceType.audit_log, "sometime last week")


def test_tools_use_the_pinned_date():
    assert check_hot_restore_eligibility.invoke(
        {"resource": "audit_log", "snapshot_date": "2026-09-01"}).startswith("NOT_ELIGIBLE")
    assert check_glacier_vault.invoke(
        {"resource": "audit_log", "snapshot_date": "2026-09-01"}).startswith("IN_GLACIER_VAULT:")
    assert check_glacier_vault.invoke(
        {"resource": "audit_log", "snapshot_date": "2026-12-01"}).startswith("ERROR:")
    assert "replica" in list_dr_alternatives.invoke({"resource": "db_snapshot"}).lower()


def test_glacier_regression_same_day_without_vault():
    assert check_glacier_vault.invoke(
        {"resource": "sandbox_env", "snapshot_date": "2026-10-29"}) == "NOT_IN_GLACIER_VAULT."


def test_policy_is_loaded_from_file(tmp_path, monkeypatch):
    rules = {"resources": {"x": {"hot_days": 3, "glacier_days": None, "dr_alternative": "rebuild"}}}
    path = tmp_path / "p.json"
    path.write_text(json.dumps(rules))
    monkeypatch.setenv("SECOPS_POLICY_PATH", str(path))
    policy.reload()
    assert policy.resource_names() == ["x"]
    assert policy.get("x").hot_days == 3


def test_invalid_policy_is_rejected(tmp_path, monkeypatch):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"resources": {"x": {"hot_days": -1, "dr_alternative": "n/a"}}}))
    monkeypatch.setenv("SECOPS_POLICY_PATH", str(path))
    policy.reload()
    with pytest.raises(policy.PolicyError):
        policy.load_policy()

def test_volatile_resource_needs_no_date():
    assert check_hot_restore_eligibility.invoke({"resource": "ephemeral_cache"}).startswith("NOT_ELIGIBLE")        