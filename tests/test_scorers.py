from pathlib import Path

from agent_harness.agent import Agent
from agent_harness.hitl import AutoApprover
from agent_harness.providers import say, scripted_run
from agent_harness.tools import default_tools
from agent_harness.tracing import init_tracing, load_spans

from agent_evals.scorers import RunContext, registered, score


def context(tmp_path):
    trace_path = tmp_path / "trace.jsonl"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "out.txt").write_text("alpha\nbeta\n")
    provider = scripted_run(say("completed successfully"))
    tp = init_tracing(trace_path)
    result = Agent(
        provider,
        default_tools(workspace),
        approver=AutoApprover(),
        tracer_provider=tp,
    ).run("task")
    tp.force_flush()
    return RunContext(result=result, workspace=workspace, spans=load_spans(trace_path))


def test_registered_scorers_are_explicit():
    names = registered()
    assert "answer_contains" in names
    assert "hitl_event_present" in names
    assert "llm_judge" not in names  # deterministic-first by design


def test_answer_and_filesystem_scorers(tmp_path):
    ctx = context(tmp_path)
    assert score(ctx, {"type": "answer_contains", "value": "completed"}).passed
    assert score(ctx, {"type": "file_exists", "value": "out.txt"}).passed
    assert score(ctx, {"type": "file_contains", "value": "out.txt", "pattern": "alpha.*beta"}).passed
    assert score(ctx, {"type": "file_not_exists", "value": "missing.txt"}).passed


def test_budget_and_unknown_scorers(tmp_path):
    ctx = context(tmp_path)
    assert score(ctx, {"type": "max_steps", "value": 1}).passed
    assert score(ctx, {"type": "max_tokens", "value": 300}).passed
    unknown = score(ctx, {"type": "not_a_real_scorer"})
    assert not unknown.passed
    assert "unknown scorer" in unknown.detail
