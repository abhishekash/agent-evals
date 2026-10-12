"""Run the two-runtime scripted vertical slice end to end, without provider calls."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from bundle_helper import export, readiness

HERE = Path(__file__).resolve().parent


def command(script: str, *args: str) -> str:
    proc = subprocess.run([sys.executable, str(HERE / script), *args], capture_output=True, text=True)
    if proc.returncode:
        raise RuntimeError(f"{script} failed ({proc.returncode}):\n{proc.stdout}\n{proc.stderr}")
    return proc.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="New output directory, never overwritten")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    summary = {"scope": "scripted offline controls; not live-model evidence", "runtimes": {}}
    for runtime, script in (("harness", "run_control.py"), ("langgraph", "run_langgraph_control.py")):
        root = args.out / runtime
        command(script, "--out", str(root), "--repeats", "20")
        baseline = root / "baseline"
        candidate = root / "passing-control"
        trace = (baseline / "traces/retrieval-loop-v1.jsonl" if runtime == "harness"
                 else baseline / "trial-1/trace.jsonl")
        # The harness first repetition is written as <task>.jsonl.
        trial_results = baseline / "results.json"
        inspection = json.loads(command("evidence_check.py", str(trace), "--task", str(HERE / "tasks/retrieval-loop.yaml"),
                                        "--results", str(trial_results)))
        if inspection["operations"]["inspect_retrieval"]["status"] != "ready":
            raise RuntimeError(f"{runtime}: retrieval inspection is not ready")
        draft_dir = root / "review-draft"
        command("draft_regression.py", str(trace), "--task", str(HERE / "tasks/retrieval-loop.yaml"),
                "--results", str(trial_results), "--out", str(draft_dir))
        decision = json.loads(command("compare_experiment.py", "--protocol", str(HERE / "protocol.json"),
                                      "--baseline", str(baseline), "--candidate", str(candidate)))
        if decision["decision"] != "mechanism_only":
            raise RuntimeError(f"{runtime}: scripted comparison must remain mechanism_only")
        task_path = HERE / "tasks/retrieval-loop.yaml"
        bundles = {}
        for label, source in (("baseline", baseline), ("passing-control", candidate)):
            first_trace = (source / "traces/retrieval-loop-v1.jsonl" if runtime == "harness"
                           else source / "trial-1/trace.jsonl")
            bundles[label] = root / f"{label}-bundle"
            export(bundles[label], first_trace, task_path, source / "results.json",
                   source / "manifest.json", HERE / "protocol.json" if label == "baseline" else None)
        bundle_report = readiness(bundles["baseline"], bundles["baseline"], bundles["passing-control"])
        if (bundle_report["operations"]["inspect_retrieval"]["status"] != "ready"
                or bundle_report["operations"]["draft_regression"]["status"] != "conditional"
                or bundle_report["operations"]["compare_experiments"].get("decision") != "mechanism_only"):
            raise RuntimeError(f"{runtime}: bundle readiness did not match controlled evidence")
        summary["runtimes"][runtime] = {
            "inspection": inspection["operations"],
            "bundle_readiness": bundle_report["operations"],
            "draft_review_status": json.loads((draft_dir / "REVIEW.json").read_text())["review_status"],
            "comparison": decision,
        }
    (args.out / "SUMMARY.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
