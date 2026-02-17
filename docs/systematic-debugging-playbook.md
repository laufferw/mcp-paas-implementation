# Systematic Debugging Playbook

Use this when behavior is failing, flaky, or inconsistent.

## Phase 1 — Reproduce
- Define expected vs actual behavior
- Capture exact failing command/request
- Reproduce in minimal scope
- Record environment facts (runtime, env vars, endpoint, branch)

Output: reproducible failure case (or explicitly non-reproducible).

## Phase 2 — Isolate
- Narrow the failure boundary (input, auth, policy, transport, storage)
- Check deterministic signals first (status codes, stack traces, schema mismatches)
- Test one hypothesis at a time

Output: smallest failing surface identified.

## Phase 3 — Fix
- Implement minimal corrective change
- Avoid unrelated refactors
- If multiple fixes are possible, choose lowest-risk first

Output: targeted patch linked to root cause.

## Phase 4 — Verify + Guard
- Re-run the original failure case
- Add/adjust test or runbook step to prevent regression
- Document root cause and confidence level

Output: proof of fix + prevention step.

## Debug report template
- Symptom:
- Expected:
- Actual:
- Reproduction:
- Root cause hypothesis:
- Fix applied:
- Verification evidence:
- Confidence: HIGH | MEDIUM | LOW
- Follow-up guardrail:
