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
