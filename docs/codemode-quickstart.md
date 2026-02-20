# Code Mode — Quickstart

## What is Code Mode?

Code Mode lets AI agents dynamically discover and call APIs by executing sandboxed Python code against OpenAPI specs. Instead of pre-registering every tool, agents write code that searches a spec, then executes HTTP calls — all gated by policy rules that can require approval for sensitive operations (like payments or journal entries), with a full audit trail for every action.

## Architecture

```
┌─────────────┐     ┌──────────────────────────────────────────────┐
│  AI Agent    │     │  MCP Gateway                                 │
│              │     │                                              │
│  search() ──────►  │  /gateway/codemode/search                   │
│              │     │    └─► Sandbox executor (AST-validated)      │
│              │     │    └─► Returns matched endpoints             │
│              │     │                                              │
│  execute() ─────►  │  /gateway/codemode/execute                  │
│              │     │    └─► Policy engine ── allow ──► Execute    │
│              │     │    │                └─ approve ─► Queue      │
│              │     │    │                └─ deny ────► Reject     │
│              │     │    └─► Audit logger                          │
│              │     │                                              │
│  audit() ───────►  │  /gateway/codemode/audit                    │
│              │     │    └─► Return audit events                   │
│              │     │                                              │
│  approve() ─────►  │  /gateway/codemode/approve/{id}  (admin)    │
│              │     │    └─► Execute queued code                   │
└─────────────┘     └──────────────────────────────────────────────┘
```

## Run the Server

```bash
cd /path/to/mcp-paas-implementation
pip install -r requirements.txt
uvicorn server:app --host 0.0.0.0 --port 8000
```

Verify: `curl http://localhost:8000/health`

## Run the Demo

```bash
python scripts/demo_codemode.py
```

The demo loads the QuickBooks sample spec, creates tokens, searches for invoice endpoints, executes allowed and approval-gated operations, and prints the audit trail.

## API Reference

All endpoints are under `/gateway/codemode` and require an `X-Gateway-Token` header.

### `POST /gateway/codemode/search`

Search an OpenAPI spec using sandboxed Python code.

| Field | Type | Description |
|-------|------|-------------|
| `code` | string | Python code to run in sandbox. Has access to `spec` variable. |
| `spec` | object | OpenAPI 3.x spec (JSON) |

**Response:** `{ "result": <any>, "status": "ok" }`

### `POST /gateway/codemode/execute`

Execute sandboxed code that can make API calls via `api_client`.

| Field | Type | Description |
|-------|------|-------------|
| `code` | string | Python code. Has access to `api_client`. |
| `server_id` | string | Registered server identifier |
| `base_url` | string | Target API base URL |
| `headers` | object? | Optional HTTP headers for the API |

**Response:** `{ "result": <any>, "status": "ok" | "pending_approval" | "denied" }`

### `GET /gateway/codemode/audit`

List audit events for the authenticated tenant.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `limit` | int | 50 | Max events (≤200) |
| `offset` | int | 0 | Pagination offset |

**Response:** `{ "items": [ { "event_id", "action", "code", "result", "status", ... } ] }`

## Real API Integration — QuickBooks Online

Code Mode really shines against large, real-world API specs. The QuickBooks Online V3 spec has **166 endpoints** and weighs **1.1 MB** (~280k tokens). Stuffing it into an LLM context window is expensive and often impossible.

With Code Mode, an agent searches the spec programmatically and only receives the handful of endpoints it needs — using **~1,000 tokens** instead of 280,000. That's a **99.6% reduction**.

### Setup

```bash
# .env — QuickBooks Online credentials
QBO_CLIENT_ID=your_client_id
QBO_CLIENT_SECRET=your_client_secret
QBO_REALM_ID=1234567890          # Company ID from QBO
QBO_REDIRECT_URI=http://localhost:8000/callback
QBO_ENVIRONMENT=sandbox          # sandbox or production
QBO_ACCESS_TOKEN=                # filled after OAuth flow
QBO_REFRESH_TOKEN=               # filled after OAuth flow
```

### Demos (no credentials needed)

```bash
# Token savings demo — searches the real 1.1 MB spec
python scripts/demo_quickbooks_codemode.py

# Month-end reconciliation workflow
python scripts/reconciliation_workflow.py
```

### Using the client in code

```python
from src.mcp_gateway.integrations.quickbooks import QuickBooksClient, QuickBooksConfig

config = QuickBooksConfig.from_env()
client = QuickBooksClient(config)

# QBO query language
invoices = client.query("Invoice", "Balance > '0'")
report = client.report("ProfitAndLoss", {"start_date": "2026-01-01", "end_date": "2026-01-31"})
```

### `POST /gateway/codemode/approve/{event_id}`

Admin-only. Approve and execute a pending operation.

**Response:** `{ "result": <any>, "status": "approved" }`
