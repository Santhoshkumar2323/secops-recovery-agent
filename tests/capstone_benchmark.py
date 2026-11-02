import argparse
import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from langchain_core.callbacks import UsageMetadataCallbackHandler
from langchain_core.messages import AIMessage, ToolMessage

from src.recovery_core import get_today
from tests.cases import build_cases


def sys_workflow(message, cfg):
    from src.recovery_workflow import app
    out = app.invoke({"message": message}, config=cfg)
    return out["decision"].verdict, out["reply"], 0


def sys_hybrid(message, cfg):
    from src.hybrid_graph import hybrid
    out = hybrid.invoke({"message": message}, config=cfg)
    return out["decision"].verdict, out["reply"], out.get("tool_calls", 0)


def sys_solo(message, cfg):
    from src.solo_agent import get_solo
    msgs = get_solo().invoke({"messages": [("user", message)]}, config=cfg)["messages"]
    calls = sum(len(m.tool_calls) for m in msgs if isinstance(m, AIMessage))
    hot = [m.content.split(":")[0] for m in msgs if isinstance(m, ToolMessage) and m.name == "check_hot_restore_eligibility"]
    verdict = hot[-1] if hot else ("NEEDS_MORE_INFO" if calls else "NO_RESTORE_REQUESTED")
    return verdict, msgs[-1].content, calls


SYSTEMS = {"workflow": sys_workflow, "solo": sys_solo, "hybrid": sys_hybrid}


def run_system(fn, cases, runs):
    rows = []
    for case in cases:
        for _ in range(runs):
            cb = UsageMetadataCallbackHandler()
            cfg = {"callbacks": [cb], "recursion_limit": 8, "configurable": {"thread_id": uuid.uuid4().hex}}
            t0, error = time.perf_counter(), ""
            try:
                verdict, reply, calls = fn(case.message, cfg)
            except Exception as e:
                verdict, reply, calls = f"ERROR:{type(e).__name__}", "", 0
                error = str(e)[:150]
            rows.append({
                "tag": case.tag, "message": case.message, "expected": case.expected, "got": verdict,
                "secs": time.perf_counter() - t0, "calls": calls, "error": error,
                "tokens": sum(u.get("total_tokens", 0) for u in cb.usage_metadata.values()),
                "alt_ok": (case.keyword in reply.lower()) if case.keyword else None,
            })
    return rows


def summarize(rows):
    secs, toks = [r["secs"] for r in rows], [r["tokens"] for r in rows]
    alt = [r["alt_ok"] for r in rows if r["alt_ok"] is not None]
    bad = [r for r in rows if r["got"] != r["expected"]]
    return {
        "n": len(rows), "verdict_ok": len(rows) - len(bad), "alt_ok": sum(alt), "alt_total": len(alt),
        "p50": float(np.percentile(secs, 50)), "p95": float(np.percentile(secs, 95)),
        "tokens_mean": float(np.mean(toks)), "tokens_max": max(toks),
        "calls_mean": float(np.mean([r["calls"] for r in rows])),
        "errors": sum(r["got"].startswith("ERROR") for r in rows),
        "failures": [{"tag": r["tag"], "expected": r["expected"], "got": r["got"], "message": r["message"][:70],
                      "error": r["error"]} for r in bad[:10]],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=int(os.getenv("BENCH_RUNS", "1")))
    ap.add_argument("--limit", type=int, default=0, help="sample N cases for a quick smoke run")
    ap.add_argument("--systems", default=",".join(SYSTEMS))
    args = ap.parse_args()
    os.environ["AUTO_APPROVE"] = "true"
    cases = build_cases(get_today())
    if args.limit:
        cases = cases[:: max(1, len(cases) // args.limit)][: args.limit]
    report = {"generated_at": datetime.now(timezone.utc).isoformat(), "today": get_today().isoformat(),
              "runs": args.runs, "n_cases": len(cases), "systems": {}}
    print(f"=== SECOPS 3-WAY BENCHMARK ({len(cases)} cases x {args.runs} run(s)) ===")
    for name in args.systems.split(","):
        s = report["systems"][name] = summarize(run_system(SYSTEMS[name], cases, args.runs))
        print(f"{name:<9} verdict={s['verdict_ok']}/{s['n']} alt={s['alt_ok']}/{s['alt_total']} "
              f"p50={s['p50']:.1f}s p95={s['p95']:.1f}s tokens mean={s['tokens_mean']:.0f} "
              f"max={s['tokens_max']} calls={s['calls_mean']:.1f} errors={s['errors']}")
        for f in s["failures"][:3]:
            print("   └─", f)
    Path("results").mkdir(exist_ok=True)
    Path("results/benchmark.json").write_text(json.dumps(report, indent=2))
    print("Saved results/benchmark.json")


if __name__ == "__main__":
    main()