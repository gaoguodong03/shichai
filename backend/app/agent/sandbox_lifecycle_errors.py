"""Lifecycle error classification and messages for OpenSandbox."""
from __future__ import annotations


class SandboxEnvironmentError(RuntimeError):
    """Non-retryable sandbox infrastructure/configuration failure."""


def is_host_path_mount_source_error(error: Exception) -> bool:
    text = str(error or "")
    return "mount source path" in text and ("/host_mnt/" in text or "host_path" in text)


def is_lifecycle_connect_error(error: Exception) -> bool:
    text = str(error or "").lower()
    return (
        "opensandbox lifecycle api" in text
        or "all connection attempts failed" in text
        or "connecterror" in text
        or "connection refused" in text
    )


def lifecycle_connect_error_message(error: Exception) -> str:
    return (
        "OpenSandbox lifecycle API 连接失败：当前应用进程无法连接 OpenSandbox 服务。"
        "请确认 1Panel 编排中的 opensandbox-server 已启动，"
        "并检查 OPENSANDBOX_DOMAIN/OPENSANDBOX_HOST_PORT 是否指向应用容器可达的地址。"
        "本地 conda 调试时，需要显式启动本地 OpenSandbox 服务或配置 OPENSANDBOX_COMPOSE_FILE 指向本地 compose；"
        "docker-compose.1panel.yml 只用于远程 1Panel 编排，不再作为本地自动启动配置。"
        f" 原始错误: {error}"
    )


def opensandbox_lifecycle_reachable() -> tuple[bool, str]:
    from app.core import dev_bootstrap

    host, port = dev_bootstrap.parse_opensandbox_target()
    target = f"{host}:{port}"
    return dev_bootstrap.can_connect(host, port, timeout=0.25), target
