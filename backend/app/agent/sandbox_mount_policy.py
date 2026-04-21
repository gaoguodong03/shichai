"""Mount planning for session workspace and skill assets."""
from __future__ import annotations

import os
from pathlib import Path
from typing import List

from app.agent.sandbox_adapter import SandboxVolumeMount

_DEFAULT_MOUNT_TYPE = os.getenv("SANDBOX_VOLUME_MOUNT_TYPE", "host_path")


def _translate_source_for_sandbox_host(path: Path) -> str:
    """
    将应用容器内路径翻译为 OpenSandbox 所在宿主机可见路径。

    通过环境变量 SANDBOX_HOST_PATH_MAP 配置，格式：
    "/app/backend/data=/var/lib/docker/volumes/st49/_data,/app/backend/config=/opt/app/config"
    """
    src = str(path.resolve())
    raw = (os.getenv("SANDBOX_HOST_PATH_MAP") or "").strip()
    if not raw:
        return src
    for item in raw.split(","):
        pair = item.strip()
        if not pair or "=" not in pair:
            continue
        left, right = pair.split("=", 1)
        left = left.strip().rstrip("/")
        right = right.strip().rstrip("/")
        if not left or not right:
            continue
        if src == left or src.startswith(left + "/"):
            suffix = src[len(left) :]
            return right + suffix
    return src


class SandboxMountPolicy:
    @staticmethod
    def workspace_only(*, workspace_host_path: Path, workspace_target: str = "/workspace") -> List[SandboxVolumeMount]:
        """挂载工作区目录到指定沙箱路径（可读写）。"""
        return [
            SandboxVolumeMount(
                source=_translate_source_for_sandbox_host(workspace_host_path),
                target=workspace_target,
                read_only=False,
                mount_type=_DEFAULT_MOUNT_TYPE,
            ),
        ]

    @staticmethod
    def workspace_sessions_root_only(*, workspace_sessions_host_path: Path) -> List[SandboxVolumeMount]:
        """挂载用户 workspaces 根目录到 /workspace（可读写）。"""
        return SandboxMountPolicy.workspace_only(
            workspace_host_path=workspace_sessions_host_path,
            workspace_target="/workspace",
        )

    @staticmethod
    def build_mounts(
        *,
        workspace_host_path: Path,
        skill_scripts_host_path: Path,
        skill_home_host_path: Path | None = None,
        skill_config_host_path: Path | None = None,
        config_writable: bool = False,
        workspace_target: str = "/workspace",
    ) -> List[SandboxVolumeMount]:
        mounts: List[SandboxVolumeMount] = [
            SandboxVolumeMount(
                source=_translate_source_for_sandbox_host(workspace_host_path),
                target=workspace_target,
                read_only=False,
                mount_type=_DEFAULT_MOUNT_TYPE,
            ),
            SandboxVolumeMount(
                source=_translate_source_for_sandbox_host(skill_scripts_host_path),
                target="/skill/scripts",
                read_only=True,
                mount_type=_DEFAULT_MOUNT_TYPE,
            ),
        ]
        if skill_home_host_path is not None:
            mounts.append(
                SandboxVolumeMount(
                    source=_translate_source_for_sandbox_host(skill_home_host_path),
                    target="/skill",
                    read_only=True,
                    mount_type=_DEFAULT_MOUNT_TYPE,
                )
            )
        if skill_config_host_path is not None:
            mounts.append(
                SandboxVolumeMount(
                    source=_translate_source_for_sandbox_host(skill_config_host_path),
                    target="/skill/config",
                    read_only=not bool(config_writable),
                    mount_type=_DEFAULT_MOUNT_TYPE,
                )
            )
        return mounts
