# Config + Preflight Lint Checklist

Run this before pilot runs, demos, or claiming completion.

## Runtime and dependency lint
- [ ] Python environment is active (`.venv` or target runtime)
- [ ] Required imports load (FastAPI, jwt/PyJWT, project modules)
- [ ] `pip install -r requirements.txt` completes without unresolved pins

## Service preflight lint
- [ ] `./scripts/preflight_check.sh http://localhost:8000` executed
- [ ] Health endpoint is reachable (or blocker documented)
- [ ] Required env vars are set for scenario (DB path, admin token)

## Policy and auth lint
- [ ] Token scopes match intended operation (`gateway:read|write|plan`)
- [ ] Tenant ID and rule tenants align
- [ ] Deny-by-default behavior verified for non-allowed action

## Evidence lint
- [ ] At least one allowed-path artifact produced
- [ ] At least one denied-path artifact produced
- [ ] Audit report includes decision reason and matched rule

## Delivery lint
- [ ] Relevant tests pass (or explicit blocker is documented)
- [ ] README/docs changed if behavior changed
- [ ] Final update includes proof links/paths (not assertions)
