from agent_evals.tasks import load_tasks


def test_all_tasks_load_and_have_expectations():
    tasks = load_tasks("tasks")
    assert len(tasks) == 8
    assert {t.id for t in tasks} == {
        "summarize-notes",
        "verify-with-shell",
        "denied-write",
        "edited-write",
        "step-budget",
        "unknown-tool-recovery",
        "token-budget",
        "file-pipeline",
    }
    assert all(t.expect for t in tasks)
    assert all(t.script for t in tasks)


def test_edit_approver_is_data():
    task = next(t for t in load_tasks("tasks") if t.id == "edited-write")
    assert task.approver.startswith("edit:")
    assert 'safe.txt' in task.approver
