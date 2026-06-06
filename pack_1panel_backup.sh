#!/usr/bin/env bash
set -euo pipefail

# Generate 1Panel "compose backup" tarball that contains compose_meta.json.
# backend/.env is optional: when absent, the package gets generated defaults.
# Optional: pass an ST49 image tag to build/push ST49 image before packaging.
# Usage:
#   bash pack_1panel_backup.sh                 # only generate backup tarball
#   bash pack_1panel_backup.sh 26.05.12.6      # docker build + push, then package
# Output: <repo_root>/1panel-compose-backup.tar.gz

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Prefer git to locate repo root (works regardless of script location).
if command -v git >/dev/null 2>&1; then
  REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel 2>/dev/null || true)"
else
  REPO_ROOT=""
fi

# Fallbacks:
# - if script is in <repo>/scripts/, use parent
# - if script is in <repo>/, use itself
if [[ -z "${REPO_ROOT:-}" ]]; then
  if [[ "$(basename "$SCRIPT_DIR")" == "scripts" ]]; then
    REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
  else
    REPO_ROOT="$SCRIPT_DIR"
  fi
fi
cd "$REPO_ROOT"

IMAGE_TAG="${1:-}"
if [[ $# -gt 1 ]]; then
  echo "ERROR: too many arguments" >&2
  echo "Usage: bash $(basename "$0") [image_tag]" >&2
  exit 2
fi

ENV_FILE="${ENV_FILE:-backend/.env}"
if [[ -f "$ENV_FILE" ]]; then
  load_env_default() {
    local key="$1"
    local line=""
    local value=""
    if [[ "${!key+x}" == "x" ]]; then
      return 0
    fi
    line="$(grep -E "^[[:space:]]*${key}=" "$ENV_FILE" | tail -n 1 || true)"
    if [[ -z "$line" ]]; then
      return 0
    fi
    value="${line#*=}"
    value="${value%$'\r'}"
    value="${value#"${value%%[![:space:]]*}"}"
    value="${value%"${value##*[![:space:]]}"}"
    if [[ "$value" == \"*\" && "$value" == *\" ]]; then
      value="${value:1:${#value}-2}"
    elif [[ "$value" == \'*\' && "$value" == *\' ]]; then
      value="${value:1:${#value}-2}"
    fi
    export "$key=$value"
  }
  for env_key in \
    SANDBOX_VERSION \
    SANDBOX_STANDARD_VERSION \
    SANDBOX_PLAYWRIGHT_VERSION \
    IMAGE_REPO \
    SANDBOX_IMAGE_REPO \
    NODE_IMAGE \
    PYTHON_IMAGE \
    SANDBOX_PYTHON_IMAGE \
    INSTALL_APP_NODE_EXTRAS \
    PREWARM_NPX_MCP \
    ST49_SANDBOX_STANDARD_IMAGE \
    ST49_SANDBOX_PLAYWRIGHT_IMAGE \
    SANDBOX_STANDARD_IMAGE \
    SANDBOX_PLAYWRIGHT_IMAGE \
    SANDBOX_ALWAYS_ON \
    SANDBOX_PREWARM_ALL_USERS \
    SANDBOX_PREWARM_ON_USER_REQUEST \
    SANDBOX_RESTART_ONLY_ON_REQUIREMENTS_UPDATE \
    SANDBOX_SESSION_ISOLATION; do
    load_env_default "$env_key"
  done
  unset -f load_env_default
fi

DEFAULT_ST49_VERSION="26.06.06"
ST49_VERSION="$DEFAULT_ST49_VERSION"
# Sandbox images are intentionally versioned independently from ST49.
# Do not derive them from IMAGE_TAG by default: otherwise a normal app release like
# `bash pack_1panel_backup.sh 26.05.12.23` would make 1Panel point to
# unpublished sandbox tags.
DEFAULT_SANDBOX_STANDARD_VERSION="26.05.12.1"
DEFAULT_SANDBOX_PLAYWRIGHT_VERSION="26.05.15"
SANDBOX_VERSION="${SANDBOX_VERSION:-}"
SANDBOX_STANDARD_VERSION="${SANDBOX_STANDARD_VERSION:-${SANDBOX_VERSION:-$DEFAULT_SANDBOX_STANDARD_VERSION}}"
SANDBOX_PLAYWRIGHT_VERSION="${SANDBOX_PLAYWRIGHT_VERSION:-${SANDBOX_VERSION:-$DEFAULT_SANDBOX_PLAYWRIGHT_VERSION}}"
IMAGE_REPO="${IMAGE_REPO:-crpi-hzqv5l81v3ftz5jl.cn-beijing.personal.cr.aliyuncs.com/free4inno-yuanfang2025/dha}"
SANDBOX_IMAGE_REPO="${SANDBOX_IMAGE_REPO:-crpi-hzqv5l81v3ftz5jl.cn-beijing.personal.cr.aliyuncs.com/free4inno-yuanfang2025/sandbox}"
NODE_IMAGE="${NODE_IMAGE:-node:20-bookworm-slim}"
PYTHON_IMAGE="${PYTHON_IMAGE:-python:3.12-slim}"
SANDBOX_PYTHON_IMAGE="${SANDBOX_PYTHON_IMAGE:-python:3.12-bookworm}"
INSTALL_APP_NODE_EXTRAS="${INSTALL_APP_NODE_EXTRAS:-0}"
PREWARM_NPX_MCP="${PREWARM_NPX_MCP:-0}"
if [[ -n "$IMAGE_TAG" ]]; then
  ST49_VERSION="$IMAGE_TAG"
  ST49_IMAGE="${IMAGE_REPO}:${IMAGE_TAG}"
else
  ST49_IMAGE="${IMAGE_REPO}:$ST49_VERSION"
fi
SANDBOX_STANDARD_IMAGE="${ST49_SANDBOX_STANDARD_IMAGE:-${SANDBOX_STANDARD_IMAGE:-${SANDBOX_IMAGE_REPO}:${SANDBOX_STANDARD_VERSION}-standard}}"
SANDBOX_PLAYWRIGHT_IMAGE="${ST49_SANDBOX_PLAYWRIGHT_IMAGE:-${SANDBOX_PLAYWRIGHT_IMAGE:-${SANDBOX_IMAGE_REPO}:${SANDBOX_PLAYWRIGHT_VERSION}-playwright}}"
SANDBOX_ALWAYS_ON="${SANDBOX_ALWAYS_ON:-1}"
SANDBOX_PREWARM_ALL_USERS="${SANDBOX_PREWARM_ALL_USERS:-0}"
SANDBOX_PREWARM_ON_USER_REQUEST="${SANDBOX_PREWARM_ON_USER_REQUEST:-0}"
SANDBOX_RESTART_ONLY_ON_REQUIREMENTS_UPDATE="${SANDBOX_RESTART_ONLY_ON_REQUIREMENTS_UPDATE:-1}"
SANDBOX_SESSION_ISOLATION="${SANDBOX_SESSION_ISOLATION:-0}"
BUILD_SANDBOX_STANDARD_IMAGE="${BUILD_SANDBOX_STANDARD_IMAGE:-${BUILD_SANDBOX_IMAGES:-0}}"
BUILD_SANDBOX_PLAYWRIGHT_IMAGE="${BUILD_SANDBOX_PLAYWRIGHT_IMAGE:-0}"
IMAGE=""
if [[ "$BUILD_SANDBOX_STANDARD_IMAGE" == "1" ]]; then
  echo "==> Building sandbox standard image: $SANDBOX_STANDARD_IMAGE"
  docker build --platform linux/amd64 \
    -f docker/skill-sandbox/Dockerfile \
    --build-arg "PYTHON_IMAGE=$SANDBOX_PYTHON_IMAGE" \
    -t "$SANDBOX_STANDARD_IMAGE" .
  if [[ "${SKIP_PUSH:-0}" == "1" ]]; then
    echo "==> SKIP_PUSH=1, not pushing sandbox image: $SANDBOX_STANDARD_IMAGE"
  else
    echo "==> Pushing sandbox image: $SANDBOX_STANDARD_IMAGE"
    docker push "$SANDBOX_STANDARD_IMAGE"
  fi
fi
if [[ "$BUILD_SANDBOX_PLAYWRIGHT_IMAGE" == "1" ]]; then
  echo "==> Building sandbox Playwright image: $SANDBOX_PLAYWRIGHT_IMAGE"
  docker build --platform linux/amd64 \
    -f docker/skill-sandbox/Dockerfile.playwright \
    --build-arg "PYTHON_IMAGE=$SANDBOX_PYTHON_IMAGE" \
    -t "$SANDBOX_PLAYWRIGHT_IMAGE" .
  if [[ "${SKIP_PUSH:-0}" == "1" ]]; then
    echo "==> SKIP_PUSH=1, not pushing sandbox image: $SANDBOX_PLAYWRIGHT_IMAGE"
  else
    echo "==> Pushing sandbox image: $SANDBOX_PLAYWRIGHT_IMAGE"
    docker push "$SANDBOX_PLAYWRIGHT_IMAGE"
  fi
fi
if [[ -n "$IMAGE_TAG" ]]; then
  if [[ "$IMAGE_TAG" == *":"* || "$IMAGE_TAG" == *"/"* ]]; then
    echo "ERROR: image_tag should be a tag only, for example: 26.04.27" >&2
    exit 2
  fi
  IMAGE="$ST49_IMAGE"
  echo "==> Building image: $IMAGE"
  echo "==> Base images: NODE_IMAGE=$NODE_IMAGE PYTHON_IMAGE=$PYTHON_IMAGE"
  echo "==> App image optional Node extras: INSTALL_APP_NODE_EXTRAS=$INSTALL_APP_NODE_EXTRAS PREWARM_NPX_MCP=$PREWARM_NPX_MCP"
  docker build --platform linux/amd64 \
    --build-arg "NODE_IMAGE=$NODE_IMAGE" \
    --build-arg "PYTHON_IMAGE=$PYTHON_IMAGE" \
    --build-arg "INSTALL_APP_NODE_EXTRAS=$INSTALL_APP_NODE_EXTRAS" \
    --build-arg "PREWARM_NPX_MCP=$PREWARM_NPX_MCP" \
    -t "$IMAGE" .
  if [[ "${SKIP_PUSH:-0}" == "1" ]]; then
    echo "==> SKIP_PUSH=1, not pushing image: $IMAGE"
  else
    echo "==> Pushing image: $IMAGE"
    docker push "$IMAGE"
  fi
fi

OUT_TGZ="${OUT_TGZ:-1panel-compose-backup.tar.gz}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.1panel.yml}"
COMPOSE_NAME="${COMPOSE_NAME:-st49}"

if [[ ! -f "$COMPOSE_FILE" ]]; then
  echo "ERROR: missing compose file: $COMPOSE_FILE" >&2
  exit 2
fi

WORK_DIR=".1panel-backup-src"
BACKUP_DIR="$WORK_DIR/1panel-compose-backup"
FILES_DIR="$BACKUP_DIR/compose_files"

rm -rf "$WORK_DIR"
mkdir -p "$FILES_DIR"

cp "$COMPOSE_FILE" "$FILES_DIR/00_docker-compose.yml"
if [[ -f "$ENV_FILE" ]]; then
  # Do not copy local secrets or host-only paths into the distributable package.
  # Allowed release knobs were already loaded above and are emitted below.
  {
    echo "# Generated env because $ENV_FILE was present."
    echo "# Local secrets are intentionally not copied; set them in 1Panel environment variables."
  } > "$FILES_DIR/.env"
else
  echo "==> No env file found at $ENV_FILE; generating package env from script defaults"
  {
    echo "# Generated empty env because $ENV_FILE was not present."
    echo "# Fill provider secrets in 1Panel if you do not inject them elsewhere."
  } > "$FILES_DIR/.env"
fi
{
  echo ""
  echo "# Generated by $(basename "$0") for 1Panel compose interpolation"
  echo "ST49_VERSION=$ST49_VERSION"
  echo "SANDBOX_VERSION=${SANDBOX_VERSION:-$SANDBOX_STANDARD_VERSION}"
  echo "SANDBOX_STANDARD_VERSION=$SANDBOX_STANDARD_VERSION"
  echo "SANDBOX_PLAYWRIGHT_VERSION=$SANDBOX_PLAYWRIGHT_VERSION"
  echo "ST49_IMAGE=$ST49_IMAGE"
  echo "ST49_SANDBOX_STANDARD_IMAGE=$SANDBOX_STANDARD_IMAGE"
  echo "ST49_SANDBOX_PLAYWRIGHT_IMAGE=$SANDBOX_PLAYWRIGHT_IMAGE"
  echo "SANDBOX_ALWAYS_ON=$SANDBOX_ALWAYS_ON"
  echo "SANDBOX_PREWARM_ALL_USERS=$SANDBOX_PREWARM_ALL_USERS"
  echo "SANDBOX_PREWARM_ON_USER_REQUEST=$SANDBOX_PREWARM_ON_USER_REQUEST"
  echo "SANDBOX_RESTART_ONLY_ON_REQUIREMENTS_UPDATE=$SANDBOX_RESTART_ONLY_ON_REQUIREMENTS_UPDATE"
  echo "SANDBOX_SESSION_ISOLATION=$SANDBOX_SESSION_ISOLATION"
  echo "QWEN_AUDIO_CHUNK_SECONDS=${QWEN_AUDIO_CHUNK_SECONDS:-120}"
  echo "AUTH_DB_PATH=/app/backend/data/auth_users.sqlite"
  echo "AUTH_USERS_FILE=/app/backend/data/auth_users.txt"
  echo "SHUTONG_USER_DATA_ROOT=/app/backend/data/users"
  echo "ACCESS_TOKEN_EXPIRE_MINUTES=${ACCESS_TOKEN_EXPIRE_MINUTES:-43200}"
} >> "$FILES_DIR/.env"

python3 - <<'PY'
import json, pathlib, datetime, os
base = pathlib.Path(".1panel-backup-src/1panel-compose-backup")
compose_name = os.environ.get("COMPOSE_NAME", "st49")
meta = {
  "composeName": compose_name,
  "composePath": "",
  "createdAt": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
  "files": [
    {
      "originalPath": os.environ.get("COMPOSE_FILE", "docker-compose.1panel.yml"),
      "fileName": "docker-compose.yml",
      "relativePath": "docker-compose.yml",
      "backupPath": "compose_files/00_docker-compose.yml",
    }
  ],
  "containers": []
}
(base / "compose_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
PY

tar -czf "$OUT_TGZ" -C "$WORK_DIR" 1panel-compose-backup

echo "OK: wrote $OUT_TGZ"
echo "ST49_IMAGE: $ST49_IMAGE"
echo "SANDBOX_STANDARD_IMAGE: $SANDBOX_STANDARD_IMAGE"
echo "SANDBOX_PLAYWRIGHT_IMAGE: $SANDBOX_PLAYWRIGHT_IMAGE"
echo "Contents:"
tar -tzf "$OUT_TGZ"
echo ""
echo "Note: compose 内 st49 依赖 OpenSandbox healthcheck；若改了 backend 里网关/沙箱逻辑，需构建并更新 ST49_IMAGE 后远端才生效。"
