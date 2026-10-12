"""Prepare a review-required task draft from a fixture and an inspectable trace.

No executable content is run. This does not recover a model response or replay tools.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

from evidence_check import check


def draft(trace: Path, task_path: Path, results: Path, out: Path) -> dict:
    report = check(trace, task_path, results)
    if report["operations"]["inspect_retrieval"]["status"] != "ready":
        raise ValueError("Cannot draft: retrieval I/O evidence incomplete: " +
                         "; ".join(report["operations"]["inspect_retrieval"]["blockers"]))
    if not report["capture"]["matched_result"] or not report["capture"]["task_fixture"]:
        raise ValueError("Cannot draft: task fixture or matching evaluation result missing")
    matching = [r for r in json.loads(results.read_text(encoding="utf-8")).get("results", [])
                if r.get("trace_id") == report["trace_id"]]
    if len(matching) != 1 or matching[0].get("passed") is not False:
        raise ValueError("Cannot draft: expected one matching failed evaluation outcome")
    original = yaml.safe_load(task_path.read_text(encoding="utf-8"))
    # Preserve the authored task; drop the scripted trajectory. A human must review
    # ground truth before a live-provider run. Never reinterpret the failure as a goal.
    task = {key: original[key] for key in ("id", "description", "prompt", "workspace", "approver", "max_steps", "expect") if key in original}
    task["id"] += "-review-draft"
    out.mkdir(parents=True, exist_ok=False)
    (out / "task.yaml").write_text(yaml.safe_dump(task, sort_keys=False), encoding="utf-8")
    metadata = {
        "review_status": "pending", "source_trace_id": report["trace_id"],
        "source_trace": str(trace), "source_task": str(task_path),
        "runnable": False,
        "review_checklist": [
            "Confirm task input and expected key/citation against independent ground truth",
            "Confirm fixture corpus reflects the intended starting environment",
            "Select live provider and tool fixture; this draft has no scripted trajectory",
            "Pin task/scorer revision and acceptance protocol before experiments",
        ],
    }
    (out / "REVIEW.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path)
    parser.add_argument("--task", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True, help="New directory, not overwritten")
    args = parser.parse_args()
    print(json.dumps(draft(args.trace, args.task, args.results, args.out), indent=2))


if __name__ == "__main__":
    main()
