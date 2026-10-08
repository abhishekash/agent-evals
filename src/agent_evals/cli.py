"""Command line for running the eval suite."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from agent_evals.report import render_markdown_table, write_results_json, write_results_md
from agent_evals.runner import run_suite
from agent_evals.tasks import load_tasks


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agent-evals",
        description="Run deterministic agent tasks through agent-harness and score the traces.",
    )
    parser.add_argument("run", nargs="?", default="run", help="run the task suite")
    parser.add_argument("--tasks", default="tasks", help="directory containing *.yaml tasks")
    parser.add_argument("--out", default="results", help="output directory for traces/results")
    parser.add_argument("--label", default="agent-harness / scripted", help="provider label in reports")
    parser.add_argument("--only", action="append", help="run only this task id (repeatable)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.run != "run":
        raise SystemExit(f"unknown command {args.run!r}; use `agent-evals run`")

    tasks = load_tasks(args.tasks)
    if args.only:
        wanted = set(args.only)
        tasks = [t for t in tasks if t.id in wanted]
        missing = wanted - {t.id for t in tasks}
        if missing:
            raise SystemExit(f"unknown task ids: {sorted(missing)}")
    out = Path(args.out)
    traces_dir = out / "traces"
    results = run_suite(tasks, traces_dir)
    write_results_json(results, out / "results.json", args.label)
    write_results_md(results, out / "RESULTS.md", args.label)

    print(render_markdown_table(results))
    print(f"\nraw results: {out / 'results.json'}", file=sys.stderr)
    print(f"traces:      {traces_dir}", file=sys.stderr)
    return 0 if all(r.passed for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
