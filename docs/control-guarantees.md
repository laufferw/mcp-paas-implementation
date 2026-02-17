# Control Guarantees Matrix

## Purpose
Provide a concise, partner-facing map of what the platform guarantees today in pilot mode.

| Guarantee | Current State | Evidence Artifact |
|---|---|---|
| No implicit access | Enforced | Policy deny-by-default behavior in dry-run output |
| Scoped tenant access | Enforced | Token role/scope checks in API responses |
| Unsafe route blocking | Enforced | `denied-dry-run.json` |
| Route selection transparency | Enforced | `audit-report.json.routeDecisions` |
| Approval-aware operation path | Partially enforced (placeholder approval log) | `approval-log.json` |
| Production-grade immutable audit trail | Not yet complete | Planned in next phase |

## Interpretation
- **Enforced:** available and testable in current pilot.
- **Partially enforced:** implemented path exists but needs hardening.
- **Not yet complete:** roadmap item; do not over-claim.
