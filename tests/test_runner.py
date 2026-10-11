from dataclasses import replace
from pathlib import Path

import pytest

from agent_harness.hitl import ApprovalRequest, Decision
from agent_harness.providers import call_tool, say, scripted_run
from agent_harness.tracing import load_spans
from agent_harness.types import AssistantMessage, Risk, Usage

from agent_evals.report import render_markdown_table, write_results_json, write_results_md
from agent_evals.runner import _build_approver, run_task, run_suite
from agent_evals.tasks import load_tasks


def test_happy_task_runs_and_writes_trace(tmp_path):
    task = next(t for t in load_tasks("tasks") if t.id == "summarize-notes")
    results = run_task(task, tmp_path / "traces")
    assert results.passed
    assert results.steps == 4
    assert results.approvals == 1
    assert (tmp_path / "traces" / "summarize-notes.jsonl").exists()
    assert all(s.passed for s in results.scores)


def test_denied_task_proves_safety(tmp_path):
    task = next(t for t in load_tasks("tasks") if t.id == "denied-write")
    result = run_task(task, tmp_path / "traces")
    assert result.passed
    assert result.approvals == 1
    assert result.trace_id


@pytest.mark.parametrize(
    "approver",
    [
        'edit:{"path": "safe.txt", "content": "approved"}',
        'edit:write_file:{"path": "safe.txt", "content": "approved"}',
    ],
)
def test_edit_fixture_targets_write_and_denies_other_gated_tools(approver):
    task = next(t for t in load_tasks("tasks") if t.id == "edited-write")
    reviewer = _build_approver(replace(task, approver=approver))
    shell = reviewer.review(ApprovalRequest("run_shell", Risk.EXECUTE, {"command": "ls"}, "inspect"))
    assert shell.decision is Decision.DENY
    assert shell.edited_arguments is None
    assert "only permits edits to write_file" in shell.rationale
    write = reviewer.review(
        ApprovalRequest("write_file", Risk.WRITE, {"path": "requested.txt", "content": "x"}, "write")
    )
    assert write.decision is Decision.EDIT
    assert write.edited_arguments == {"path": "safe.txt", "content": "approved"}


def test_edit_fixture_rejects_non_object_arguments():
    task = next(t for t in load_tasks("tasks") if t.id == "edited-write")
    with pytest.raises(ValueError, match="JSON object"):
        _build_approver(replace(task, approver="edit:write_file:[]"))


def _inspection_then_write_provider():
    return scripted_run(
        call_tool("run_shell", {"command": "cat input.txt"}),
        call_tool("read_file", {"path": "input.txt"}),
        call_tool("write_file", {"path": "requested.txt", "content": "original proposal"}),
        say("Wrote the human-approved content to safe.txt."),
    )


def test_edit_fixture_allows_recovery_and_a_final_answer(tmp_path):
    task = next(t for t in load_tasks("tasks") if t.id == "edited-write")
    result = run_task(task, tmp_path / "traces", provider=_inspection_then_write_provider())
    assert result.passed
    assert result.steps == 4
    assert result.stopped_reason == "completed"
    spans = load_spans(tmp_path / "traces" / "edited-write.jsonl")
    shell = next(span for span in spans if span["attributes"].get("tool.name") == "run_shell")
    assert shell["attributes"]["tool.result_status"] == "denied"
    assert "tool.duration_ms" not in shell["attributes"]  # the command never executed
    assert "bad_edited_arguments" != shell["attributes"].get("tool.error")
    assert any(s.scorer == "edited" and s.passed for s in result.scores)


def test_written_file_does_not_make_an_incomplete_run_pass(tmp_path):
    task = next(t for t in load_tasks("tasks") if t.id == "edited-write")
    result = run_task(
        replace(task, max_steps=3),
        tmp_path / "traces",
        provider=_inspection_then_write_provider(),
    )
    assert not result.passed
    assert result.stopped_reason == "max_steps"
    assert any(s.scorer == "file_contains" and s.passed for s in result.scores)
    assert any(s.scorer == "stopped_reason" and not s.passed for s in result.scores)


def test_live_provider_factory_is_repeated_per_run(tmp_path):
    task = next(t for t in load_tasks("tasks") if t.id == "token-budget")
    calls = []

    class FakeLiveProvider:
        model = "fake-live"

        def complete(self, messages, tools):
            calls.append(1)
            return AssistantMessage("Hello — completed", usage=Usage(2, 3))

    results = run_suite(
        [task],
        tmp_path / "traces",
        provider_factory=FakeLiveProvider,
        repeats=2,
        cost_table={"fake-live": (1.0, 2.0)},
    )

    assert all(result.passed for result in results)
    assert len(calls) == 2
    assert {result.provider_model for result in results} == {"fake-live"}
    assert all(result.cost_usd == 0.000008 for result in results)


def test_unknown_pricing_is_reported_as_unknown(tmp_path):
    task = next(t for t in load_tasks("tasks") if t.id == "token-budget")

    class UnpricedProvider:
        model = "unpriced-model"

        def complete(self, messages, tools):
            return AssistantMessage("Hello — completed", usage=Usage(2, 3))

    result = run_task(task, tmp_path / "traces", provider=UnpricedProvider())
    assert result.passed
    assert not result.cost_known
    payload = write_results_json([result], tmp_path / "results.json", "unpriced-model")
    assert payload["summary"]["total_cost_usd"] is None
    assert "unknown" in render_markdown_table([result])


def test_repeated_suite_reports_rates_cost_and_latency(tmp_path):
    task = next(t for t in load_tasks("tasks") if t.id == "token-budget")
    results = run_suite([task], tmp_path / "traces", repeats=2)

    assert len(results) == 2
    assert all(result.passed for result in results)
    assert (tmp_path / "traces" / "token-budget.jsonl").exists()
    assert (tmp_path / "traces" / "token-budget.repeat-2.jsonl").exists()
    payload = write_results_json(results, tmp_path / "results.json", "scripted")
    assert payload["summary"]["pass_rate"] == 1.0
    assert payload["summary"]["p95_latency_s"] >= 0


def test_suite_and_reports(tmp_path):
    tasks = [t for t in load_tasks("tasks") if t.id in {"token-budget", "unknown-tool-recovery"}]
    results = run_suite(tasks, tmp_path / "traces")
    assert len(results) == 2
    assert all(r.passed for r in results)
    table = render_markdown_table(results)
    assert "token-budget" in table and "2/2 passing" in table
    payload = write_results_json(results, tmp_path / "results.json", "test")
    assert payload["passed"] == 2
    write_results_md(results, tmp_path / "RESULTS.md", "test")
    assert (tmp_path / "RESULTS.md").exists()
