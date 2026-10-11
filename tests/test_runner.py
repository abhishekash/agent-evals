from pathlib import Path

from agent_harness.types import AssistantMessage, Usage

from agent_evals.report import render_markdown_table, write_results_json, write_results_md
from agent_evals.runner import run_task, run_suite
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
