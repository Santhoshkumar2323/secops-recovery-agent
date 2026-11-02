import logging
import time
from typing import Literal, Optional, TypedDict

from langchain_core.runnables import RunnableConfig

from src import audit, notify, policy
from src.llm import get_fast, get_large
from src.recovery_core import DecisionResult, IncidentFacts, decide, get_today

log = logging.getLogger("secops.workflow")

EXTRACT_PROMPT = (
    "Today's date is {today}. Extract incident recovery facts from the request.\n"
    "Valid resources: {resources}. Everyday wording maps as follows: {aliases}.\n"
    "Resolve relative dates (like 'yesterday') using today's date. Never guess a missing date or resource.\n"
    "ALWAYS call the tool, even for a general question or a message with no restore request: "
    "then set wants_restore=false and resource=unknown."
)

DRAFT_PROMPT = (
    "You write concise SecOps support replies, max 75 words. The decision is final: {verdict}. "
    "Policy reason: {reason}. Do not change the decision or invent policy. "
    "If NEEDS_MORE_INFO, ask specifically for the missing field."
)


class State(TypedDict, total=False):
    message: str
    facts: Optional[IncidentFacts]
    decision: DecisionResult
    reply: str
    approved: bool
    approver: str
    trace: list[str]


def _trace(state: State, entry: str) -> list[str]:
    return state.get("trace", []) + [entry]


def extract(state: State, config: RunnableConfig) -> dict:
    t0 = time.perf_counter()
    prompt = EXTRACT_PROMPT.format(
        today=get_today().isoformat(),
        resources=", ".join(policy.resource_names()),
        aliases=policy.alias_hints(),
    )
    try:
        extractor = get_large().with_structured_output(IncidentFacts).with_retry(stop_after_attempt=3)
        facts = extractor.invoke([("system", prompt), ("human", state["message"])])
        status = f"extract_ok ({time.perf_counter() - t0:.2f}s) -> resource={facts.resource.value}, date={facts.snapshot_date}"
    except Exception as e:
        log.warning("extraction failed after retries: %s: %s", type(e).__name__, str(e)[:200])
        facts, status = None, f"extract_failed ({time.perf_counter() - t0:.2f}s) -> {type(e).__name__}"
    return {"facts": facts, "trace": _trace(state, status)}


def decide_node(state: State, config: RunnableConfig) -> dict:
    res = decide(state["facts"], get_today())
    audit.record("decision", audit.thread_id_of(config), verdict=res.verdict, reason=res.reason,
                 request=state["message"][:200])
    return {"decision": res, "trace": _trace(state, f"decide -> {res.verdict} ({res.reason})")}


def draft(state: State, config: RunnableConfig) -> dict:
    t0, res = time.perf_counter(), state["decision"]
    system = DRAFT_PROMPT.format(verdict=res.verdict, reason=res.reason)
    try:
        reply = get_fast(0.2).invoke([("system", system), ("human", state["message"])], config=config).content
        status = f"draft ({time.perf_counter() - t0:.2f}s)"
    except Exception as e:
        log.exception("draft failed; using the plain policy text")
        reply, status = f"{res.verdict}: {res.reason}", f"draft_fallback ({type(e).__name__})"
    return {"reply": reply, "trace": _trace(state, status)}


def escalate(state: State, config: RunnableConfig) -> dict:
    tid = audit.thread_id_of(config)
    reason = "Automated extraction failed after 3 retries."
    result = notify.page(reason, tid, state.get("message", ""))
    audit.record("escalation", tid, reason=reason, delivered=result.delivered, channel=result.channel)
    if result.delivered:
        reply = f"Your request was recorded in the on-call SecOps alert queue (via {result.channel}, ref {tid})."
    else:
        reply = ("Automated processing failed and the on-call alert could not be delivered. "
                 "Please retry or contact SecOps directly.")
    return {
        "decision": DecisionResult(verdict="ESCALATE_TO_SECOPS", reason=reason),
        "reply": reply,
        "trace": _trace(state, f"escalate -> delivered={result.delivered}"),
    }


def route(state: State) -> Literal["decide", "escalate"]:
    return "decide" if state.get("facts") is not None else "escalate"


def route_after_decide(state: State) -> Literal["approval", "draft"]:
    return "approval" if state["decision"].verdict == "ELIGIBLE" else "draft"