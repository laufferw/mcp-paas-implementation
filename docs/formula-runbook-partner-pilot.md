# Formula Runbook: Partner Pilot (AgentGate)

Repeatable operator flow for a partner-facing pilot demonstration.

## Formula name
`partner-pilot-v1`

## Inputs
- `BASE_URL` (e.g., `http://localhost:8000`)
- `ADMIN_TOKEN`
- `TENANT_ID`
- `TENANT_TOKEN`
- `OUTDIR` (default: `pilot-artifacts/YYYY-MM-DD`)

## Steps
1. **Preflight**
   - Run `./scripts/preflight_check.sh $BASE_URL`
   - Exit if critical preflight fails.

2. **Onboarding**
   - Run `./scripts/pilot_onboarding.sh $BASE_URL $ADMIN_TOKEN $TENANT_ID $TENANT_TOKEN`

3. **Route proofs**
   - Run failover dry-run (expected allow)
   - Run weighted dry-run (expected allow)
   - Run denied-path dry-run (expected deny)

4. **Audit packaging**
   - Run `./scripts/run_day1_internal_pilot.sh ...`
   - Verify `audit-report.json` includes decision metadata and action trace

5. **Demo-ready check**
   - Confirm artifacts exist:
     - `audit-report.json`
     - `failover-dry-run.json`
     - `weighted-dry-run.json`
     - `denied-dry-run.json`
   - Confirm at least one allow and one deny decision are present.

## Exit criteria
- Preflight passed (or documented exception)
- Route proofs generated and valid
- Audit report contains replayable decision evidence
- Demo script references latest artifact directory

## Failure handling
- If preflight fails: stop and remediate before proceeding.
- If proofs are incomplete: rerun onboarding + route steps.
- If audit report missing required fields: treat as blocker.
