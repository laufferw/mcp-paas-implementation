#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${1:-http://localhost:8000}"

ok() { echo "[OK] $1"; }
warn() { echo "[WARN] $1"; }
fail() { echo "[FAIL] $1"; exit 1; }

command -v python3 >/dev/null 2>&1 && ok "python3 available" || fail "python3 missing"

if python3 -c "import fastapi" >/dev/null 2>&1; then
  ok "fastapi import works"
else
  warn "fastapi not importable in current python env"
fi

if command -v curl >/dev/null 2>&1; then
  ok "curl available"
else
  fail "curl missing"
fi

if curl -sS -m 3 "$BASE_URL/health" >/dev/null 2>&1; then
  ok "gateway health reachable at $BASE_URL/health"
else
  warn "gateway health not reachable at $BASE_URL/health"
fi

echo "Preflight complete."
