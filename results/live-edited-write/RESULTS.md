## Latest results — provider: `agent-harness / opencode:big-pickle`

- Pass rate: **0/3 (0.0%)**
- Cost: **unknown total** / unknown mean run (3 runs without pricing)
- Latency: **0.538s mean**, 0.534s p50, 0.590s p95
- Failures: **3**

| Run | Task | Result | Steps | Tokens | Cost | Latency | Approvals | Stop | Failures |
|---:|---|---|---:|---:|---:|---:|---:|---|---|
| 1 | `edited-write` | ❌ | 1 | 0 | unknown | 0.590s | 0 | error | answer_contains: answer missing 'human-approved'; file_exists: safe.txt missing in workspace; file_contains: safe.txt missing; hitl_decisions: 0 approvals recorded (want ≥1); hitl_event_present: hitl.decision event MISSING — gate bypassed?; run_error: provider error on step 1: OpenAI-compatible request failed: Error code: 403 - {'type': 'error', 'error': {'type': 'FreeTierError', 'message': "OpenCode's free tier can only be used from within OpenCode"}} |
| 2 | `edited-write` | ❌ | 1 | 0 | unknown | 0.489s | 0 | error | answer_contains: answer missing 'human-approved'; file_exists: safe.txt missing in workspace; file_contains: safe.txt missing; hitl_decisions: 0 approvals recorded (want ≥1); hitl_event_present: hitl.decision event MISSING — gate bypassed?; run_error: provider error on step 1: OpenAI-compatible request failed: Error code: 403 - {'type': 'error', 'error': {'type': 'FreeTierError', 'message': "OpenCode's free tier can only be used from within OpenCode"}} |
| 3 | `edited-write` | ❌ | 1 | 0 | unknown | 0.534s | 0 | error | answer_contains: answer missing 'human-approved'; file_exists: safe.txt missing in workspace; file_contains: safe.txt missing; hitl_decisions: 0 approvals recorded (want ≥1); hitl_event_present: hitl.decision event MISSING — gate bypassed?; run_error: provider error on step 1: OpenAI-compatible request failed: Error code: 403 - {'type': 'error', 'error': {'type': 'FreeTierError', 'message': "OpenCode's free tier can only be used from within OpenCode"}} |

**0/3 passing (0.0%) · unknown total · 0.538s mean / 0.590s p95 · 3 failures**
