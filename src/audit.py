import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("secops.audit")
_lock = threading.Lock()


def thread_id_of(config) -> str:
    return ((config or {}).get("configurable") or {}).get("thread_id", "no-thread")


def record(event: str, thread_id: str = "no-thread", **data) -> bool:
    entry = {"ts": datetime.now(timezone.utc).isoformat(), "thread_id": thread_id, "event": event, **data}
    path = Path(os.getenv("AUDIT_FILE", "audit.jsonl"))
    try:
        with _lock, path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")
        return True
    except OSError as e:
        log.error("AUDIT WRITE FAILED for %s: %s", event, e)
        return False