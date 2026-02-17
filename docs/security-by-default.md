# Security-by-Default for Agent Operations

AgentGate is designed so that policy and governance are core execution primitives, not optional add-ons.

## Security principles
1. **Deny by default**
   - Policy engine denies when no explicit allow rule matches.
2. **Least privilege access**
   - Tenant-scoped tokens with explicit scopes.
3. **Separation of duties**
   - Token/role model separates admin, operator, and reader capabilities.
4. **Health-aware routing**
   - Unhealthy upstream servers are excluded from route execution planning.
5. **Auditability as a first-class output**
   - Route decisions, matched rules, and reasons are included in audit artifacts.

## Control guarantees (current)

| Control | Status | How it is enforced |
|---|---|---|
| Deny-by-default policy | ✅ | `PolicyEngine` default decision is deny |
| Tenant-scoped RBAC | ✅ | `x-gateway-token` + scopes + tenant binding |
| Transport validation | ✅ | transport-specific endpoint validation before registration |
| Route safety | ✅ | failover/weighted select only healthy servers |
| Denied-path evidence | ✅ | Day-1 pilot requires explicit denied-path artifact |
| Decision traceability | ✅ | audit report includes reason + matched rule |

## Recommended deployment guardrails (next)
- Rotate access tokens on schedule
- Restrict token creation to admin channels only
- Add immutable audit event persistence
- Add alerting for repeated deny events and health flaps
