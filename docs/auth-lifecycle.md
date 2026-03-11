# Auth & Token Lifecycle

## Overview

AgentGate uses bearer tokens (`x-gateway-token` header) for all authenticated endpoints. Tokens are stored in SQLite and carry role, scopes, tenant binding, and optional expiry.

## Token Model

| Field | Type | Description |
|-------|------|-------------|
| `token` | string | Unique bearer value (primary key) |
| `subject_id` | string | Human-readable identity |
| `tenant_id` | string? | Tenant scope (null = cross-tenant) |
| `role` | enum | `admin`, `tenant-operator`, `reader` |
| `scopes` | set | e.g. `gateway:read`, `gateway:write`, `gateway:plan`, `gateway:*` |
| `enabled` | bool | Set to false on revocation |
| `expires_at` | ISO-8601? | Optional expiry timestamp (UTC) |
| `revoked_at` | ISO-8601? | Set when token is revoked |

## 1. Admin Token Bootstrap

On server startup, the gateway reads `MCP_GATEWAY_ADMIN_TOKEN` (env var, default `dev-gateway-token`) and upserts it as:

```
token:      <env value>
subject_id: bootstrap-admin
role:       admin
scopes:     {gateway:*}
enabled:    true
```

This token has full access and is the root credential for all subsequent provisioning. In production, set `MCP_GATEWAY_ADMIN_TOKEN` to a strong random value and rotate it regularly.

## 2. Tenant Operator Provisioning

An admin creates tenant-scoped tokens via `POST /gateway/access/tokens`:

```bash
curl -X POST http://localhost:8000/gateway/access/tokens \
  -H "x-gateway-token: $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "token": "tenant-a-token",
    "subject_id": "tenant-a-ops",
    "tenant_id": "tenant-a",
    "role": "tenant-operator",
    "scopes": ["gateway:read", "gateway:write", "gateway:plan"],
    "expires_at": "2026-06-30T23:59:59+00:00"
  }'
```

Tenant operators can only access resources within their `tenant_id` scope.

## 3. Token Expiry

- `expires_at` is an optional ISO-8601 UTC timestamp.
- On every authenticated request, the gateway checks: if `expires_at` is set and in the past, the request is rejected with **401 Token expired**.
- Expiry is enforced in the authentication layer (`_require_actor`), before any authorization checks.

## 4. Token Rotation

To rotate a token:

1. Create a new token with a new value and the same scopes/role:
   ```bash
   curl -X POST http://localhost:8000/gateway/access/tokens \
     -H "x-gateway-token: $ADMIN_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{
       "token": "tenant-a-token-v2",
       "subject_id": "tenant-a-ops",
       "tenant_id": "tenant-a",
       "role": "tenant-operator",
       "scopes": ["gateway:read", "gateway:write", "gateway:plan"],
       "expires_at": "2026-12-31T23:59:59+00:00"
     }'
   ```

2. Update clients to use the new token.

3. Revoke the old token:
   ```bash
   curl -X POST http://localhost:8000/gateway/access/tokens/tenant-a-token/revoke \
     -H "x-gateway-token: $ADMIN_TOKEN"
   ```

## 5. Token Revocation

`POST /gateway/access/tokens/{token}/revoke` (admin only):

- Sets `enabled = false` and records `revoked_at` timestamp.
- Revoked tokens are immediately rejected with **403 Gateway token disabled**.
- Revocation is permanent — to restore access, create a new token.

## 6. Request Authentication Flow

```
Request arrives
  → Extract x-gateway-token header
  → Missing? → 401 "x-gateway-token required"
  → Look up token in DB
  → Not found? → 401 "Invalid gateway token"
  → Token disabled? → 403 "Gateway token disabled"
  → Token expired? → 401 "Token expired"
  → Proceed to authorization (scope + tenant checks)
```

## 7. Scope Reference

| Scope | Grants |
|-------|--------|
| `gateway:read` | List servers, export audit log |
| `gateway:write` | Register servers, set health |
| `gateway:plan` | Execute dry-run route planning |
| `gateway:policy:read` | List policy rules |
| `gateway:policy:write` | Create/delete policy rules |
| `gateway:*` | All of the above (admin wildcard) |
