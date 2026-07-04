"""User requirements handling for sandbox lifecycles."""
from __future__ import annotations

import hashlib
import logging
import time
from typing import Any

from app.agent.sandbox_adapter import SandboxHandle, SandboxPolicy
from app.agent.sandbox_requirements_installer import (
    build_requirements_install_command,
    build_requirements_install_env,
)
from app.agent.sandbox_requirements_runtime import (
    command_exit_code,
    command_output,
    requirements_b64,
    requirements_package_summary,
    tail,
)
from app.agent.sandbox_requirements_verifier import (
    REQUIREMENTS_REAL_VERIFIED_AT_KEY,
)
from app.core.user_context import get_user_context_for

logger = logging.getLogger(__name__)

REQUIREMENTS_VERIFIER_VERSION = "import-v2"


class SandboxRequirementsMixin:
    _adapter: Any
    _requirements_real_verify_ttl_sec: int

    def _requirements_hash_for_user(self, user_id: str) -> str:
        txt = self._read_user_sandbox_requirements(user_id)
        normalized = (txt or "").strip()
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]

    def _requirements_b64_for_user(self, user_id: str) -> str:
        return requirements_b64(self._read_user_sandbox_requirements(user_id))

    def _requirements_real_verify_is_fresh(
        self,
        handle: SandboxHandle,
        *,
        dep_hash: str,
        now: float,
    ) -> bool:
        if self._requirements_real_verify_ttl_sec <= 0:
            return True
        if not isinstance(handle.metadata, dict):
            return False
        if dep_hash and str(handle.metadata.get("verified_requirements_hash") or "").strip() != dep_hash:
            return False
        verified_at_raw = handle.metadata.get(REQUIREMENTS_REAL_VERIFIED_AT_KEY)
        try:
            verified_at = float(verified_at_raw)
        except (TypeError, ValueError):
            return False
        if verified_at <= 0:
            return False
        return (now - verified_at) <= self._requirements_real_verify_ttl_sec

    def _read_user_sandbox_requirements(self, user_id: str) -> str:
        try:
            ctx = get_user_context_for(user_id)
        except Exception as e:
            logger.warning(
                "st49_sandbox_requirements_read_failed code=user_context_error user_id=%s err=%s",
                user_id,
                str(e)[:500],
            )
            return ""
        path = (ctx.settings_dir / "sandbox" / "requirements.txt").resolve()
        try:
            if not path.exists():
                logger.info(
                    "st49_sandbox_requirements_absent code=requirements_file_missing user_id=%s path=%s",
                    user_id,
                    str(path),
                )
                return ""
            content = path.read_text(encoding="utf-8")
            logger.debug(
                "st49_sandbox_requirements_loaded code=requirements_file_loaded user_id=%s path=%s bytes=%s non_comment_lines=%s",
                user_id,
                str(path),
                len(content.encode("utf-8")),
                sum(1 for line in content.splitlines() if line.strip() and not line.strip().startswith("#")),
            )
            return content
        except Exception as e:
            logger.warning(
                "st49_sandbox_requirements_read_failed code=requirements_file_read_error user_id=%s path=%s err=%s",
                user_id,
                str(path),
                str(e)[:500],
            )
            return ""

    async def _maybe_install_user_requirements(
        self,
        handle: SandboxHandle,
        *,
        user_id: str,
        policy: SandboxPolicy,
    ) -> None:
        started_at = time.perf_counter()
        if not isinstance(handle.metadata, dict):
            logger.info("sandbox_requirements_skip reason=metadata_not_dict user_id=%s", user_id)
            return
        normalized = (self._read_user_sandbox_requirements(user_id) or "").strip()
        dep_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
        req_summary = requirements_package_summary(normalized)
        last = str(handle.metadata.get("installed_requirements_hash") or "")
        verified = str(handle.metadata.get("verified_requirements_hash") or "")
        verifier_version = str(handle.metadata.get("requirements_verifier_version") or "")
        logger.info(
            "st49_sandbox_requirements_check code=requirements_check user_id=%s dep_hash=%s installed_hash=%s verified_hash=%s verifier_version=%s required_verifier=%s has_requirements=%s req_bytes=%s package_count=%s package_preview=%s has_playwright=%s has_patchright=%s sandbox_id=%s image_ref=%s variant=%s allow_network=%s timeout_ms=%s",
            user_id,
            dep_hash,
            last,
            verified,
            verifier_version,
            REQUIREMENTS_VERIFIER_VERSION,
            bool(normalized),
            len(normalized.encode("utf-8")),
            req_summary["count"],
            ",".join(req_summary["preview"]),
            req_summary["has_playwright"],
            req_summary["has_patchright"],
            str((handle.metadata or {}).get("sandbox_id") or ""),
            str((handle.metadata or {}).get("image_ref") or ""),
            str((policy.environment or {}).get("SANDBOX_IMAGE_VARIANT") or ""),
            bool(policy.allow_network),
            int(policy.timeout_ms or 0),
        )
        if dep_hash == last and dep_hash == verified and verifier_version == REQUIREMENTS_VERIFIER_VERSION:
            handle.metadata.setdefault(REQUIREMENTS_REAL_VERIFIED_AT_KEY, time.time())
            logger.info(
                "st49_sandbox_requirements_skip code=requirements_hash_verified user_id=%s dep_hash=%s sandbox_id=%s",
                user_id,
                dep_hash,
                str((handle.metadata or {}).get("sandbox_id") or ""),
            )
            return
        if not normalized:
            handle.metadata["installed_requirements_hash"] = dep_hash
            handle.metadata["verified_requirements_hash"] = dep_hash
            handle.metadata["requirements_verifier_version"] = REQUIREMENTS_VERIFIER_VERSION
            handle.metadata[REQUIREMENTS_REAL_VERIFIED_AT_KEY] = time.time()
            logger.info(
                "st49_sandbox_requirements_skip code=requirements_empty user_id=%s dep_hash=%s sandbox_id=%s",
                user_id,
                dep_hash,
                str((handle.metadata or {}).get("sandbox_id") or ""),
            )
            return
        cmd = build_requirements_install_command(normalized)
        env = build_requirements_install_env(normalized, policy.environment)
        will_install_browsers = bool(
            str(env.get("SANDBOX_AUTO_INSTALL_BROWSERS") or "").strip() == "1"
            and (req_summary["has_playwright"] or req_summary["has_patchright"])
        )
        logger.info(
            "st49_sandbox_requirements_install_start code=requirements_install_start user_id=%s dep_hash=%s sandbox_id=%s image_ref=%s variant=%s req_bytes=%s package_count=%s package_preview=%s will_install_browsers=%s timeout_ms=%s",
            user_id,
            dep_hash,
            str((handle.metadata or {}).get("sandbox_id") or ""),
            str((handle.metadata or {}).get("image_ref") or ""),
            str(env.get("SANDBOX_IMAGE_VARIANT") or ""),
            len(normalized.encode("utf-8")),
            req_summary["count"],
            ",".join(req_summary["preview"]),
            will_install_browsers,
            max(120_000, int(policy.timeout_ms or 120_000)),
        )
        try:
            if hasattr(self._adapter, "exec_command"):
                install_result = await self._adapter.exec_command(
                    handle,
                    cmd,
                    cwd="/",
                    timeout_ms=max(120_000, int(policy.timeout_ms or 120_000)),
                    env=env,
                )
                exit_code = command_exit_code(install_result)
                stdout, stderr = command_output(install_result)
                if "requirements_verify_end" not in stdout:
                    logger.warning(
                        "st49_sandbox_requirements_install_failed code=requirements_install_incomplete user_id=%s dep_hash=%s sandbox_id=%s complete=%s stdout_tail=%r stderr_tail=%r",
                        user_id,
                        dep_hash,
                        str((handle.metadata or {}).get("sandbox_id") or ""),
                        install_result.get("complete") if isinstance(install_result, dict) else "",
                        tail(stdout),
                        tail(stderr),
                    )
                    raise RuntimeError(
                        "沙箱 requirements 安装未完成或输出不完整"
                        f"。stdout_tail={tail(stdout)} stderr_tail={tail(stderr)}"
                    )
                if isinstance(exit_code, int) and exit_code != 0:
                    logger.warning(
                        "st49_sandbox_requirements_install_failed code=requirements_install_nonzero user_id=%s dep_hash=%s exit_code=%s sandbox_id=%s stdout_tail=%r stderr_tail=%r",
                        user_id,
                        dep_hash,
                        exit_code,
                        str((handle.metadata or {}).get("sandbox_id") or ""),
                        tail(stdout),
                        tail(stderr),
                    )
                    raise RuntimeError(
                        "沙箱 requirements 安装失败"
                        f"（exit_code={exit_code}）。stdout_tail={tail(stdout)} stderr_tail={tail(stderr)}"
                    )
                handle.metadata["installed_requirements_hash"] = dep_hash
                handle.metadata["verified_requirements_hash"] = dep_hash
                handle.metadata["requirements_verifier_version"] = REQUIREMENTS_VERIFIER_VERSION
                handle.metadata[REQUIREMENTS_REAL_VERIFIED_AT_KEY] = time.time()
                elapsed_ms = int((time.perf_counter() - started_at) * 1000)
                logger.info(
                    "st49_sandbox_requirements_install_done code=requirements_install_done user_id=%s dep_hash=%s elapsed_ms=%s sandbox_id=%s image_ref=%s",
                    user_id,
                    dep_hash,
                    elapsed_ms,
                    str((handle.metadata or {}).get("sandbox_id") or ""),
                    str((handle.metadata or {}).get("image_ref") or ""),
                )
                logger.debug(
                    "st49_sandbox_requirements_install_output code=requirements_install_output user_id=%s dep_hash=%s sandbox_id=%s stdout_tail=%r stderr_tail=%r",
                    user_id,
                    dep_hash,
                    str((handle.metadata or {}).get("sandbox_id") or ""),
                    tail(stdout, 2000),
                    tail(stderr, 2000),
                )
            else:
                logger.warning(
                    "st49_sandbox_requirements_install_skipped code=adapter_no_exec_command user_id=%s dep_hash=%s sandbox_id=%s image_ref=%s",
                    user_id,
                    dep_hash,
                    str((handle.metadata or {}).get("sandbox_id") or ""),
                    str((handle.metadata or {}).get("image_ref") or ""),
                )
        except Exception as e:
            elapsed_ms = int((time.perf_counter() - started_at) * 1000)
            logger.warning(
                "st49_sandbox_requirements_install_failed code=requirements_install_exception user_id=%s dep_hash=%s elapsed_ms=%s sandbox_id=%s image_ref=%s err=%s",
                user_id,
                dep_hash,
                elapsed_ms,
                str((handle.metadata or {}).get("sandbox_id") or ""),
                str((handle.metadata or {}).get("image_ref") or ""),
                str(e),
            )
            raise
