# Coordinator ↔ Worker Handoff Contract

Use this contract whenever a coordinating agent delegates work to a worker agent.

## Goal
Ensure delegated execution is reliable, auditable, and resumable.

## Handoff payload (required)
- **Task ID**: unique identifier
- **Objective**: one-line expected outcome
- **Scope**: explicit in-scope and out-of-scope
- **Inputs**: files, endpoints, tokens/scopes (non-secret references only)
- **Success criteria**: binary checks
- **Constraints**: security, time, quality bars
- **Evidence requirement**: exact artifact/log output expected

## Worker response contract
Worker must return:
- **Status**: done | blocked | partial
- **Evidence**: command output, artifact path(s), test result(s)
- **Confidence**: HIGH | MEDIUM | LOW
- **Blockers**: concrete blocker + next action

## Escalation rules
Escalate immediately when:
- a required permission is missing,
- a security control conflicts with requested action,
- evidence quality drops below acceptable confidence,
- output deviates from success criteria.

## Safety rules
- No external side effects without explicit approval.
- No secret material in handoff logs.
- Keep delegation bounded and reversible.
