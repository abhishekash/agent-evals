# M0 decision record — provisional

**Status:** Not a completed M0 go/no-go decision. No independent-user timings or natural failure are available.

## What the offline comparison establishes

- The original harness span export preserved `tool.call` identity and status but omitted successful results and arguments; a retrieval-overlap diagnosis was blocked.
- An opt-in bounded I/O capture makes the controlled run inspectable without a new schema: the same checker reports inspection ready for both harness and the instrumented LangGraph fixture.
- LangGraph's native `stream_mode="updates"` output also contains retrieval observations; the assisted trace/report offers a different way to correlate calls and flags incomplete evidence.
- The checker correctly blocks a deliberately incomplete trace. Both runtimes remain conditional for regression drafting (review pending) and blocked for experiment comparison (no repeated trials).
- A metadata-only trace now blocks drafting as well as retrieval inspection;
  duplicate outcome matches cannot establish run provenance. Live experiment
  verification requires a prompt-only protocol and matching declared runtime,
  tool-schema, and model-settings identities across arms. The existing controls
  still produce only `mechanism_only` decisions.
- Both examples are scripted controls. No improvement in engineer time, model behavior, or cross-framework portability has been measured.

## Decision for now

**Use existing JSONL/OpenTelemetry-shaped spans plus a thin readiness helper. Do not create a standalone portable contract package yet.** This is a scope decision, not proof that the helper is better than native debugging.

## What would change the decision

1. A naturally occurring failure whose required evidence cannot be represented with the thin helper.
2. A second independently instrumented LangGraph application exposing a semantic gap in the current mapping.
3. A baseline walkthrough showing measurable manual friction after accounting for capture setup and fixture review.

## Outstanding M0/M2 gates

- Collect one natural failure; preserve its source, constraints, and redactions.
- Time native and assisted debugging with someone unfamiliar with this fixture.
- Generalize the LangGraph instrumentation from the controlled graph only if user evidence warrants it.
- Complete reviewed regression and repeated live evaluation before claiming a verified fix.
