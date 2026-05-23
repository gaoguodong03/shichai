#!/usr/bin/env bash
# Frontend user-visible UI flow regression.
# Run from anywhere:
#   ./scripts/test-ui-flow.sh
#
# Env:
#   FRONTEND_INSTALL=auto      default; run npm ci only when node_modules is missing
#   FRONTEND_INSTALL=always    always run npm ci before E2E
#   FRONTEND_INSTALL=skip      never run npm ci, only npm run test:e2e:full

set -u

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FRONTEND_INSTALL="${FRONTEND_INSTALL:-auto}"

echo "========== ui-flow tests (repo: $ROOT) =========="
echo "scope: frontend/e2e/*.spec.ts via Playwright Chrome"

if [[ "$FRONTEND_INSTALL" == "always" ]]; then
  echo ">>> [frontend] npm ci && npm run test:e2e:full"
  (cd "$ROOT/frontend" && npm ci && npm run test:e2e:full)
elif [[ "$FRONTEND_INSTALL" == "skip" ]]; then
  echo ">>> [frontend] npm run test:e2e:full (FRONTEND_INSTALL=skip)"
  (cd "$ROOT/frontend" && npm run test:e2e:full)
else
  if [[ -d "$ROOT/frontend/node_modules" ]]; then
    echo ">>> [frontend] npm run test:e2e:full (node_modules exists; FRONTEND_INSTALL=auto)"
    (cd "$ROOT/frontend" && npm run test:e2e:full)
  else
    echo ">>> [frontend] npm ci && npm run test:e2e:full (node_modules missing; FRONTEND_INSTALL=auto)"
    (cd "$ROOT/frontend" && npm ci && npm run test:e2e:full)
  fi
fi

STATUS=$?
echo ""
echo "========== summary =========="
if [[ "$STATUS" -eq 0 ]]; then
  echo "  ui-flow: PASS"
else
  echo "  ui-flow: FAIL (exit $STATUS)"
fi
echo "============================="
exit "$STATUS"
