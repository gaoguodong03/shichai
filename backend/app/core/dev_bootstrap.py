"""本地开发启动辅助。"""
import os
import socket
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from app.core.runtime_env import is_truthy_env


def can_connect(host: str, port: int, timeout: float = 0.8) -> bool:
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def http_ok(url: str, timeout: float = 1.0) -> bool:
    try:
        req = Request(url, method="GET")
        with urlopen(req, timeout=timeout) as resp:  # nosec B310 - local health check only
            return 200 <= int(getattr(resp, "status", 0)) < 300
    except Exception:
        return False


def parse_opensandbox_target() -> tuple[str, int]:
    raw = (os.getenv("OPENSANDBOX_DOMAIN") or os.getenv("OPEN_SANDBOX_DOMAIN") or "127.0.0.1:8091").strip()
    if "://" not in raw:
        raw = "http://" + raw
    parsed = urlparse(raw)
    host = parsed.hostname or "127.0.0.1"
    port = int(parsed.port or 8091)
    return host, port


def auto_bootstrap_opensandbox() -> None:
    """Local dev bootstrap: auto `docker compose up -d opensandbox-server` when unreachable."""
    if not is_truthy_env("AUTO_START_OPENSANDBOX", "1"):
        return
    host, port = parse_opensandbox_target()
    if can_connect(host, port):
        return

    backend_root = Path(__file__).resolve().parent.parent.parent
    repo_root = backend_root.parent
    compose_file = (os.getenv("OPENSANDBOX_COMPOSE_FILE") or "").strip()
    if compose_file:
        compose_path = Path(compose_file).expanduser()
        if not compose_path.is_absolute():
            compose_path = (repo_root / compose_path).resolve()
    else:
        candidates = [repo_root / "docker-compose.yml", repo_root / "docker-compose.1panel.yml"]
        compose_path = next((p for p in candidates if p.exists()), candidates[-1])

    print(f"[startup] OpenSandbox 不可达 {host}:{port}，尝试自动启动 docker compose: {compose_path} ...")
    try:
        proc = subprocess.run(
            ["docker", "compose", "-f", str(compose_path), "up", "-d", "opensandbox-server"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception as e:  # noqa: BLE001
        print(f"[startup] 自动启动 OpenSandbox 失败：{e}")
        return

    if proc.returncode != 0:
        out = (proc.stderr or proc.stdout or "").strip()
        print(f"[startup] 自动启动 OpenSandbox 失败：{out}")
        return

    for _ in range(20):
        if can_connect(host, port) and http_ok(f"http://{host}:{port}/health"):
            print("[startup] OpenSandbox 已就绪。")
            return
        time.sleep(0.5)
    print("[startup] OpenSandbox 仍未就绪，请检查 Docker Desktop 或 `docker compose logs opensandbox-server`。")


def reuse_existing_backend(host: str, port: int) -> bool:
    """If backend already running, skip a second bind and exit gracefully."""
    if not is_truthy_env("REUSE_EXISTING_BACKEND", "1"):
        return False
    if not can_connect(host, port):
        return False
    if http_ok(f"http://{host}:{port}/health"):
        print(f"[startup] 检测到后端已在运行：http://{host}:{port} ，本次不重复启动。")
        return True
    print(f"[startup] 端口 {port} 已被占用且不是当前服务，请先释放端口后重试。")
    return True
