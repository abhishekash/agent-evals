"""Runner: execute task suites through agent-harness and score them.

Deterministic mode (default): tasks carry a `script` for the ScriptedProvider —
the loop, tools, and HITL gates are exercised offline, reproducibly.
Live mode: pass --live with a real provider (same scorers, real model).
"""
from __future__ import annotations

import json
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent_harness.agent import Agent, RunResult
from agent_harness.hitl import ApprovalPolicy, AutoApprover, CallbackApprover, Decision, DenyAllApprover
from agent_harness.providers import ScriptedProvider
from agent_harness.providers.mock import call_tool, say
from agent_harness.tools import default_tools
from agent_harness.tracing import group_traces, init_tracing, load_spans
from agent_harness.types import AssistantMessage

from agent_evals.scorers import RunContext, Score, score
from agent_evals.tasks import Task


@dataclass
class EvalResult:
    task_id: str
    passed: bool
    scores: list[Score] = field(default_factory=list)
    steps: int = 0
    tokens: int = 0
    cost_usd: float = 0.0
    approvals: int = 0
    stopped_reason: str = ""
    trace_id: str = ""
    duration_s: float = 0.0

    def failed_scorers(self) -> list[Score]:
        return [s for s in self.scores if not s.passed]


def _materialize_workspace(root: Path, files: dict[str, str]) -> None:
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def _build_provider(task: Task) -> ScriptedProvider:
    script: list[AssistantMessage] = []
    for turn in task.script:
        if "tool_call" in turn:
            spec = turn["tool_call"]
            script.append(call_tool(spec["name"], spec.get("args", {}), content=turn.get("content", "")))
        elif "say" in turn:
            script.append(say(turn["say"]))
        else:
            raise ValueError(f"task {task.id}: unknown script turn {turn!r}")
    return ScriptedProvider(script)


def _build_approver(task: Task):
    if task.approver == "auto":
        return AutoApprover()
    if task.approver == "deny-all":
        return DenyAllApprover()
    if task.approver.startswith("edit:"):
        edited = json.loads(task.approver[len("edit:"):])
        return CallbackApprover(lambda req, e=edited: (Decision.EDIT, e), name="edit-fixture")
    raise ValueError(f"task {task.id}: unknown approver {task.approver!r}")


def run_task(task: Task, traces_dir: Path, provider=None) -> EvalResult:
    """Run one task in an isolated workspace; score it; return everything."""
    trace_path = traces_dir / f"{task.id}.jsonl"
    tp = init_tracing(trace_path, service_name="agent-evals")
    started = time.perf_counter()
    with tempfile.TemporaryDirectory() as ws:
        workspace = Path(ws)
        _materialize_workspace(workspace, task.workspace)
        agent = Agent(
            provider or _build_provider(task),
            default_tools(workspace),
            approver=_build_approver(task),
            policy=ApprovalPolicy.default(),
            tracer_provider=tp,
            max_steps=task.max_steps,
        )
        result = agent.run(task.prompt)
        tp.force_flush()

        spans = [s for s in load_spans(trace_path) if s["trace_id"] == result.trace_id]
        ctx = RunContext(result=result, workspace=workspace, spans=spans)
        scores = [score(ctx, spec) for spec in task.expect]

    return EvalResult(
        task_id=task.id,
        passed=all(s.passed for s in scores),
        scores=scores,
        steps=result.steps,
        tokens=result.usage.total,
        cost_usd=result.cost_usd,
        approvals=len(result.approvals),
        stopped_reason=result.stopped_reason,
        trace_id=result.trace_id,
        duration_s=round(time.perf_counter() - started, 3),
    )


def run_suite(tasks: list[Task], traces_dir: Path) -> list[EvalResult]:
    traces_dir.mkdir(parents=True, exist_ok=True)
    return [run_task(t, traces_dir) for t in tasks]
