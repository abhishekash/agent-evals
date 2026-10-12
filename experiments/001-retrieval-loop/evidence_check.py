"""Offline evidence inventory for the retrieval fixture; not a portable contract.

Never executes captured content. Reports what the native span export actually contains,
not what the scripted provider or fixture could theoretically reconstruct.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml


def check(trace_path: Path, task_path: Path | None = None, results_path: Path | None = None) -> dict:
    spans = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    roots = [s for s in spans if s.get("name") == "agent.run"]
    calls = [s for s in spans if s.get("name") == "tool.call"]
    call_ids = [s.get("attributes", {}).get("tool.call_id") for s in calls]
    has_calls = bool(calls) and all(call_ids) and len(set(call_ids)) == len(call_ids)
    # Full successful I/O is opt-in. A truncated value is not enough to prove overlap.
    # Do not infer per-call data from a static YAML script.
    arguments = bool(calls) and all(
        "tool.arguments" in s.get("attributes", {})
        and not s["attributes"].get("tool.arguments_truncated", False)
        for s in calls
    )
    outputs = bool(calls) and all(
        "tool.result" in s.get("attributes", {})
        and not s["attributes"].get("tool.result_truncated", False)
        and s["attributes"].get("tool.result_status") == "ok"
        for s in calls
    )
    trace_id = roots[0].get("trace_id") if len(roots) == 1 else None
    valid_trace = bool(trace_id) and has_calls and all(s.get("trace_id") == trace_id for s in calls)

    task = yaml.safe_load(task_path.read_text(encoding="utf-8")) if task_path else None
    fixture = isinstance(task, dict) and bool(task.get("prompt")) and bool(task.get("workspace"))
    expectations = isinstance(task, dict) and bool(task.get("expect"))
    results = json.loads(results_path.read_text(encoding="utf-8")) if results_path else None
    matched_result = bool(results) and trace_id is not None and sum(
        r.get("trace_id") == trace_id for r in results.get("results", [])
    ) == 1

    inspect = []
    if not valid_trace:
        inspect.append("Missing a unique agent.run trace with correlated, distinct tool-call IDs")
    if not arguments:
        inspect.append("Trace omits or truncates tool-call arguments; call targets cannot be verified from spans")
    if not outputs:
        inspect.append("Trace omits or truncates successful tool outputs; result overlap cannot be verified from spans")
    draft = []
    if not fixture:
        draft.append("Missing task input and starting workspace fixture")
    if not expectations:
        draft.append("Missing proposed outcome assertions")
    if not matched_result:
        draft.append("Missing evaluation result matched to this trace ID")
    if not arguments or not outputs:
        draft.append("Original tool arguments/outputs incomplete; fixture-backed rerun is not faithful replay")
    if not arguments or not outputs:
        draft.append("Retrieval outputs and arguments must be supplied before drafting")
    draft.append("Engineer review of fixture and expected outcome not recorded")
    compare = ["Missing baseline/candidate repeated trials and predeclared acceptance protocol"]
    if not matched_result:
        compare.append("Missing evaluation result matched to this trace ID")

    return {
        "trace_id": trace_id,
        "tool_calls": len(calls),
        "capture": {
            "call_ids": has_calls,
            "tool_arguments": arguments,
            "tool_outputs": outputs,
            "task_fixture": bool(fixture),
            "matched_result": matched_result,
        },
        "operations": {
            "inspect_retrieval": {"status": "blocked" if inspect else "ready", "blockers": inspect},
            "draft_regression": {"status": "blocked" if not fixture or not expectations or not matched_result or not valid_trace or not arguments or not outputs else "conditional", "blockers": draft},
            "compare_experiments": {"status": "blocked", "blockers": compare},
        },
        "note": "Task script/workspace is separate fixture data, not proof of per-call outputs in the native trace.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path)
    parser.add_argument("--task", type=Path)
    parser.add_argument("--results", type=Path)
    args = parser.parse_args()
    print(json.dumps(check(args.trace, args.task, args.results), indent=2))


if __name__ == "__main__":
    main()
