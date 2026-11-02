import json
import logging
import os
import threading
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("secops.notify")
_lock = threading.Lock()


@dataclass(frozen=True)
class PageResult:
    delivered: bool
    channel: str
    detail: str = ""


def _write_file(entry: dict) -> PageResult:
    path = Path(os.getenv("ALERT_FILE", "alerts.jsonl"))
    try:
        with _lock, path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")
        return PageResult(True, f"file:{path.name}")
    except OSError as e:
        log.error("could not write alert file %s: %s", path, e)
        return PageResult(False, "file", str(e))


def _post_webhook(url: str, entry: dict) -> PageResult:
    body = {"text": f"SecOps alert [{entry['thread_id']}]: {entry['reason']}"}  # Slack/Teams style
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=float(os.getenv("ALERT_TIMEOUT_S", "5"))) as resp:
            return PageResult(200 <= resp.status < 300, "webhook", f"HTTP {resp.status}")
    except Exception as e:
        log.error("webhook alert failed: %s", e)
        return PageResult(False, "webhook", type(e).__name__)


def page(reason: str, thread_id: str = "no-thread", message: str = "") -> PageResult:
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "thread_id": thread_id,
        "reason": reason,
        "request": message[:200],
    }
    results = [_write_file(entry)]
    url = os.getenv("ALERT_WEBHOOK_URL")
    if url:
        results.append(_post_webhook(url, entry))
    ok = [r for r in results if r.delivered]
    return PageResult(bool(ok), "+".join(r.channel for r in ok) or "none", "; ".join(r.detail for r in results if r.detail))