"""Task loading: eval tasks are YAML data, not code.

Schema:
    id: summarize-notes
    description: what this task checks
    prompt: the user task given to the agent
    workspace:            # files materialized into a temp dir before the run
      notes.md: "# notes\n..."
    approver: auto        # auto | deny-all | edit:<path-as-json>
    max_steps: 10         # optional loop guard (default 10)
    script:               # scripted provider turns (deterministic mode)
      - tool_call: {name: list_dir, args: {}}
      - say: "final answer"
    expect:               # scorers
      - {type: answer_contains, value: "done"}
      - {type: file_exists, value: SUMMARY.md}
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class Task:
    id: str
    description: str
    prompt: str
    workspace: dict[str, str] = field(default_factory=dict)
    approver: str = "auto"
    max_steps: int = 10
    script: list[dict[str, Any]] = field(default_factory=list)
    expect: list[dict[str, Any]] = field(default_factory=list)

    @staticmethod
    def from_dict(data: dict[str, Any], source: str = "<dict>") -> "Task":
        missing = {"id", "prompt", "expect"} - data.keys()
        if missing:
            raise ValueError(f"{source}: task missing required keys: {sorted(missing)}")
        return Task(
            id=data["id"],
            description=data.get("description", ""),
            prompt=data["prompt"],
            workspace=data.get("workspace") or {},
            approver=data.get("approver", "auto"),
            max_steps=int(data.get("max_steps", 10)),
            script=data.get("script") or [],
            expect=data.get("expect") or [],
        )


def load_tasks(tasks_dir: str | Path) -> list[Task]:
    root = Path(tasks_dir)
    if not root.is_dir():
        raise FileNotFoundError(f"tasks dir not found: {root}")
    tasks = []
    for path in sorted(root.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        tasks.append(Task.from_dict(data, source=str(path)))
    if not tasks:
        raise ValueError(f"no *.yaml tasks found under {root}")
    return tasks
