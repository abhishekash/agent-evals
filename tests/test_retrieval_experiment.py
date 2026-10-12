"""Keep experimental expected failures outside the default passing task suite."""
import importlib.util
import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from agent_evals.runner import run_task
from agent_harness.tracing import load_spans

EXPERIMENT = Path(__file__).resolve().parents[1] / "experiments/001-retrieval-loop"
spec = importlib.util.spec_from_file_location("retrieval_control", EXPERIMENT / "run_control.py")
control = importlib.util.module_from_spec(spec)
spec.loader.exec_module(control)
checker_spec = importlib.util.spec_from_file_location("retrieval_evidence", EXPERIMENT / "evidence_check.py")
evidence = importlib.util.module_from_spec(checker_spec)
checker_spec.loader.exec_module(evidence)


def test_baseline_fails_on_outcome_not_execution(tmp_path):
    baseline, _ = control.control_tasks()
    result = run_task(baseline, tmp_path)
    assert not result.passed
    assert not result.error
    assert result.stopped_reason == "completed"
    assert [s.scorer for s in result.failed_scorers()] == ["answer_regex"]
    spans = load_spans(tmp_path / f"{baseline.id}.jsonl")
    reads = [s for s in spans if s.get("attributes", {}).get("tool.name") == "read_file"]
    assert len(reads) == 4


def test_passing_control_uses_same_task_and_scorers(tmp_path):
    baseline, passing = control.control_tasks()
    assert replace(passing, script=baseline.script) == baseline
    result = run_task(passing, tmp_path)
    assert result.passed
    assert result.steps == 3


@pytest.mark.parametrize("answer", [
    "KEY=request.timeout; SOURCE=atlas-timeouts-v1",
    "KEY=client.request_timeout_ms; SOURCE=atlas-retries-v1",
    "KEY=client.request_timeout_ms; SOURCE=atlas-timeouts-v1 or another document",
])
def test_incorrect_or_ambiguous_answers_fail(tmp_path, answer):
    _, passing = control.control_tasks()
    task = replace(passing, script=passing.script[:-1] + [{"say": answer}])
    result = run_task(task, tmp_path)
    assert not result.passed
    assert [s.scorer for s in result.failed_scorers()] == ["answer_regex"]


def test_incomplete_run_cannot_pass(tmp_path):
    _, passing = control.control_tasks()
    result = run_task(replace(passing, max_steps=2), tmp_path)
    assert not result.passed
    assert result.stopped_reason == "max_steps"
    assert any(s.scorer == "stopped_reason" for s in result.failed_scorers())


def test_opt_in_trace_supports_retrieval_inspection(tmp_path):
    baseline, _ = control.control_tasks()
    result = run_task(baseline, tmp_path, capture_tool_io=True)
    trace = tmp_path / f"{baseline.id}.jsonl"
    report = evidence.check(trace, EXPERIMENT / "tasks/retrieval-loop.yaml")
    assert result.trace_id == report["trace_id"]
    assert report["operations"]["inspect_retrieval"]["status"] == "ready"
    assert report["capture"]["tool_arguments"]
    assert report["capture"]["tool_outputs"]
    calls = [s for s in load_spans(trace) if s["name"] == "tool.call"]
    assert [json.loads(s["attributes"]["tool.arguments"])["path"] for s in calls] == [
        "docs/index.md", "docs/retries.md", "docs/retries.md", "docs/retries.md"
    ]
    assert calls[1]["attributes"]["tool.result"] == calls[2]["attributes"]["tool.result"]
    assert calls[2]["attributes"]["tool.result"] == calls[3]["attributes"]["tool.result"]


def test_native_trace_readiness_does_not_infer_outputs_from_fixture(tmp_path):
    baseline, _ = control.control_tasks()
    result = run_task(baseline, tmp_path)
    trace = tmp_path / f"{baseline.id}.jsonl"
    from agent_evals.report import write_results_json
    results = tmp_path / "results.json"
    write_results_json([result], results, "scripted")
    full = evidence.check(trace, EXPERIMENT / "tasks/retrieval-loop.yaml", results)
    assert full["tool_calls"] == 4
    assert full["capture"]["call_ids"]
    assert not full["capture"]["tool_arguments"]
    assert not full["capture"]["tool_outputs"]
    assert full["capture"]["matched_result"]
    assert full["operations"]["inspect_retrieval"]["status"] == "blocked"
    assert full["operations"]["draft_regression"]["status"] == "blocked"
    assert full["operations"]["compare_experiments"]["status"] == "blocked"
    incomplete = evidence.check(trace)
    assert incomplete["operations"]["draft_regression"]["status"] == "blocked"
    assert not incomplete["capture"]["matched_result"]


