# Day-1 Internal Pilot Runbook (Finance POC)

## Objective
Run one full internal pilot cycle end-to-end and produce evidence artifacts we can show design partners.

## Inputs
- Gateway running locally
- Admin token configured (`MCP_GATEWAY_ADMIN_TOKEN`)
- Pilot tenant id (default: `tenant-a`)

## Step 0 — Environment check
- Confirm gateway health endpoint responds
- Confirm CI passing on `main`

## Step 1 — Bootstrap pilot tenant
Run:

```bash
./scripts/pilot_onboarding.sh http://localhost:8000 dev-gateway-token tenant-a tenant-a-token
```

Expected result:
- tenant token created
- two servers registered
- plan policy rule created
- dry-run sanity check succeeds

## Step 2 — Run dry-run scenarios
Execute these checks:
1. Preferred strategy with explicit server
2. Failover strategy (ensure priority behavior)
3. Weighted strategy (ensure healthy selection)
4. Unhealthy server rejection path

## Step 3 — Produce artifacts
Create folder `pilot-artifacts/YYYY-MM-DD/` with:
- `reconciliation-summary.md`
- `proposed-actions.json`
- `approval-log.json`
- `audit-report.json`

## Step 4 — Evaluate against POC criteria
- Any unauthorized action allowed? (must be no)
- Did route planning provide clear denial reasons?
- Is audit output readable by non-engineering stakeholder?

## Step 5 — Log issues
Open issues using `/.github/ISSUE_TEMPLATE/pilot-blocker.md`.
Label with severity: `pilot-blocker:p0|p1|p2`.

## Exit condition for Day-1
Internal pilot is successful when:
- onboarding flow completes,
- at least one realistic dry-run scenario and one denied scenario are demonstrated,
- all four artifacts are generated,
- top blockers are documented with owners.
