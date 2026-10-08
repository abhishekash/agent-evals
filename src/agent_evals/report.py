"""Report: EvalResults → results.json + a markdown table for READMEs."""
from __future__ import annotations

import json
import time
from dataclasses import asdict
from pathlib import Path

from agent_evals.runner import EvalResult


def write_results_json(results: list[EvalResult], path: Path, provider_label: str) -> dict:
    payload = {
        "provider": provider_label,
        "generated_unix": time.time(),
        "passed": sum(1 for r in results if r.passed),
        "total": len(results),
        "results": [
            {
                **{k: v for k, v in asdict(r).items() if k != "scores"},
                "scores": [asdict(s) for s in r.scores],
            }
            for r in results
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def render_markdown_table(results: list[EvalResult]) -> str:
    lines = [
        "| Task | Result | Steps | Tokens | Approvals | Stop | Failed scorers |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in results:
        mark = "✅" if r.passed else "❌"
        failed = "; ".join(f"{s.scorer}: {s.detail}" for s in r.failed_scorers()) or "—"
        lines.append(
            f"| `{r.task_id}` | {mark} | {r.steps} | {r.tokens} | {r.approvals} | {r.stopped_reason} | {failed} |"
        )
    passed = sum(1 for r in results if r.passed)
    lines.append(f"\n**{passed}/{len(results)} passing**")
    return "\n".join(lines)


def write_results_md(results: list[EvalResult], path: Path, provider_label: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"## Latest results — provider: `{provider_label}`\n\n"
        + render_markdown_table(results)
        + "\n",
        encoding="utf-8",
    )
