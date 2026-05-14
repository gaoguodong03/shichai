#!/usr/bin/env bash
# Full business-flow regression: backend full pytest + frontend production build.
# Run from anywhere:
#   ./scripts/test-full-flow.sh
#
# Env:
#   SKIP_BACKEND=1             skip backend tests
#   SKIP_FRONTEND=1            skip frontend build
#   FRONTEND_INSTALL=auto      default; run npm ci only when node_modules is missing
#   FRONTEND_INSTALL=always    always run npm ci before build
#   FRONTEND_INSTALL=skip      never run npm ci, only npm run build
#   BACKEND_PY=/path/to/python force backend Python
#   SHUTONG_CONDA_ENV=name     conda env for fallback (default: st49)

set -u

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

SHUTONG_CONDA_ENV="${SHUTONG_CONDA_ENV:-st49}"
FRONTEND_INSTALL="${FRONTEND_INSTALL:-auto}"
BACKEND_RUN_MODE=""

if [[ -n "${BACKEND_PY:-}" ]]; then
  BACKEND_RUN_MODE="BACKEND_PY"
elif [[ -n "${CONDA_PREFIX:-}" && -x "${CONDA_PREFIX}/bin/python" && "${CONDA_DEFAULT_ENV:-}" == "${SHUTONG_CONDA_ENV}" ]]; then
  BACKEND_PY="${CONDA_PREFIX}/bin/python"
  BACKEND_RUN_MODE="conda_prefix(${CONDA_DEFAULT_ENV:-active})"
elif [[ -x "$ROOT/backend/venv/bin/python" ]]; then
  BACKEND_PY="$ROOT/backend/venv/bin/python"
  BACKEND_RUN_MODE="backend/venv"
elif [[ -x "$ROOT/backend/.venv/bin/python" ]]; then
  BACKEND_PY="$ROOT/backend/.venv/bin/python"
  BACKEND_RUN_MODE="backend/.venv"
elif command -v conda >/dev/null 2>&1; then
  BACKEND_PY=""
  BACKEND_RUN_MODE="conda_run(${SHUTONG_CONDA_ENV})"
else
  BACKEND_PY="python3"
  BACKEND_RUN_MODE="python3(PATH)"
fi

BACKEND_STATUS="skipped"
FRONTEND_STATUS="skipped"
BACKEND_EXIT=0
FRONTEND_EXIT=0

cleanup_backend_caches() {
  find "$ROOT/backend" -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
  find "$ROOT/backend" -type f -name "*.pyc" -delete 2>/dev/null || true
}

echo "========== full-flow tests (repo: $ROOT) =========="
echo "backend scope: full pytest suite"
echo "frontend scope: vue-tsc + vite build"

if [[ "${SKIP_BACKEND:-0}" != "1" ]]; then
  echo ""
  if [[ "$BACKEND_RUN_MODE" == conda_run* ]]; then
    echo ">>> [backend] conda run ... python -m pytest --tb=short  (cwd: backend)"
    (cd "$ROOT/backend" && conda run --no-capture-output -n "${SHUTONG_CONDA_ENV}" python -m pytest --tb=short)
  else
    echo ">>> [backend] $BACKEND_PY -m pytest --tb=short  (cwd: backend)  [${BACKEND_RUN_MODE}]"
    (cd "$ROOT/backend" && "$BACKEND_PY" -m pytest --tb=short)
  fi
  BACKEND_EXIT=$?
  cleanup_backend_caches
  if [[ "$BACKEND_EXIT" -eq 0 ]]; then
    BACKEND_STATUS="PASS"
  else
    BACKEND_STATUS="FAIL (exit $BACKEND_EXIT)"
  fi
fi

if [[ "${SKIP_FRONTEND:-0}" != "1" ]]; then
  echo ""
  if [[ "$FRONTEND_INSTALL" == "always" ]]; then
    echo ">>> [frontend] npm ci && npm run build"
    (cd "$ROOT/frontend" && npm ci && npm run build)
  elif [[ "$FRONTEND_INSTALL" == "skip" ]]; then
    echo ">>> [frontend] npm run build (FRONTEND_INSTALL=skip)"
    (cd "$ROOT/frontend" && npm run build)
  else
    if [[ -d "$ROOT/frontend/node_modules" ]]; then
      echo ">>> [frontend] npm run build (node_modules exists; FRONTEND_INSTALL=auto)"
      (cd "$ROOT/frontend" && npm run build)
    else
      echo ">>> [frontend] npm ci && npm run build (node_modules missing; FRONTEND_INSTALL=auto)"
      (cd "$ROOT/frontend" && npm ci && npm run build)
    fi
  fi
  FRONTEND_EXIT=$?
  if [[ "$FRONTEND_EXIT" -eq 0 ]]; then
    FRONTEND_STATUS="PASS"
  else
    FRONTEND_STATUS="FAIL (exit $FRONTEND_EXIT)"
  fi
fi

echo ""
echo "========== summary =========="
echo "  backend:  $BACKEND_STATUS"
echo "  frontend: $FRONTEND_STATUS"
echo "=============================="

if [[ "${SKIP_BACKEND:-0}" != "1" && "$BACKEND_EXIT" -ne 0 ]]; then
  exit "$BACKEND_EXIT"
fi
if [[ "${SKIP_FRONTEND:-0}" != "1" && "$FRONTEND_EXIT" -ne 0 ]]; then
  exit "$FRONTEND_EXIT"
fi
exit 0
