# Experiment 001: repeated file retrieval

## Status and provenance

This is an **injected, scripted mechanism fixture**, not a natural failure or a
live-model experiment. File reads stand in for document retrieval; there is no
search ranking or remote retrieval service. No prompt fix has been verified.
The expected key and citation are authored fixture ground truth. Independent
engineer review is pending.

## Run the controls

From the agent-evals repository with its development environment installed:

```bash
python experiments/001-retrieval-loop/run_control.py --out /tmp/retrieval-control-001
```

Use a new output directory for every run. This writes baseline and passing-control
reports and traces separately. Check the native evidence after the control run:

```bash
python experiments/001-retrieval-loop/evidence_check.py \
  /tmp/retrieval-control-001/baseline/traces/retrieval-loop-v1.jsonl \
  --task experiments/001-retrieval-loop/tasks/retrieval-loop.yaml \
  --results /tmp/retrieval-control-001/baseline/results.json
```

For these controlled runs, the runner opts into bounded tool I/O capture:
retrieval inspection is **ready** and exposes three identical `docs/retries.md`
results, alongside the call arguments. The default harness trace remains
metadata-only, so checking a default run reports inspection **blocked**.
Regression drafting with the complete trace is still **conditional** on engineer review and does not
represent replay; experiment comparison remains **blocked** until repeated
trials and an acceptance protocol exist. Trace output can contain document
contents: inspect/redact before sharing it. Exit zero means the baseline failed only the
answer assertion and the passing control passed. It does not mean the baseline
agent succeeded.
When retrieval outputs are omitted, drafting is **blocked** until the missing
evidence is supplied; a task YAML does not prove what the run returned.

The task YAML is outside `tasks/` so its intentional failure does not contaminate
the default passing suite. Both controls use the same task ID, workspace, prompt,
and scorers; only scripted provider behavior changes.

## LangGraph comparison (offline, scripted)

Install the optional dependency, then run a fresh control:

```bash
uv pip install -e '.[dev,langgraph-experiment]'
python experiments/001-retrieval-loop/run_langgraph_control.py \
  --out /tmp/retrieval-langgraph-001
python experiments/001-retrieval-loop/evidence_check.py \
  /tmp/retrieval-langgraph-001/baseline/trace.jsonl \
  --task experiments/001-retrieval-loop/tasks/retrieval-loop.yaml \
  --results /tmp/retrieval-langgraph-001/baseline/results.json
```

The compiled LangGraph graph runs retrieval and answer nodes; it uses scripted
paths and a scripted answer rule, **not a model**. Its instrumented retrieval
node emits the minimal span mapping for this fixture. `native-updates.json` is
the separate native LangGraph stream output. This does not adapt arbitrary
LangGraph graphs, nor does it reproduce a natural failure. This slice tests
whether the same inspection/readiness workflow works across two execution
runtimes; it does not yet demonstrate a general-purpose adapter or verified fix.

### Native versus assisted evidence worksheet

Compare the same failing run without changing tools or task:

| Question | Native LangGraph stream (`native-updates.json`) | Assisted trace/readiness report |
|---|---|---|
| Which documents were returned? | Inspect `retrieve` updates, correlate sequence manually | Filter `tool.call` spans and inspect `tool.result` |
| Which result repeated? | Compare `observed` lists across updates | Compare result bodies on the three `docs/retries.md` spans |
| What caused the wrong answer? | Not established by observed execution alone | Also not established; report only observed correlation |
| Can an outcome be scored? | Requires task expectation and manual matching | Exact fixture scorer in `results.json` |
| Is evidence sufficient? | Manually check missing entries | `evidence_check.py` reports readiness and blockers |

Record wall-clock time and manual edits for each workflow in the measurement
table below. Scripted run duration is *not* engineer debugging time. A single
offline fixture does not yet prove the helper is faster or justify a standard.

## Manual workflow

1. Read the baseline report: execution completed, but the exact key/citation failed.
2. Inspect its trace and locate the repeated `read_file` calls.
3. Compare available trace fields with the task YAML and corpus below.
4. Read `docs/retries.md` and `docs/timeouts.md` in the YAML workspace fixture.
5. Review the expected answer: `KEY=client.request_timeout_ms; SOURCE=atlas-timeouts-v1`.
6. Run the passing control, which reads the relevant document instead of repeating
   the irrelevant one. This validates the assertion and runner, not model behavior.
7. Record missing evidence and manual work before implementing a new evidence format.

The exact output assertion checks fixture answer correctness; it does not prove
that the model used the cited document causally. Repetition is diagnostic evidence,
not itself the outcome assertion.

## Evidence inventory

