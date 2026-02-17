# Execution Standards (API/AI/Agent-First Delivery)

These standards are adopted to keep MCP Gateway work fast, reliable, and evidence-driven.

## 1) First-Value Operating Loop
For any multi-step feature or fix:

1. Define a **binary first-value checkpoint** (working/not-working within 10-30 minutes).
2. Run **preflight** (deps, auth, runtime, network, permissions).
3. Execute the **smallest end-to-end path** that proves value.
4. Capture **evidence artifacts** (logs, JSON outputs, screenshots, test reports).
5. Expand scope only after first-value is proven.

If first-value fails, stop broadening scope and fix blockers directly.

## 2) Preflight Checklist
Before claiming progress, verify:

- Runtime/dependencies are installed and importable
- Main command actually runs
- Output artifact exists and is readable
- Relevant tests/CI checks pass (or explicit blocker is documented)
- Any blocker has a concrete next action

## 3) Proof-over-assertion Rule
Use language like:
- "here is the output"
- "here is the artifact"
- "here is the run id / log"

Avoid: "should work now" without evidence.

## 4) Pilot Quality Gate
For partner-facing pilot workflows, every run must include:
- at least one allowed-path route proof
- at least one denied-path route proof
- audit report with decision reason + matched rule + selected route

## 5) Scope Discipline
- Keep changes surgical and focused on current goal.
- Avoid broad refactors unless they unblock first-value directly.
- Prefer incremental commits with clear validation notes.
