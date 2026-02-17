# Finance Policy Templates v1

These templates are intended for POC tenants and should be adapted per customer policy.

## 1) Read-Only Analysis Mode
Use when validating trust and analysis quality before allowing writes.

### Scopes
- `gateway:read`
- `gateway:plan`

### Rules
```json
[
  {
    "name": "allow-finance-read",
    "effect": "allow",
    "actions": ["read", "plan"],
    "resources": ["gateway.server.*"],
    "tenants": ["tenant-a"]
  },
  {
    "name": "deny-finance-write",
    "effect": "deny",
    "actions": ["write", "execute"],
    "resources": ["gateway.server.*"],
    "tenants": ["tenant-a"]
  }
]
```

## 2) Propose-Only Mode
Use for human-in-the-loop operations where agent may suggest writes but not execute.

### Scopes
- `gateway:read`
- `gateway:plan`

### Rules
```json
[
  {
    "name": "allow-read-and-propose",
    "effect": "allow",
    "actions": ["read", "plan", "propose"],
    "resources": ["gateway.server.*"],
    "tenants": ["tenant-a"]
  },
  {
    "name": "deny-direct-execution",
    "effect": "deny",
    "actions": ["write", "execute"],
    "resources": ["gateway.server.*"],
    "tenants": ["tenant-a"]
  }
]
```

## 3) Restricted Execution Mode
Use after trust is established; allows controlled writes with approvals.

### Scopes
- `gateway:read`
- `gateway:plan`
- `gateway:write`

### Rules
```json
[
  {
    "name": "allow-read-plan",
    "effect": "allow",
    "actions": ["read", "plan"],
    "resources": ["gateway.server.*"],
    "tenants": ["tenant-a"]
  },
  {
    "name": "allow-low-risk-exec",
    "effect": "allow",
    "actions": ["execute"],
    "resources": ["gateway.server.srv-journal-lowrisk"],
    "tenants": ["tenant-a"]
  },
  {
    "name": "deny-high-risk-exec",
    "effect": "deny",
    "actions": ["execute"],
    "resources": ["gateway.server.srv-journal-highrisk"],
    "tenants": ["tenant-a"]
  }
]
```

## Operational Notes
- Keep deny-by-default as baseline.
- Require explicit approval artifact before `execute` actions.
- Periodically review matched-rule logs to tighten scope.
