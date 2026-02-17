# Partner-Ready API Hardening Checklist

## Goal
Move AgentGate from pilot-capable API to partner-ready API without widening scope.

## Owner model
- **Primary owner:** William + TimTam
- **Validation owner:** CI + artifact checks

## 1) Contract stability
- [ ] Freeze schemas for:
  - `POST /gateway/access/tokens`
  - `POST /gateway/servers`
  - `POST /gateway/routes/dry-run`
- [ ] Add canonical success/error examples in `docs/api_spec.yaml`
- [ ] Add compatibility note for any schema changes

## 2) Auth lifecycle
- [ ] Define token expiry fields and enforcement behavior
- [ ] Define rotation/revocation process
- [ ] Test: missing scope / wrong tenant / expired token

## 3) Audit completeness
- [ ] Ensure audit output includes: actor, tenant, action, decision, matched rule, timestamp, event id
- [ ] Ensure both allow and deny paths are captured
- [ ] Add replay/readability notes for partner review

## 4) Operational proof
- [ ] Preflight check passes in documented runtime
- [ ] Policy/API test suite passes in CI and local venv
- [ ] Fresh artifact bundle generated and linked in docs

## 5) Partner packaging
- [ ] Update partner brief with current guarantees only
- [ ] Update demo script to latest artifact paths
- [ ] Include one-page “How to know it is working” checklist

## Current evidence snapshot
- Local venv tests: **3 passed** (`gateway_tests/test_gateway_policy.py`, `gateway_tests/test_gateway_api.py`)
- Preflight caveat: host shell lacked active python env; venv resolves imports.
