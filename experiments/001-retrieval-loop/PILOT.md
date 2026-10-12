# Independent-user pilot protocol (pending)

**Not completed.** This is a script for an engineer who did not build the fixture. It is not a substitute for recruiting that engineer or measuring their time.

## Preconditions

- Use a clean working environment with `agent-evals[dev,langgraph-experiment]` installed.
- Reviewer must not read implementation or answer key before the native task.
- Keep the same authored task and fixture across both workflows; vary task order across participants if more than one participates.
- No model credentials are needed for the offline controls. Do not paste private logs into shared reports.

## Native task

Given `run_langgraph_control.py`'s baseline `native-updates.json` and the task prompt (without the expected outcome), identify the repeated retrieval, the observable cause of the wrong answer, and any information you cannot establish. Record elapsed wall time, setup time, number of manual steps, and whether the diagnosis is supported. Do not infer model reasoning from a scripted control.

## Assisted task

Using the baseline `trace.jsonl`, run `evidence_check.py`, examine the relevant spans, and draft a regression with `draft_regression.py`. Report the same measurements plus fixture/assertion review time. Do not call the draft runnable until an engineer has reviewed it.

## Review and verification

- Reveal `docs/timeouts.md` and the exact outcome assertion. Reviewer records whether the key and citation are valid and whether the fixture is realistic enough for the intended question.
- Run `run_offline_slice.py` in a fresh output directory to confirm both controls, then compare using the predeclared `protocol.json`.
- Record the comparator's `mechanism_only` label: passing scripted controls do not prove a model fix.
- For any future live study, pin the model/settings and treatment before running; use held-out tasks before claiming general improvement.

## Measurement sheet

| Participant ID | Workflow | Capture/setup | Active inspection | Fixture review | Waiting | Total wall-clock | Steps/edits | Correct diagnosis? | Unsupported claims? |
|---|---|---:|---:|---:|---:|---:|---|---|---|
| pending | native | | | | | | | | |
| pending | assisted | | | | | | | | |

Do not fill in fictitious numbers. A single participant is a usability pilot, not evidence of statistically reliable time savings. Record failures and incomplete attempts, not just successes.
