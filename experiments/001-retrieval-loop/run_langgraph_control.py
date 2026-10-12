"""Offline LangGraph graph exercising the retrieval fixture; no model is called.

The adapter instruments this graph's retrieval node, not arbitrary LangGraph apps.
Native LangGraph state/updates are kept as separate artifacts for baseline inspection.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from pathlib import Path
from typing import TypedDict

import yaml
from langgraph.graph import END, START, StateGraph
from agent_harness.tracing import init_tracing

HERE = Path(__file__).resolve().parent
TASK = HERE / "tasks/retrieval-loop.yaml"
EXPECTED = re.compile(r"\AKEY=client\.request_timeout_ms; SOURCE=atlas-timeouts-v1\s*\Z")


class State(TypedDict):
    remaining: list[str]
    observed: list[dict]
    answer: str


def build_graph(workspace: dict[str, str], tracer):
    def retrieve(state: State):
        path = state["remaining"][0]
        with tracer.start_as_current_span("tool.call") as span:
            span.set_attribute("tool.name", "read_file")
            span.set_attribute("tool.call_id", f"retrieval-{len(state['observed']) + 1}")
            span.set_attribute("tool.proposed_arguments", json.dumps({"path": path}))
            span.set_attribute("tool.arguments", json.dumps({"path": path}))
            # A fixture-backed tool, not the harness' read_file implementation.
            value = workspace.get(path)
            if value is None:
                span.set_attribute("tool.result_status", "error")
                span.set_attribute("tool.error_message", "fixture document not found")
                observed = {"path": path, "status": "error"}
            else:
                span.set_attribute("tool.result_status", "ok")
                span.set_attribute("tool.result", value)
                observed = {"path": path, "status": "ok", "result": value}
            return {"remaining": state["remaining"][1:], "observed": state["observed"] + [observed]}

    def answer(state: State):
        # Scripted response based only on whether the timeouts document was read;
        # this is not an LLM choosing the right tool or reasoning over contents.
        found = any(o["path"] == "docs/timeouts.md" and o["status"] == "ok" for o in state["observed"])
        text = ("KEY=client.request_timeout_ms; SOURCE=atlas-timeouts-v1" if found
                else "KEY=request.timeout; SOURCE=atlas-retries-v1")
        return {"answer": text}

    graph = StateGraph(State)
    graph.add_node("retrieve", retrieve)
    graph.add_node("answer", answer)
    graph.add_edge(START, "retrieve")
    graph.add_conditional_edges("retrieve", lambda s: "retrieve" if s["remaining"] else "answer")
    graph.add_edge("answer", END)
    return graph.compile()


def run(label: str, paths: list[str], out: Path) -> dict:
    task = yaml.safe_load(TASK.read_text(encoding="utf-8"))
    out.mkdir(parents=True, exist_ok=False)
    provider = init_tracing(out / "trace.jsonl", service_name="retrieval-langgraph-control")
    tracer = provider.get_tracer("retrieval-langgraph-control")
    graph = build_graph(task["workspace"], tracer)
    state: State = {"remaining": paths, "observed": [], "answer": ""}
    updates = []
    started = time.perf_counter()
    try:
        with tracer.start_as_current_span("agent.run") as root:
            root.set_attribute("agent.task", task["prompt"])
            root.set_attribute("llm.model", "scripted-langgraph")
            root.set_attribute("agent.stopped_reason", "completed")
            trace_id = f"{root.get_span_context().trace_id:032x}"
            # Native stream updates are retained for the unassisted workflow.
            for update in graph.stream(state, stream_mode="updates"):
                updates.append(update)
                for change in update.values():
                    state.update(change)
        provider.force_flush()
    finally:
        provider.shutdown()
    (out / "native-updates.json").write_text(json.dumps(updates, indent=2), encoding="utf-8")
    passed = bool(EXPECTED.fullmatch(state["answer"]))
    result = {
        "task_id": task["id"], "passed": passed, "trace_id": trace_id,
        "repeat": 1, "provider_model": "scripted-langgraph", "error": "",
        "duration_s": round(time.perf_counter() - started, 3),
        "scores": [{"scorer": "answer_regex", "passed": passed,
                    "detail": "fixture exact key and citation"}],
    }
    (out / "results.json").write_text(json.dumps({
        "provider": "scripted-langgraph", "results": [result]
    }, indent=2), encoding="utf-8")
    print(f"{label}: passed={passed}; trace_id={trace_id}")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=1)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be positive")
    args.out.mkdir(parents=True, exist_ok=False)
    task = yaml.safe_load(TASK.read_text(encoding="utf-8"))
    batches = []
    for label, paths in (("baseline", ["docs/index.md"] + ["docs/retries.md"] * 3),
                         ("passing-control", ["docs/index.md", "docs/timeouts.md"])):
        base = args.out / label
        runs = []
        for i in range(1, args.repeats + 1):
            trial_dir = base if args.repeats == 1 else base / f"trial-{i}"
            result = run(label, paths, trial_dir)
            result["repeat"] = i
            runs.append(result)
        base.mkdir(exist_ok=True)
        (base / "results.json").write_text(json.dumps({"provider": "scripted-langgraph", "results": runs}, indent=2))
        manifest = {
            "protocol_revision": "retrieval-pilot-v1", "task_revision": task["id"],
            "scorer_revision": "exact-key-citation-v1", "runtime": "langgraph",
            "model": "scripted-langgraph", "treatment": label,
            "fixture_sha256": hashlib.sha256(json.dumps(task["workspace"], sort_keys=True).encode()).hexdigest(),
        }
        (base / "manifest.json").write_text(json.dumps(manifest, indent=2))
        batches.append(runs)
    print("Offline scripted controls only; no live-model improvement claim.")
    return 0 if all(not r["passed"] for r in batches[0]) and all(r["passed"] for r in batches[1]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