def test_duplicate_result_cannot_establish_regression_provenance(tmp_path):
    baseline, _ = control.control_tasks()
    run = run_task(baseline, tmp_path, capture_tool_io=True)
    from agent_evals.report import write_results_json
    results = tmp_path / "results.json"
    write_results_json([run, run], results, "scripted")
    report = evidence.check(tmp_path / f"{baseline.id}.jsonl", EXPERIMENT / "tasks/retrieval-loop.yaml", results)
    assert not report["capture"]["matched_result"]
    assert report["operations"]["draft_regression"]["status"] == "blocked"


def test_langgraph_controls_produce_real_graph_updates_and_inspectable_spans(tmp_path):
    pytest.importorskip("langgraph")
    spec = importlib.util.spec_from_file_location("retrieval_langgraph", EXPERIMENT / "run_langgraph_control.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    failing = module.run("baseline", ["docs/index.md"] + ["docs/retries.md"] * 3, tmp_path / "baseline")
    passing = module.run("passing-control", ["docs/index.md", "docs/timeouts.md"], tmp_path / "passing")
    assert not failing["passed"] and passing["passed"]
    assert len(json.loads((tmp_path / "baseline/native-updates.json").read_text())) == 5
    report = evidence.check(
        tmp_path / "baseline/trace.jsonl", EXPERIMENT / "tasks/retrieval-loop.yaml",
        tmp_path / "baseline/results.json",
    )
    assert report["operations"]["inspect_retrieval"]["status"] == "ready"
    spans = [s for s in load_spans(tmp_path / "baseline/trace.jsonl") if s["name"] == "tool.call"]
    assert len(spans) == 4
    assert len({s["attributes"]["tool.result"] for s in spans[1:]}) == 1
    # An intentionally incomplete export must not claim retrieval diagnosis.
    incomplete = tmp_path / "incomplete.jsonl"
    all_spans = load_spans(tmp_path / "baseline/trace.jsonl")
    for span in all_spans:
        if span["name"] == "tool.call":
            span["attributes"].pop("tool.result", None)
    incomplete.write_text("\n".join(json.dumps(s) for s in all_spans) + "\n")
    missing = evidence.check(incomplete, EXPERIMENT / "tasks/retrieval-loop.yaml")
    assert missing["operations"]["inspect_retrieval"]["status"] == "blocked"
    assert any("outputs" in b for b in missing["operations"]["inspect_retrieval"]["blockers"])


def test_review_draft_requires_complete_trace_and_records_pending_review(tmp_path):
    baseline, _ = control.control_tasks()
    run = run_task(baseline, tmp_path, capture_tool_io=True)
    from agent_evals.report import write_results_json
    results = tmp_path / "results.json"
    write_results_json([run], results, "scripted")
    trace = tmp_path / f"{baseline.id}.jsonl"
    def execute(trace_path, output):
        return subprocess.run([sys.executable, str(EXPERIMENT / "draft_regression.py"), str(trace_path),
                               "--task", str(EXPERIMENT / "tasks/retrieval-loop.yaml"),
                               "--results", str(results), "--out", str(output)],
                              capture_output=True, text=True, env=os.environ.copy())
    drafted = execute(trace, tmp_path / "draft")
    assert drafted.returncode == 0, drafted.stderr
    metadata = json.loads((tmp_path / "draft/REVIEW.json").read_text())
    assert metadata["review_status"] == "pending" and not metadata["runnable"]
    import yaml
    task = yaml.safe_load((tmp_path / "draft/task.yaml").read_text())
    assert "script" not in task
    assert task["expect"] == yaml.safe_load((EXPERIMENT / "tasks/retrieval-loop.yaml").read_text())["expect"]
    spans = load_spans(trace)
    for span in spans:
        if span["name"] == "tool.call":
            span["attributes"].pop("tool.result", None)
    incomplete = tmp_path / "incomplete.jsonl"
    incomplete.write_text("\n".join(json.dumps(s) for s in spans))
    refused = execute(incomplete, tmp_path / "refused")
    assert refused.returncode != 0
    assert not (tmp_path / "refused").exists()


def test_experiment_comparison_rejects_missing_and_incompatible_trials():
    spec = importlib.util.spec_from_file_location("retrieval_compare", EXPERIMENT / "compare_experiment.py")
    compare_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(compare_module)
    protocol = json.loads((EXPERIMENT / "protocol.json").read_text())
    def records(passes, model="live-model"):
        return {"results": [
            {"task_id": "retrieval-loop-v1", "repeat": i, "passed": i <= passes,
             "duration_s": 1.0, "scores": [{"passed": i <= passes}],
             "trace_id": f"trace-{i}", "provider_model": model, "error": ""}
            for i in range(1, 21)
        ]}
    def manifest(treatment, model="live-model"):
        return {"protocol_revision": "retrieval-pilot-v1", "task_revision": "retrieval-loop-v1",
                "scorer_revision": "exact-key-citation-v1", "runtime": "test-runtime",
                 "model": model, "fixture_sha256": "abc", "treatment": treatment,
                 "tool_schema_sha256": "tools", "model_settings_sha256": "settings",
                 "runtime_version": "1.0", "prompt_sha256": treatment + "-prompt"}
    b, c = manifest("baseline"), manifest("candidate")
    run = compare_module.compare
    live_protocol = dict(protocol, allowed_difference="prompt_sha256")
    assert run(live_protocol, records(12), records(19), b, c)["decision"] == "verified_for_protocol"
    assert run(live_protocol, records(12), records(14), b, c)["decision"] == "not_verified"
    assert run(protocol, records(12), records(19, "scripted"),
               manifest("baseline", "scripted"), manifest("candidate", "scripted"))["decision"] == "mechanism_only"
    missing = records(19)
    missing["results"].pop()
    assert run(live_protocol, records(12), missing, b, c)["decision"] == "insufficient_evidence"
    duplicated = records(19)
    duplicated["results"][1]["repeat"] = 1
    assert run(live_protocol, records(12), duplicated, b, c)["decision"] == "insufficient_evidence"
    wrong = dict(c, scorer_revision="new-scorer")
    assert run(live_protocol, records(12), records(19), b, wrong)["decision"] == "insufficient_evidence"
    inconsistent = records(19)
    inconsistent["results"][0]["error"] = "transport failed"
    assert run(live_protocol, records(12), inconsistent, b, c)["decision"] == "insufficient_evidence"
    timed_out = records(19)
    timed_out["results"][0].update(passed=False, error="timeout", scores=[{"passed": False}])
    assert run(live_protocol, records(12), timed_out, b, c)["decision"] == "verified_for_protocol"
    assert run(protocol, records(12), records(19), b, c)["decision"] == "insufficient_evidence"
    assert run(live_protocol, records(12), records(19), b, dict(c, model_settings_sha256="different"))["decision"] == "insufficient_evidence"
    assert run(live_protocol, records(12), records(19), b, dict(c, prompt_sha256=b["prompt_sha256"]))["decision"] == "insufficient_evidence"
    unfinished = records(19)
    unfinished["results"][0]["stopped_reason"] = "max_steps"
    assert run(live_protocol, records(12), unfinished, b, c)["decision"] == "insufficient_evidence"
    wrong_model = records(19)
    wrong_model["results"][0]["provider_model"] = "other-model"
    assert run(live_protocol, records(12), wrong_model, b, c)["decision"] == "insufficient_evidence"
    nonfinite = records(19)
    nonfinite["results"][0]["duration_s"] = float("nan")
    assert run(live_protocol, records(12), nonfinite, b, c)["decision"] == "insufficient_evidence"


def test_offline_slice_runs_both_runtimes_without_claiming_live_verification(tmp_path):
    pytest.importorskip("langgraph")
    proc = subprocess.run([sys.executable, str(EXPERIMENT / "run_offline_slice.py"),
                           "--out", str(tmp_path / "slice")],
                          capture_output=True, text=True, env=os.environ.copy())
    assert proc.returncode == 0, proc.stderr
    summary = json.loads((tmp_path / "slice/SUMMARY.json").read_text())
    assert set(summary["runtimes"]) == {"harness", "langgraph"}
    for runtime in summary["runtimes"].values():
        assert runtime["inspection"]["inspect_retrieval"]["status"] == "ready"
        assert runtime["draft_review_status"] == "pending"
        assert runtime["comparison"]["decision"] == "mechanism_only"


def test_readiness_rejects_uncorrelated_calls(tmp_path):
    trace = tmp_path / "broken.jsonl"
    trace.write_text("\n".join(json.dumps(s) for s in [
        {"name": "agent.run", "trace_id": "one"},
        {"name": "tool.call", "trace_id": "other", "attributes": {"tool.call_id": "c"}},
    ]))
    report = evidence.check(trace)
    assert report["operations"]["inspect_retrieval"]["status"] == "blocked"
    assert not report["capture"]["tool_arguments"]
