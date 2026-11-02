import sys
import uuid

from src.recovery_workflow import app

DEFAULT = [
    "Can you restore our ephemeral_cache from 20 October 2026?",
    "We lost our ephemeral_cache, please restore it.",
    "I need an emergency restore for the production cluster we lost.",
    "Please restore our Kafka topics from 27 October 2026.",
    "Restore audit_log from 1 November 2026.",
    "What is our hot retention policy for audit logs?",
    "Restore audit_log from 1 September 2026.",
    "Restore audit_log from September 1, 2026.",
    "Restore audit_log from sometime last week.",
]

for msg in sys.argv[1:] or DEFAULT:
    cfg = {"configurable": {"thread_id": uuid.uuid4().hex}}
    app.invoke({"message": msg}, config=cfg)
    values = app.get_state(cfg).values
    facts, decision = values.get("facts"), values["decision"]
    found = f"{facts.resource.value}, {facts.snapshot_date}" if facts else "none (extraction failed)"
    print(f"\nRequest   : {msg}")
    print(f"Extracted : {found}")
    print(f"Decision  : {decision.verdict} ({decision.reason})")
    print(f"Reply     : {values.get('reply', '(waiting for approval)')}")