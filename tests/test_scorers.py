from pathlib import Path

from agent_harness.agent import Agent
from agent_harness.hitl import ApprovalRecord, ApprovalRequest, AutoApprover, Decision
from agent_harness.providers import say, scripted_run
from agent_harness.tools import default_tools
from agent_harness.tracing import init_tracing, load_spans
from agent_harness.types import Risk

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


def test_edited_scorer_requires_a_real_change_to_the_correct_tool(tmp_path):
    ctx = context(tmp_path)
    request = ApprovalRequest(
        "write_file", Risk.WRITE, {"path": "requested.txt", "content": "x"}, "write"
    )
    ctx.result.approvals = [ApprovalRecord(request, Decision.APPROVE, "fixture")]
    spec = {"type": "edited", "tool": "write_file"}
    assert not score(ctx, spec).passed
    ctx.result.approvals = [
        ApprovalRecord(request, Decision.EDIT, "fixture", edited_arguments=dict(request.arguments))
    ]
    assert not score(ctx, spec).passed
    ctx.result.approvals[0].edited_arguments = {"path": "safe.txt", "content": "x"}
    assert score(ctx, spec).passed
    assert not score(ctx, {"type": "edited", "tool": "run_shell"}).passed


def test_hitl_event_can_be_scoped_to_tool_and_decision(tmp_path):
    ctx = context(tmp_path)
    ctx.spans = [{
        "attributes": {"tool.name": "run_shell"},
        "events": [{"name": "hitl.decision", "attributes": {"hitl.decision": "edit"}}],
    }]
    assert score(ctx, {"type": "hitl_event_present"}).passed
    spec = {"type": "hitl_event_present", "tool": "write_file", "decision": "edit"}
    assert not score(ctx, spec).passed
    ctx.spans[0]["attributes"]["tool.name"] = "write_file"
    assert score(ctx, spec).passed
    ctx.spans[0]["events"][0]["attributes"]["hitl.decision"] = "approve"
    assert not score(ctx, spec).passed


def test_budget_and_unknown_scorers(tmp_path):
    ctx = context(tmp_path)
    assert score(ctx, {"type": "max_steps", "value": 1}).passed
    assert score(ctx, {"type": "max_tokens", "value": 300}).passed
    unknown = score(ctx, {"type": "not_a_real_scorer"})
    assert not unknown.passed
    assert "unknown scorer" in unknown.detail