| Evidence | Current source | Limitation |
|---|---|---|
| Task input and initial corpus | Task YAML workspace | Temporary run workspace is deleted afterward |
| Expected answer | YAML exact-answer scorer | Independent review pending |
| Tool-call timing/sequence | Generated JSONL traces | Four read calls; opt-in traces include bounded arguments, default traces omit them |
| Tool result contents | Opt-in JSONL traces | Successful results captured up to 4,000 characters; default traces omit them |
| Scripted behavior | YAML / passing-control script | Not a model decision |
| Outcome and trace ID | Generated result reports | Does not preserve a full reproduction bundle |
| Natural failure | Not collected | Required for the next validation gate |
| External runtime | Scripted LangGraph control | Does not cover arbitrary LangGraph applications |

## Baseline measurement worksheet

Do not populate these fields with scripted execution duration. They measure an
engineer's workflow, including unsuccessful attempts.

| Stage | Native workflow elapsed | Assisted workflow elapsed | Manual steps / blockers |
|---|---|---|---|
| Capture/setup | Not measured | Not measured | |
| Inspection/diagnosis | Not measured | Not measured | |
| Fixture and assertion review | Not measured | Not measured | |
| Proposed change | Not measured | Not measured | |
| Model/tool waiting | Not measured | Not measured | |
| Verification | Not measured | Not measured | |

## Full offline slice

```bash
python experiments/001-retrieval-loop/run_offline_slice.py \
  --out /tmp/retrieval-offline-slice-001
```

This produces `SUMMARY.json`, 20 scripted runs per arm for each runtime,
review-pending drafts, copied baseline/passing-control bundles, and a
`mechanism_only` comparison under `protocol.json`.
A new directory is required on each run. See [PILOT.md](PILOT.md) for an
independent-user walkthrough; it is prepared but has not been conducted.
The comparison threshold can be met by a scripted control while **no live-model
fix is verified**. Neither a time-saving claim nor a separate evidence
standard is supported by these runs.

## Local portable evidence helper

The offline slice writes `<runtime>/baseline-bundle` and
`<runtime>/passing-control-bundle`. Each contains an existing trace export,
the authored task (including the selected fixture corpus), result records, and
SHA-256 references in `manifest.json`. The baseline bundle also includes the
predeclared protocol. Move or copy both directories to another machine and run:

```bash
python experiments/001-retrieval-loop/bundle_helper.py check \
  /tmp/retrieval-offline-slice-001/harness/baseline-bundle \
  --baseline /tmp/retrieval-offline-slice-001/harness/baseline-bundle \
  --candidate /tmp/retrieval-offline-slice-001/harness/passing-control-bundle
```

For a single control, export explicitly (use a new output directory):

```bash
python experiments/001-retrieval-loop/bundle_helper.py export \
  --trace /tmp/retrieval-control-001/baseline/traces/retrieval-loop-v1.jsonl \
  --task experiments/001-retrieval-loop/tasks/retrieval-loop.yaml \
  --results /tmp/retrieval-control-001/baseline/results.json \
  --out /tmp/retrieval-bundle-001
python experiments/001-retrieval-loop/bundle_helper.py check /tmp/retrieval-bundle-001
```

The three readiness operations are independent: inspection requires correlated
calls and complete observed retrieval I/O; drafting also requires a matching
outcome and an authored fixture, then stays `conditional` until engineer review;
comparison requires two complete trial sets, matching identities, and an included
protocol. The comparison's `ready` status means the inputs can be evaluated,
not that a model fix succeeded: scripted controls return `mechanism_only`.
Missing or modified artifacts, symlinks, and paths outside a bundle root block
readiness. The manifest's capture labels are informational; checks recompute
readiness from the included bytes. Capture is opt-in and includes unredacted
document text in this fixture; review before sharing. This helper exports only
authored local fixtures and does not replay recorded tools or execute bundle
content. The first included trace corresponds to one run; repeated outcomes are
carried in `results.json`, not as individual trace artifacts.

## Next gates

- Collect a natural retrieval failure and retain its provenance separately.
- Compare two existing debugging/export workflows using matched cases.
- Time a native-vs-assisted LangGraph walkthrough with an engineer; record overhead and blockers.
- Identify the minimum missing evidence and decide helper-only vs separate contract.
- Write a live-trial protocol before changing prompts or collecting candidate results.
- For a future live comparison, declare `allowed_difference: prompt_sha256` and
  record differing prompt fingerprints plus matching tool-schema, model-settings,
  and runtime-version fingerprints in both manifests; include the declared model
  in every trial result. Missing identities yield `insufficient_evidence`.
- Preserve failed trials; no autonomous fixes or paid model calls in this control.
