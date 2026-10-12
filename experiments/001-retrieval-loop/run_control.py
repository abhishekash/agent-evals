"""Offline failing/passing controls, not evidence of a live-model fix."""
from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import replace
from pathlib import Path

from agent_evals.report import write_results_json, write_results_md
from agent_evals.runner import run_suite
from agent_evals.tasks import load_tasks

HERE = Path(__file__).resolve().parent


def control_tasks():
    baseline = load_tasks(HERE / "tasks")[0]
    candidate = replace(
        baseline,
        script=[
            {"tool_call": {"name": "read_file", "args": {"path": "docs/index.md"}}},
            {"tool_call": {"name": "read_file", "args": {"path": "docs/timeouts.md"}}},
            {"say": "KEY=client.request_timeout_ms; SOURCE=atlas-timeouts-v1"},
        ],
    )
    return baseline, candidate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="New output directory (never overwritten)")
    parser.add_argument("--repeats", type=int, default=1, help="Offline controls only; use 20 for protocol check")
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be positive")
    args.out.mkdir(parents=True, exist_ok=False)
    results = []
    for label, task in zip(("baseline", "passing-control"), control_tasks()):
        directory = args.out / label
        batch = run_suite([task], directory / "traces", repeats=args.repeats, capture_tool_io=True)
        write_results_json(batch, directory / "results.json", "scripted")
        write_results_md(batch, directory / "RESULTS.md", "scripted")
        manifest = {
            "protocol_revision": "retrieval-pilot-v1", "task_revision": task.id,
            "scorer_revision": "exact-key-citation-v1", "runtime": "agent-harness",
            "model": "scripted", "treatment": label,
            "fixture_sha256": hashlib.sha256(json.dumps(task.workspace, sort_keys=True).encode()).hexdigest(),
        }
        (directory / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        results.append(batch)
        print(f"{label}: {sum(r.passed for r in batch)}/{len(batch)} passing")
    baseline, passing = results
    # An infrastructure error is not the expected outcome failure.
    expected = all(
        not r.passed and not r.error and r.stopped_reason == "completed"
        and [s.scorer for s in r.failed_scorers()] == ["answer_regex"] for r in baseline
    ) and all(r.passed for r in passing)
    print("Offline mechanism controls only; no live-model improvement claim.")
    return 0 if expected else 1


if __name__ == "__main__":
    raise SystemExit(main())
