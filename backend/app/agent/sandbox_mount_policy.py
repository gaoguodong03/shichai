"""Mount planning for session workspace and skill assets."""
from __future__ import annotations

import os
from pathlib import Path
from typing import List

from app.agent.sandbox_adapter import SandboxVolumeMount

_DEFAULT_MOUNT_TYPE = os.getenv("SANDBOX_VOLUME_MOUNT_TYPE", "host_path")


class SandboxMountPolicy:
    @staticmethod
    def workspace_only(*, workspace_host_path: Path) -> List[SandboxVolumeMount]:
        """仅挂载当前会话工作区到沙箱内 /workspace（可读写）。"""
        return [
            SandboxVolumeMount(
                source=str(workspace_host_path.resolve()),
                target="/workspace",
                read_only=False,
                mount_type=_DEFAULT_MOUNT_TYPE,
            ),
        ]

    @staticmethod
    def build_mounts(
        *,
        workspace_host_path: Path,
        skill_scripts_host_path: Path,
        skill_config_host_path: Path | None = None,
        config_writable: bool = False,
    ) -> List[SandboxVolumeMount]:
        mounts: List[SandboxVolumeMount] = [
            SandboxVolumeMount(
                source=str(workspace_host_path.resolve()),
                target="/workspace",
                read_only=False,
                mount_type=_DEFAULT_MOUNT_TYPE,
            ),
            SandboxVolumeMount(
                source=str(skill_scripts_host_path.resolve()),
                target="/skill/scripts",
                read_only=True,
                mount_type=_DEFAULT_MOUNT_TYPE,
            ),
        ]
        if skill_config_host_path is not None:
            mounts.append(
                SandboxVolumeMount(
                    source=str(skill_config_host_path.resolve()),
                    target="/skill/config",
                    read_only=not bool(config_writable),
                    mount_type=_DEFAULT_MOUNT_TYPE,
                )
            )
        return mounts
