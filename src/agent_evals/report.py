"""Reports for deterministic and repeated live evaluations."""
from __future__ import annotations

from collections import defaultdict
import json
from dataclasses import asdict
from pathlib import Path
import statistics
import time
from typing import Any

from agent_evals.runner import EvalResult


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, round((len(ordered) - 1) * percentile))
    return ordered[index]


def summarize_results(results: list[EvalResult]) -> dict[str, Any]:
    passed = sum(1 for result in results if result.passed)
    costs = [result.cost_usd for result in results]
    durations = [result.duration_s for result in results]
    failures = [result for result in results if not result.passed]
    by_task: dict[str, list[EvalResult]] = defaultdict(list)
    for result in results:
        by_task[result.task_id].append(result)
    return {
        "passed": passed,
        "total": len(results),
        "pass_rate": round(passed / len(results), 4) if results else 0.0,
        "failures": len(failures),
        "total_cost_usd": round(sum(costs), 8),
        "mean_cost_usd": round(statistics.mean(costs), 8) if costs else 0.0,
        "mean_latency_s": round(statistics.mean(durations), 4) if durations else 0.0,
        "p50_latency_s": round(_percentile(durations, 0.50), 4),
        "p95_latency_s": round(_percentile(durations, 0.95), 4),
        "tasks": {
            task_id: {
                "passed": sum(1 for result in task_results if result.passed),
                "total": len(task_results),
                "pass_rate": round(
                    sum(1 for result in task_results if result.passed) / len(task_results),
                    4,
                ),
                "total_cost_usd": round(sum(result.cost_usd for result in task_results), 8),
                "mean_latency_s": round(
                    statistics.mean(result.duration_s for result in task_results), 4
                ),
                "failures": [
                    {
                        "repeat": result.repeat,
                        "error": result.error,
                        "failed_scorers": [score.scorer for score in result.failed_scorers()],
                    }
                    for result in task_results
                    if not result.passed
                ],
            }
            for task_id, task_results in sorted(by_task.items())
        },
    }


def write_results_json(results: list[EvalResult], path: Path, provider_label: str) -> dict:
    summary = summarize_results(results)
    payload = {
        "provider": provider_label,
        "generated_unix": time.time(),
        "passed": summary["passed"],
        "total": summary["total"],
        "summary": summary,
        "results": [
            {
                **{k: v for k, v in asdict(result).items() if k != "scores"},
                "scores": [asdict(score) for score in result.scores],
            }
            for result in results
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def render_markdown_table(results: list[EvalResult]) -> str:
    lines = [
        "| Run | Task | Result | Steps | Tokens | Cost | Latency | Approvals | Stop | Failures |",
        "|---:|---|---|---:|---:|---:|---:|---:|---|---|",
    ]
    for result in results:
        mark = "✅" if result.passed else "❌"
        failed = "; ".join(
            f"{score.scorer}: {score.detail}" for score in result.failed_scorers()
        ) or "—"
        lines.append(
            f"| {result.repeat} | `{result.task_id}` | {mark} | {result.steps} | "
            f"{result.tokens} | ${result.cost_usd:.4f} | {result.duration_s:.3f}s | "
            f"{result.approvals} | {result.stopped_reason} | {failed} |"
        )
    summary = summarize_results(results)
    lines.append(
        f"\n**{summary['passed']}/{summary['total']} passing "
        f"({summary['pass_rate']:.1%}) · "
        f"${summary['total_cost_usd']:.4f} total · "
        f"{summary['mean_latency_s']:.3f}s mean / "
        f"{summary['p95_latency_s']:.3f}s p95 · "
        f"{summary['failures']} failures**"
    )
    return "\n".join(lines)


def write_results_md(results: list[EvalResult], path: Path, provider_label: str) -> None:
    summary = summarize_results(results)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"## Latest results — provider: `{provider_label}`\n\n"
        f"- Pass rate: **{summary['passed']}/{summary['total']} ({summary['pass_rate']:.1%})**\n"
        f"- Cost: **${summary['total_cost_usd']:.4f} total** / ${summary['mean_cost_usd']:.4f} mean run\n"
        f"- Latency: **{summary['mean_latency_s']:.3f}s mean**, {summary['p50_latency_s']:.3f}s p50, {summary['p95_latency_s']:.3f}s p95\n"
        f"- Failures: **{summary['failures']}**\n\n"
        + render_markdown_table(results)
        + "\n",
        encoding="utf-8",
    )
