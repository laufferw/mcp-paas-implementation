# Finance Pilot Readiness Checklist

## Technical
- [ ] Tenant token bootstrap flow documented
- [ ] At least 2 healthy servers registered for tenant
- [ ] Policy template applied (read-only or propose-only)
- [ ] Dry-run route planning verified
- [ ] Audit export generated from test run

## Workflow
- [ ] Canonical workflow runbook reviewed with pilot stakeholder
- [ ] Approval gate owner assigned
- [ ] Risk tiers defined for proposed actions

## Validation
- [ ] Unauthorized write attempt is denied
- [ ] Unhealthy server is excluded from route selection
- [ ] Failover strategy selects backup server
- [ ] Weighted strategy returns valid healthy server

## Pilot Ops
- [ ] Success metrics agreed
- [ ] Weekly feedback cadence scheduled
- [ ] Issue escalation owner assigned
