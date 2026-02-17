# Immediate Next Sprint Tasks

## Completed in Phase 1
- [x] Implement DB-backed gateway registry (SQLite).
- [x] Add policy rule management endpoints (list/create/delete).
- [x] Expand dry-run route response with deny reasons and health filtering.
- [x] Export gateway metrics (`/gateway/metrics`) with Prometheus counters.
- [x] Add API tests for `/gateway/*` and policy engine tests.

## Completed in Phase 2 (current slice)
- [x] Add richer transport validation by transport type.
- [x] Add weighted route strategy and failover selection.
- [x] Add tenant-scoped RBAC token model (replacing single shared admin header model).
- [x] Add CI workflow for gateway tests.

## Next (Phase 3 candidates)
- [ ] Add DB migration/versioning framework for gateway tables.
- [ ] Implement real transport execution adapters (SSE/WS/stdio/streamable-http).
- [ ] Add per-action audit log table and replay tooling.
- [ ] Add integration tests with live ephemeral MCP upstream stubs.

## API Hardening Sprint (Now)
### First-value checkpoint (today)
- [x] Run gateway policy/API tests in project venv (`3 passed`).
- [x] Run preflight check and capture runtime readiness caveats.
- [x] Produce partner-ready API hardening checklist with owners.

### Workstream A — API contract hardening
- [ ] Freeze request/response schemas for token, server, and dry-run endpoints.
- [ ] Add schema examples to `docs/api_spec.yaml` + README snippets.
- [ ] Add negative tests for malformed payloads and missing scopes.

### Workstream B — Auth and token lifecycle
- [ ] Add token expiry/rotation semantics and validation checks.
- [ ] Document admin bootstrap vs tenant-operator lifecycle.
- [ ] Add tests for expired/revoked token behavior.

### Workstream C — Audit completeness
- [x] Expand audit report with per-step action trace and actor identity.
- [x] Add explicit event IDs and timestamps for replayability.
- [x] Add tests asserting required audit fields.

### Workstream D — Integration credibility
- [ ] Add one finance-adjacent upstream stub flow with deterministic fixture data.
- [ ] Produce one fresh allow-path + one denied-path artifact bundle.
- [ ] Update partner demo script to point to latest artifacts.
