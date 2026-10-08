# Contributing to agent-evals

## Development setup

```bash
uv venv
uv pip install -e ".[dev]"
pytest -q
agent-evals run
```

## Adding an eval

Add a YAML task under `tasks/` with a deterministic scripted path, an isolated workspace, and explicit expectations. Include at least one mechanism scorer (tool, side effect, budget, HITL, or trace), not only an answer string.

The checked-in baseline is intentionally scripted. If adding a live-model runner, report model/version, sampling settings, repeats, cost, latency, and failed-task traces separately from the deterministic baseline.

Keep generated `results/traces/` out of Git; commit only intentional result snapshots and update the README's interpretation when the suite changes.
