from pathlib import Path

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
