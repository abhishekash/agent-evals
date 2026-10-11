"""Runner: execute task suites through agent-harness and score them.

Deterministic mode (default): tasks carry a `script` for the ScriptedProvider —
the loop, tools, and HITL gates are exercised offline, reproducibly.
Live mode: pass a provider factory with a real provider (same scorers, real model).
"""
from __future__ import annotations

import json
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from agent_harness.agent import Agent
from agent_harness.hitl import (
    ApprovalPolicy,
    ApprovalRecord,
    AutoApprover,
    CallbackApprover,
    Decision,
    DenyAllApprover,
)
from agent_harness.providers import ScriptedProvider
from agent_harness.providers.mock import call_tool, say
from agent_harness.tools import default_tools
from agent_harness.tracing import init_tracing, load_spans
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
    cost_known: bool = True
    approvals: int = 0
    stopped_reason: str = ""
    trace_id: str = ""
    duration_s: float = 0.0
    repeat: int = 1
    provider_model: str = ""
    error: str = ""

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
        spec = task.approver[len("edit:"):].strip()
        # Legacy edit:<JSON> tasks mean a write_file edit. New tasks can name
        # the target explicitly: edit:<tool>:<JSON>. Never apply one tool's
        # arguments to another tool or auto-approve an unrelated side effect.
        target = "write_file"
        if not spec.startswith("{"):
            target, separator, spec = spec.partition(":")
            if not separator or not target:
                raise ValueError(f"task {task.id}: expected edit:<tool>:<JSON object>")
        edited = json.loads(spec)
        if not isinstance(edited, dict):
            raise ValueError(f"task {task.id}: edited arguments must be a JSON object")

        def review(request):
            if request.tool_name != target:
                return ApprovalRecord(
                    request,
                    Decision.DENY,
                    approver="edit-fixture",
                    rationale=(
                        f"this fixture only permits edits to {target}; "
                        "use read-only tools for inspection or stop"
                    ),
                )
            return ApprovalRecord(
                request,
                Decision.EDIT,
                approver="edit-fixture",
                rationale=f"fixture edited {target} arguments",
                edited_arguments=dict(edited),
            )

        return CallbackApprover(review, name="edit-fixture")
    raise ValueError(f"task {task.id}: unknown approver {task.approver!r}")


def run_task(
    task: Task,
    traces_dir: Path,
    provider=None,
    *,
    provider_factory: Callable[[], Any] | None = None,
    repeat: int = 1,
    cost_table: dict[str, tuple[float, float]] | None = None,
) -> EvalResult:
    """Run one task in an isolated workspace; score it; return everything.

    ``provider_factory`` is preferred for live evaluation so every repetition
    gets a fresh provider/client. The scripted default remains deterministic.
    """
    if repeat < 1:
        raise ValueError("repeat must be at least 1")
    trace_name = f"{task.id}.jsonl" if repeat == 1 else f"{task.id}.repeat-{repeat}.jsonl"
    trace_path = traces_dir / trace_name
    tp = init_tracing(trace_path, service_name="agent-evals")
    started = time.perf_counter()
    run_provider = None
    provider_model = "unknown"
    try:
        run_provider = provider_factory() if provider_factory is not None else (provider or _build_provider(task))
        provider_model = getattr(run_provider, "model", "unknown")
        with tempfile.TemporaryDirectory() as ws:
            workspace = Path(ws)
            _materialize_workspace(workspace, task.workspace)
            agent = Agent(
                run_provider,
                default_tools(workspace),
                approver=_build_approver(task),
                policy=ApprovalPolicy.default(),
                tracer_provider=tp,
                max_steps=task.max_steps,
                cost_table=cost_table,
            )
            result = agent.run(task.prompt)
            tp.force_flush()

            spans = [s for s in load_spans(trace_path) if s["trace_id"] == result.trace_id]
            ctx = RunContext(result=result, workspace=workspace, spans=spans)
            scores = [score(ctx, spec) for spec in task.expect]
            run_error = (
                result.answer
                if result.stopped_reason in {"error", "checkpoint_error", "context_error"}
                else ""
            )
            if run_error:
                scores.append(Score("run_error", False, run_error))

        return EvalResult(
            task_id=task.id,
            passed=all(s.passed for s in scores),
            scores=scores,
            steps=result.steps,
            tokens=result.usage.total,
            cost_usd=result.cost_usd,
            cost_known=result.cost_known,
            approvals=len(result.approvals),
            stopped_reason=result.stopped_reason,
            trace_id=result.trace_id,
            duration_s=round(time.perf_counter() - started, 3),
            repeat=repeat,
            provider_model=provider_model,
            error=run_error,
        )
    except Exception as exc:
        tp.force_flush()
        spans = load_spans(trace_path) if trace_path.exists() else []
        trace_id = next((s["trace_id"] for s in spans if s["name"] == "agent.run"), "")
        detail = f"{type(exc).__name__}: {exc}"
        return EvalResult(
            task_id=task.id,
            passed=False,
            scores=[Score("run_error", False, detail)],
            stopped_reason="error",
            trace_id=trace_id,
            duration_s=round(time.perf_counter() - started, 3),
            repeat=repeat,
            provider_model=provider_model,
            cost_known=False,
            error=detail,
        )


def run_suite(
    tasks: list[Task],
    traces_dir: Path,
    *,
    provider_factory: Callable[[], Any] | None = None,
    repeats: int = 1,
    cost_table: dict[str, tuple[float, float]] | None = None,
) -> list[EvalResult]:
    if repeats < 1:
        raise ValueError("repeats must be at least 1")
    traces_dir.mkdir(parents=True, exist_ok=True)
    results: list[EvalResult] = []
    for repeat in range(1, repeats + 1):
        for task in tasks:
            results.append(
                run_task(
                    task,
                    traces_dir,
                    provider_factory=provider_factory,
                    repeat=repeat,
                    cost_table=cost_table,
                )
            )
    return results
