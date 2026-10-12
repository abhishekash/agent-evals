"""Apply the predeclared retrieval experiment rule to repeated result records.

Scripted controls are always labelled mechanism_only, never verified improvement.
Requires explicit, matching run manifests; no missing run is counted as success.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
from pathlib import Path


def compare(protocol: dict, baseline: dict, candidate: dict, baseline_manifest: dict, candidate_manifest: dict) -> dict:
    blockers = []
    required = ("protocol_revision", "task_revision", "scorer_revision")
    for key in required:
        if not protocol.get(key) or any(m.get(key) != protocol[key] for m in (baseline_manifest, candidate_manifest)):
            blockers.append(f"{key}: missing or incompatible revision")
    for key in ("runtime", "model", "fixture_sha256"):
        if not baseline_manifest.get(key) or baseline_manifest.get(key) != candidate_manifest.get(key):
            blockers.append(f"{key}: missing or incompatible baseline/candidate setting")
    if not protocol.get("allowed_difference"):
        blockers.append("protocol: no permitted treatment difference declared")
    if not baseline_manifest.get("treatment") or not candidate_manifest.get("treatment"):
        blockers.append("treatment: undeclared change")
    if baseline_manifest.get("treatment") == candidate_manifest.get("treatment"):
        blockers.append("treatment: no declared difference")

    scripted = all("scripted" in str(m.get("model", "")) for m in (baseline_manifest, candidate_manifest))
    if not scripted:
        # A treatment label is not evidence that only a prompt changed. A live
        # comparison requires explicit identities for every controlled setting.
        if protocol.get("allowed_difference") != "prompt_sha256":
            blockers.append("protocol: live trials require a prompt_sha256-only treatment")
        for key in ("tool_schema_sha256", "model_settings_sha256", "runtime_version"):
            if not baseline_manifest.get(key) or baseline_manifest.get(key) != candidate_manifest.get(key):
                blockers.append(f"{key}: missing or incompatible controlled setting")
        if not baseline_manifest.get("prompt_sha256") or not candidate_manifest.get("prompt_sha256") or baseline_manifest.get("prompt_sha256") == candidate_manifest.get("prompt_sha256"):
            blockers.append("prompt_sha256: missing or unchanged treatment")

    planned = protocol.get("planned_trials_per_arm", 0)
    if type(planned) is not int or planned < 2:
        blockers.append("protocol: invalid planned trial count")
    trial_sets = []
    for label, payload in (("baseline", baseline), ("candidate", candidate)):
        rows = payload.get("results", [])
        ids = [r.get("repeat") for r in rows]
        if not planned or sorted(ids, key=lambda x: str(x)) != sorted(range(1, planned + 1), key=str):
            blockers.append(f"{label}: missing, duplicate, or unexpected trial records")
        if any(r.get("task_id") != protocol.get("task_revision") for r in rows):
            blockers.append(f"{label}: incompatible task IDs")
        if any(not isinstance(r.get("passed"), bool) or type(r.get("duration_s")) not in (int, float)
               or not math.isfinite(r["duration_s"]) or r["duration_s"] < 0 or not isinstance(r.get("scores"), list)
               or not r["scores"] or not all(isinstance(s.get("passed"), bool) for s in r["scores"] if isinstance(s, dict))
               or any(not isinstance(s, dict) for s in r["scores"])
               or not r.get("trace_id") for r in rows):
            blockers.append(f"{label}: incomplete outcome, score, duration, or trace ID")
        if len({r.get("trace_id") for r in rows}) != len(rows):
            blockers.append(f"{label}: duplicate trace IDs")
        manifest = baseline_manifest if label == "baseline" else candidate_manifest
        if not scripted and any(r.get("provider_model") != manifest.get("model") for r in rows):
            blockers.append(f"{label}: trial model differs from declared model")
        if any(r.get("stopped_reason") not in (None, "completed") and r.get("passed") for r in rows):
            blockers.append(f"{label}: incomplete execution marked as passed")
        if any(r.get("passed") and (r.get("error") or not all(s.get("passed") for s in r.get("scores", []) if isinstance(s, dict))) for r in rows):
            blockers.append(f"{label}: passed flag contradicts error or scorer outcomes")
        trial_sets.append(rows)
    if blockers:
        return {"decision": "insufficient_evidence", "blockers": blockers}

    for key in ("minimum_candidate_passes", "minimum_pass_gain", "maximum_median_latency_ratio"):
        if type(protocol.get(key)) not in (int, float) or not math.isfinite(protocol[key]) or protocol[key] < 0:
            return {"decision": "insufficient_evidence", "blockers": [f"protocol: invalid {key}"]}
    b, c = trial_sets
    b_pass = sum(r["passed"] and not r.get("error") for r in b)
    c_pass = sum(r["passed"] and not r.get("error") for r in c)
    b_median = statistics.median(r["duration_s"] for r in b)
    c_median = statistics.median(r["duration_s"] for r in c)
    if b_median == 0:
        return {"decision": "insufficient_evidence", "blockers": ["baseline median latency is zero"]}
    meets = (c_pass >= protocol["minimum_candidate_passes"]
             and c_pass - b_pass >= protocol["minimum_pass_gain"]
             and c_median <= b_median * protocol["maximum_median_latency_ratio"])
    # These controls change the scripted action, not a real agent's prompt/model behavior.
    return {
        "decision": "mechanism_only" if scripted else ("verified_for_protocol" if meets else "not_verified"),
        "thresholds_met": meets,
        "baseline": {"passes": b_pass, "total": len(b), "median_latency_s": b_median},
        "candidate": {"passes": c_pass, "total": len(c), "median_latency_s": c_median},
        "scope": "offline scripted control" if scripted else "fixture-specific protocol only",
        "blockers": [],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True, help="Directory containing results.json and manifest.json")
    parser.add_argument("--candidate", type=Path, required=True)
    args = parser.parse_args()
    load = lambda p: json.loads(p.read_text(encoding="utf-8"))
    report = compare(load(args.protocol), load(args.baseline / "results.json"),
                     load(args.candidate / "results.json"), load(args.baseline / "manifest.json"),
                     load(args.candidate / "manifest.json"))
    print(json.dumps(report, indent=2))
    return 2 if report["decision"] == "insufficient_evidence" else 0


if __name__ == "__main__":
    raise SystemExit(main())
