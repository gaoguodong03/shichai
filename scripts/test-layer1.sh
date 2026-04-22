#!/usr/bin/env bash
# Layer-1 local regression: backend pytest -m layer1_core + frontend npm ci && build.
# Backend scope: orchestration, group chat, sandbox, auth, workspace, graph/MCP slice
#   (see backend/tests/conftest.py LAYER1_CORE_MODULES). Full suite: pytest without -m.
# Run from anywhere:  ./scripts/test-layer1.sh
# Env:
#   SKIP_BACKEND=1       backend only off
#   SKIP_FRONTEND=1      frontend only off
#   FRONTEND_INSTALL=skip   skip npm ci, run npm run build only (needs node_modules)
#   BACKEND_PY=/path/to/python   force interpreter for pytest
#   SHUTONG_CONDA_ENV=name   conda env for "conda run" fallback (default: st49)

set -u

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

SHUTONG_CONDA_ENV="${SHUTONG_CONDA_ENV:-st49}"
BACKEND_RUN_MODE=""

if [[ -n "${BACKEND_PY:-}" ]]; then
  BACKEND_RUN_MODE="BACKEND_PY"
elif [[ -n "${CONDA_PREFIX:-}" && -x "${CONDA_PREFIX}/bin/python" && "${CONDA_DEFAULT_ENV:-}" == "${SHUTONG_CONDA_ENV}" ]]; then
  # 仅当当前激活环境与目标环境一致（默认 st49）时，才直接使用 CONDA_PREFIX
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

echo "========== layer-1 tests (repo: $ROOT) =========="

if [[ "${SKIP_BACKEND:-0}" != "1" ]]; then
  echo ""
  if [[ "$BACKEND_RUN_MODE" == conda_run* ]]; then
    echo ">>> [backend] conda run ... pytest -m layer1_core --tb=short  (cwd: backend)"
    (cd "$ROOT/backend" && conda run --no-capture-output -n "${SHUTONG_CONDA_ENV}" python -m pytest -m layer1_core --tb=short)
  else
    echo ">>> [backend] $BACKEND_PY -m pytest -m layer1_core --tb=short  (cwd: backend)  [${BACKEND_RUN_MODE}]"
    (cd "$ROOT/backend" && "$BACKEND_PY" -m pytest -m layer1_core --tb=short)
  fi
  BACKEND_EXIT=$?
  if [[ "$BACKEND_EXIT" -eq 0 ]]; then
    BACKEND_STATUS="PASS"
  else
    BACKEND_STATUS="FAIL (exit $BACKEND_EXIT)"
  fi
fi

if [[ "${SKIP_FRONTEND:-0}" != "1" ]]; then
  echo ""
  if [[ "${FRONTEND_INSTALL:-}" == "skip" ]]; then
    echo ">>> [frontend] npm run build (FRONTEND_INSTALL=skip, no npm ci)"
    (cd "$ROOT/frontend" && npm run build)
  else
    echo ">>> [frontend] npm ci && npm run build"
    (cd "$ROOT/frontend" && npm ci && npm run build)
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
