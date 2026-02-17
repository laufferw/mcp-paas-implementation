# Spec → Build → Verify Gates

Use this gate model for implementation work to prevent drift and false-complete outcomes.

## Gate 1: Spec (build the right thing)
Required before implementation:
- Problem statement in one sentence
- Success criteria (binary where possible)
- Constraints (security, time, scope, dependencies)
- Out-of-scope list

**Exit criteria:** all four are written and reviewed.

## Gate 2: Build (build it in controlled increments)
Execution rules:
- Break implementation into micro-tasks (ideally 2–15 minute chunks)
- Keep changes surgical and tied to success criteria
- Prefer deterministic checks before LLM-heavy iteration

**Exit criteria:** implementation path complete with intermediate evidence artifacts.

## Gate 3: Verify (prove it works)
Validation rules:
- Run preflight checklist
- Run relevant tests/checks
- Produce proof artifact(s): logs, API outputs, test report
- Classify open findings by confidence (HIGH/MEDIUM/LOW)

**Exit criteria:** evidence confirms criteria met, or blockers are explicit with next action.

## Handoff format
- Objective
- Gate reached (Spec/Build/Verify)
- Evidence links/paths
- Open findings + confidence
- Next 1–3 actions
