# Code Mode Policy Templates — Finance Use Cases

These templates define reusable `PolicyRule` sets for common finance access patterns. Each maps to the QuickBooks-style API spec in `specs/quickbooks-sample.json`.

---

## 1. `read-only-finance`

**Use case:** Auditors, analysts, read-only dashboards. Can search the API spec and execute GET-only operations.

```python
from src.mcp_gateway.policy import PolicyRule

read_only_finance_rules = [
    PolicyRule(
        rule_id="rof-search",
        name="Allow Code Mode search",
        resource="codemode:search",
        action="execute",
        effect="allow",
        conditions={}
    ),
    PolicyRule(
        rule_id="rof-execute-get",
        name="Allow GET-only execution",
        resource="codemode:execute",
        action="execute",
        effect="allow",
        conditions={
            "http_method": "GET",
            "path_pattern": "/**"
        }
    ),
    PolicyRule(
        rule_id="rof-deny-write",
        name="Deny all write operations",
        resource="codemode:execute",
        action="execute",
        effect="deny",
        conditions={
            "http_method_in": ["POST", "PUT", "PATCH", "DELETE"]
        }
    ),
    PolicyRule(
        rule_id="rof-audit",
        name="Allow audit read",
        resource="codemode:audit",
        action="read",
        effect="allow",
        conditions={}
    ),
]
```

**Scopes required:** `gateway:codemode:search`, `gateway:codemode:execute`, `gateway:codemode:audit`

---

## 2. `finance-operator`

**Use case:** Bookkeepers, AP/AR clerks. Can read and write most resources, but journal entries and payments require admin approval before execution.

```python
finance_operator_rules = [
    PolicyRule(
        rule_id="fo-search",
        name="Allow Code Mode search",
        resource="codemode:search",
        action="execute",
        effect="allow",
        conditions={}
    ),
    PolicyRule(
        rule_id="fo-execute-read",
        name="Allow all GET operations",
        resource="codemode:execute",
        action="execute",
        effect="allow",
        conditions={
            "http_method": "GET",
            "path_pattern": "/**"
        }
    ),
    PolicyRule(
        rule_id="fo-execute-invoices",
        name="Allow invoice create/send",
        resource="codemode:execute",
        action="execute",
        effect="allow",
        conditions={
            "http_method": "POST",
            "path_pattern": "/invoices{/**}"
        }
    ),
    PolicyRule(
        rule_id="fo-execute-bills",
        name="Allow bill creation",
        resource="codemode:execute",
        action="execute",
        effect="allow",
        conditions={
            "http_method": "POST",
            "path_pattern": "/bills"
        }
    ),
    PolicyRule(
        rule_id="fo-approve-payments",
        name="Payments require approval",
        resource="codemode:execute",
        action="execute",
        effect="approve",
        conditions={
            "http_method": "POST",
            "path_pattern": "/payments"
        }
    ),
    PolicyRule(
        rule_id="fo-approve-journal",
        name="Journal entries require approval",
        resource="codemode:execute",
        action="execute",
        effect="approve",
        conditions={
            "http_method": "POST",
            "path_pattern": "/journal-entries"
        }
    ),
    PolicyRule(
        rule_id="fo-audit",
        name="Allow audit read",
        resource="codemode:audit",
        action="read",
        effect="allow",
        conditions={}
    ),
]
```

**Scopes required:** `gateway:codemode:search`, `gateway:codemode:execute`, `gateway:codemode:audit`

---

## 3. `finance-admin`

**Use case:** Controllers, CFO. Full access to all operations with no approval gates.

```python
finance_admin_rules = [
    PolicyRule(
        rule_id="fa-search",
        name="Allow Code Mode search",
        resource="codemode:search",
        action="execute",
        effect="allow",
        conditions={}
    ),
    PolicyRule(
        rule_id="fa-execute-all",
        name="Allow all execution",
        resource="codemode:execute",
        action="execute",
        effect="allow",
        conditions={
            "path_pattern": "/**"
        }
    ),
    PolicyRule(
        rule_id="fa-audit",
        name="Allow audit read",
        resource="codemode:audit",
        action="read",
        effect="allow",
        conditions={}
    ),
    PolicyRule(
        rule_id="fa-approve",
        name="Allow approving pending executions",
        resource="codemode:approve",
        action="execute",
        effect="allow",
        conditions={}
    ),
]
```

**Scopes required:** `gateway:codemode:search`, `gateway:codemode:execute`, `gateway:codemode:audit`

---

## Summary Matrix

| Capability | `read-only-finance` | `finance-operator` | `finance-admin` |
|---|---|---|---|
| Search spec | ✅ | ✅ | ✅ |
| GET any endpoint | ✅ | ✅ | ✅ |
| POST invoices/bills | ❌ | ✅ | ✅ |
| POST payments | ❌ | ⏳ Approval | ✅ |
| POST journal-entries | ❌ | ⏳ Approval | ✅ |
| View audit trail | ✅ | ✅ | ✅ |
| Approve pending | ❌ | ❌ | ✅ |
