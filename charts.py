import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

SRC = Path(sys.argv[1] if len(sys.argv) > 1 else "results/benchmark.json")
OUT = "secops_performance_infographic.png"
LABELS = {"workflow": "Workflow\n(Deterministic DAG)", "solo": "Solo Agent\n(Pure ReAct)",
          "hybrid": "Hybrid Graph\n(Direct tool calls)"}
COLORS = {"workflow": "#576574", "solo": "#ff9f43", "hybrid": "#9b59b6"}


def load(path: Path):
    if not path.exists():
        sys.exit(f"{path} not found. Run: python -m tests.capstone_benchmark")
    data = json.loads(path.read_text())
    systems = {k: v for k, v in data["systems"].items() if k in LABELS}
    return data, (systems or sys.exit("No known systems in the results file."))


def style(ax, names, title, ylabel):
    ax.set_title(title, fontsize=12, fontweight="bold", pad=15)
    ax.set_xticks(np.arange(len(names)))
    ax.set_xticklabels([LABELS[n] for n in names], fontsize=8)
    ax.set_ylabel(ylabel, fontsize=10, color="#cccccc")
    ax.grid(True, linestyle="--", alpha=0.1)


def bars(ax, names, values, title, ylabel, fmt):
    rects = ax.bar(np.arange(len(names)), values, width=0.5, color=[COLORS[n] for n in names],
                   edgecolor="white", linewidth=0.3)
    top = max(values) or 1
    ax.set_ylim(0, top * 1.25)
    style(ax, names, title, ylabel)
    for rect, v in zip(rects, values):
        ax.text(rect.get_x() + rect.get_width() / 2, v + top * 0.02, fmt(v), ha="center", fontsize=9, color="white")
    return rects


def main():
    data, systems = load(SRC)
    names = [n for n in LABELS if n in systems]
    plt.style.use("dark_background")
    fig, axes = plt.subplots(1, 4, figsize=(22, 6.5))
    fig.suptitle(f"SecOps Architectures: {data['n_cases']} cases x {data['runs']} run(s), "
                 f"{data['generated_at'][:10]}", fontsize=16, fontweight="bold", color="#f1c40f", y=0.98)

    x, w = np.arange(len(names)), 0.32
    p50, p95 = [systems[n]["p50"] for n in names], [systems[n]["p95"] for n in names]
    axes[0].bar(x - w / 2, p50, w, label="p50", color="#00d2d3")
    axes[0].bar(x + w / 2, p95, w, label="p95", color="#ff6b6b")
    axes[0].set_ylim(0, max(p95) * 1.25)
    axes[0].legend(frameon=False)
    style(axes[0], names, "Latency (seconds)", "Seconds")

    bars(axes[1], names, [systems[n]["tokens_mean"] for n in names], "Mean tokens per request", "Tokens",
         lambda v: f"{v:.0f}")
    rects = bars(axes[2], names, [systems[n]["calls_mean"] for n in names], "Mean tool calls per request",
                 "Tool calls", lambda v: f"{v:.1f}")
    if "solo" in systems and "hybrid" in systems and systems["solo"]["calls_mean"] > 0:
        pct = (systems["solo"]["calls_mean"] - systems["hybrid"]["calls_mean"]) / systems["solo"]["calls_mean"] * 100
        bar = rects[names.index("hybrid")]
        axes[2].text(bar.get_x() + bar.get_width() / 2, bar.get_height() / 2 + 0.02,
                     f"{abs(pct):.0f}% {'fewer' if pct >= 0 else 'more'}\ncalls than solo",
                     ha="center", va="center", fontsize=8.5, fontweight="bold")
    bars(axes[3], names, [100 * systems[n]["verdict_ok"] / systems[n]["n"] for n in names],
         "Verdict accuracy", "% of requests correct", lambda v: f"{v:.0f}%")

    plt.tight_layout(rect=[0, 0, 1, 0.93])
    plt.savefig(OUT, dpi=300, bbox_inches="tight")
    print(f"Infographic exported to: {OUT}")


if __name__ == "__main__":
    main()