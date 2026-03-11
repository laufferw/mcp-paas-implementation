# Partner Demo Script v1 (Finance POC)

## Goal
Show, in 15 minutes, that AgentGate delivers **API-first, AI-first, agent-first** workflow control with real governance.

## Demo flow

### 1) Open with problem (2 min)
- Finance close workflows are fragmented and manual.
- Agent automation is powerful but risky without controls.
- AgentGate is the control plane: policy, routing, approvals, audit.

### 2) Show architecture quickly (2 min)
- Tenant-scoped token
- Registered upstream servers
- Route strategy (failover/weighted)
- Policy decision point (allow/deny)
- Audit artifact output

### 3) Run onboarding + route demo (6 min)
- Run `pilot-artifacts/finance-stub-demo/run_demo.py` for an end-to-end walkthrough
  - Creates admin + tenant tokens
  - Registers a finance reconciliation MCP server
  - Runs allow-path dry-run (plan action, matching rule)
  - Runs deny-path dry-run (execute action, no matching rule)
  - Exports the audit log
- Alternatively, run the pilot onboarding script for failover/weighted demos

### 4) Show trust evidence (3 min)
- Open latest artifact bundle in `pilot-artifacts/YYYY-MM-DD/`
- Start with `audit-report.json`
- Highlight event id/time, actor identity, matched rule, reason, selected server, allow/deny counts
- Optionally show `actionTrace` entries for replay-style review
- Emphasize: no unauthorized execution path

### 5) Close with value (2 min)
- Faster close prep
- safer AI agent operations
- auditable output for finance leadership

## Demo artifacts

- `pilot-artifacts/finance-stub-demo/fixtures.json` — deterministic fixture (3 accounts, 1 discrepancy)
- `pilot-artifacts/finance-stub-demo/run_demo.py` — self-contained demo script (boots server, full lifecycle)
- `docs/auth-lifecycle.md` — token bootstrap, rotation, and revocation reference

## Key language to repeat
- API-first
- Agent-first
- policy-governed execution
- production-safe automation
- audit-ready operations
