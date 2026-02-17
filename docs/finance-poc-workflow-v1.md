# Finance POC Workflow v1 — Close/Reconciliation Prep

## Goal
Produce a governed close-prep package with clear mismatch findings, proposed actions, and an audit trail.

## Actors
- Finance Operator (tenant user)
- Approver (controller/finance lead)
- AgentGate (policy, routing, audit)
- Upstream systems (accounting + spreadsheet/document source)

## Preconditions
1. Tenant token created with `gateway:read`, `gateway:plan`, and optional `gateway:write` scope.
2. Servers registered for tenant with health status `healthy=true`.
3. Policy rule set loaded for finance workflow (see `docs/policy-templates-finance-v1.md`).

## Workflow Steps

### Step 1 — Intake
- Operator submits run request with period (e.g., `2026-01`) and account scope.
- Gateway validates token scope + tenant binding.

### Step 2 — Data Pull Plan
- Gateway dry-runs route selection for required reads (weighted or failover strategy).
- Policy checks executed for each planned read operation.
- If denied/unhealthy, return explicit reason and stop.

### Step 3 — Reconciliation Analysis
- Agent computes:
  - trial balance mismatches
  - unsupported line items
  - high-variance accounts
- Output is read-only analysis artifact.

### Step 4 — Proposed Actions (No Write Yet)
- Agent produces proposed action list:
  - suggested journal adjustments
  - required supporting docs
  - unresolved blockers
- Each proposed action labeled by risk level.

### Step 5 — Approval Gate
- Approver reviews proposed actions.
- Approved actions are tagged for execution scope (if execution enabled).
- Rejected actions remain logged with reason.

### Step 6 — Controlled Execution (Optional in POC)
- For approved low/medium-risk actions only, gateway validates write scope and policy.
- Executes or stages operation depending on policy mode.

### Step 7 — Audit Export
- Gateway emits run summary including:
  - selected servers/routes
  - policy decisions and matched rules
  - approvals/rejections
  - final action outcomes

## Required Outputs
1. `reconciliation-summary.md`
2. `proposed-actions.json`
3. `approval-log.json`
4. `audit-report.json`

## Success Criteria
- End-to-end run completed without unauthorized action.
- At least one meaningful mismatch/proposal identified from sample data.
- Audit report accepted by finance reviewer as usable.
