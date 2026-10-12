"""Local retrieval-evidence export and three operation-specific readiness checks.

Bundles contain copied files, not executable replay instructions. Inspecting one
never runs its contents. This is an experiment helper, not a general contract.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath

import yaml

from compare_experiment import compare
from evidence_check import check

FILES = {"trace": "trace.jsonl", "task": "task.yaml", "results": "results.json",
         "run_manifest": "run-manifest.json", "protocol": "protocol.json"}
REQUIRED = ("trace", "task", "results")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_path(root: Path, name: str) -> Path:
    """Reject absolute paths, traversal, and symlinks (including root)."""
    if not isinstance(name, str) or not name or "\\" in name:
        raise ValueError("invalid bundle artifact path")
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in (".", "..") for part in name.split("/")):
        raise ValueError(f"bundle artifact path escapes root: {name!r}")
    if root.is_symlink() or any(p.is_symlink() for p in (root / name, *(root / name).parents)):
        raise ValueError(f"symlink in bundle artifact path: {name!r}")
    target = root / name
    if not target.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"bundle artifact path escapes root: {name!r}")
    return target


def export(out: Path, trace: Path, task: Path, results: Path,
           run_manifest: Path | None = None, protocol: Path | None = None) -> dict:
    sources = {"trace": trace, "task": task, "results": results,
               "run_manifest": run_manifest, "protocol": protocol}
    # Validate sources and parse the authored fixture before creating output.
    for source in sources.values():
        if source is not None and (source.is_symlink() or not source.is_file()):
            raise ValueError(f"expected a regular input file: {source}")
    authored = yaml.safe_load(task.read_text(encoding="utf-8"))
    if not isinstance(authored, dict) or not isinstance(authored.get("workspace"), dict):
        raise ValueError("task must contain an authored workspace mapping")
    if not isinstance(json.loads(results.read_text(encoding="utf-8")), dict):
        raise ValueError("results must be an object")
    identity = json.loads(run_manifest.read_text(encoding="utf-8")) if run_manifest else {}
    if not isinstance(identity, dict):
        raise ValueError("run manifest must be an object")
    if protocol:
        json.loads(protocol.read_text(encoding="utf-8"))
    out.mkdir(parents=True, exist_ok=False)
    artifacts = {}
    for key, source in sources.items():
        if source is None:
            continue
        data = source.read_bytes()
        target = _safe_path(out, FILES[key])
        target.write_bytes(data)
        artifacts[key] = {"path": FILES[key], "sha256": digest(data)}
    observation = check(out / FILES["trace"], out / FILES["task"], out / FILES["results"])
    manifest = {
        "format": "retrieval-helper-v1",
        "artifacts": artifacts,
        "identity": {
            "task_id": authored.get("id"),
            "task_sha256": artifacts["task"]["sha256"],
            "fixture_sha256": digest(json.dumps(authored["workspace"], sort_keys=True,
                                                separators=(",", ":"), ensure_ascii=False).encode("utf-8")),
            "trace_id": observation["trace_id"],
            "run": identity,
        },
        "capture": {
            field: ("present" if value else "missing")
            for field, value in observation["capture"].items()
        },
        "omissions": [key for key in ("run_manifest", "protocol") if key not in artifacts],
        "capture_limitations": observation["operations"]["inspect_retrieval"]["blockers"],
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def _load(root: Path) -> tuple[dict, dict[str, Path]]:
    if root.is_symlink() or not root.is_dir():
        raise ValueError("bundle root must be a directory, not a symlink")
    manifest = json.loads(_safe_path(root, "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("format") != "retrieval-helper-v1" or not isinstance(manifest.get("artifacts"), dict):
        raise ValueError("unsupported or malformed bundle manifest")
    artifacts = manifest["artifacts"]
    if not all(key in artifacts for key in REQUIRED) or any(key not in FILES for key in artifacts):
        raise ValueError("missing required or unrecognized artifact")
    paths = {}
    for key, record in artifacts.items():
        if not isinstance(record, dict) or record.get("path") != FILES[key]:
            raise ValueError(f"invalid {key} artifact reference")
        path = _safe_path(root, record["path"])
        if not path.is_file() or digest(path.read_bytes()) != record.get("sha256"):
            raise ValueError(f"missing or corrupt {key} artifact")
        paths[key] = path
    return manifest, paths


def readiness(root: Path, baseline: Path | None = None, candidate: Path | None = None) -> dict:
    """Recompute readiness from included bytes; producer capture labels are advisory."""
    try:
        manifest, paths = _load(root)
        report = check(paths["trace"], paths["task"], paths["results"])
        authored = yaml.safe_load(paths["task"].read_text(encoding="utf-8"))
        identity = manifest.get("identity", {})
        if (not isinstance(authored, dict) or identity.get("task_id") != authored.get("id")
                or identity.get("task_sha256") != digest(paths["task"].read_bytes())
                or identity.get("trace_id") != report["trace_id"]
                or identity.get("fixture_sha256") != digest(json.dumps(authored.get("workspace"), sort_keys=True,
                        separators=(",", ":"), ensure_ascii=False).encode("utf-8"))):
            raise ValueError("bundle identity disagrees with included evidence")
        run_identity = identity.get("run", {})
        if "run_manifest" in paths and run_identity != json.loads(paths["run_manifest"].read_text(encoding="utf-8")):
            raise ValueError("run identity disagrees with included manifest")
        if run_identity.get("task_revision") not in (None, authored.get("id")):
            raise ValueError("run task revision disagrees with authored task")
        if (run_identity.get("fixture_sha256") and
                run_identity["fixture_sha256"] != digest(json.dumps(authored["workspace"], sort_keys=True).encode())):
            raise ValueError("run fixture fingerprint disagrees with authored workspace")
        operations = report["operations"]
        if baseline is not None and candidate is not None:
            b_manifest, b_paths = _load(baseline)
            c_manifest, c_paths = _load(candidate)
            for label, m, p in (("baseline", b_manifest, b_paths), ("candidate", c_manifest, c_paths)):
                if "identity" not in readiness(baseline if label == "baseline" else candidate):
                    raise ValueError(f"{label} bundle identity validation failed")
                if "run_manifest" not in p:
                    raise ValueError(f"{label} bundle has no run manifest")
                if m.get("identity", {}).get("run") != json.loads(p["run_manifest"].read_text(encoding="utf-8")):
                    raise ValueError(f"{label} run identity disagrees with included manifest")
            if "protocol" not in paths:
                raise ValueError("comparison protocol is not included in bundle")
            decision = compare(json.loads(paths["protocol"].read_text(encoding="utf-8")),
                               json.loads(b_paths["results"].read_text(encoding="utf-8")),
                               json.loads(c_paths["results"].read_text(encoding="utf-8")),
                               json.loads(b_paths["run_manifest"].read_text(encoding="utf-8")),
                               json.loads(c_paths["run_manifest"].read_text(encoding="utf-8")))
            operations["compare_experiments"] = {
                "status": "blocked" if decision["decision"] == "insufficient_evidence" else "ready",
                "blockers": decision["blockers"], "decision": decision["decision"],
            }
        elif baseline is not None or candidate is not None:
            operations["compare_experiments"]["blockers"].append("Both baseline and candidate bundles required")
        return {"identity": identity, "operations": operations, "capture": report["capture"]}
    except (ValueError, OSError, KeyError, TypeError, json.JSONDecodeError, yaml.YAMLError) as exc:
        reason = f"Bundle validation failed: {exc}"
        return {"operations": {key: {"status": "blocked", "blockers": [reason]}
                               for key in ("inspect_retrieval", "draft_regression", "compare_experiments")}}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    writer = commands.add_parser("export")
    for option in ("trace", "task", "results", "out"):
        writer.add_argument(f"--{option}", type=Path, required=True)
    writer.add_argument("--run-manifest", type=Path)
    writer.add_argument("--protocol", type=Path)
    reader = commands.add_parser("check")
    reader.add_argument("bundle", type=Path)
    reader.add_argument("--baseline", type=Path)
    reader.add_argument("--candidate", type=Path)
    args = parser.parse_args()
    if args.command == "export":
        result = export(args.out, args.trace, args.task, args.results, args.run_manifest, args.protocol)
    else:
        result = readiness(args.bundle, args.baseline, args.candidate)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
