# Immediate Next Sprint Tasks

## Completed in Phase 1
- [x] Implement DB-backed gateway registry (SQLite).
- [x] Add policy rule management endpoints (list/create/delete).
- [x] Expand dry-run route response with deny reasons and health filtering.
- [x] Export gateway metrics (`/gateway/metrics`) with Prometheus counters.
- [x] Add API tests for `/gateway/*` and policy engine tests.

## Next (Phase 2 candidates)
- [ ] Add persistent migration scripts/versioning for gateway tables.
- [ ] Add richer transport validation by transport type.
- [ ] Add weighted route strategy and fallback selection.
- [ ] Add tenant-scoped RBAC (beyond shared admin token).
- [ ] Add end-to-end integration test suite in CI.
