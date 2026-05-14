"""Platform-side sandbox service over OpenSandbox adapter."""
from __future__ import annotations

import asyncio
import base64
import json
import hashlib
import logging
import os
import shlex
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.agent.path_whitelist_guard import ensure_within_root, normalize_rel_path
from app.agent.sandbox_adapter import OpenSandboxAdapter, SandboxAdapter, SandboxHandle, SandboxPolicy
from app.agent.sandbox_audit import append_sandbox_event
from app.agent.sandbox_image_policy import image_for_variant, read_sandbox_variant
from app.agent.sandbox_mount_policy import SANDBOX_WORKSPACE_ROOT, SandboxMountPolicy
from app.agent.session_workspace_policy import host_sessions_root_from_workspace, sandbox_session_dir, sandbox_sessions_root
from app.core.user_context import get_user_context_for, users_data_root

logger = logging.getLogger(__name__)

_REQUIREMENTS_VERIFIER_VERSION = "import-v2"
_REQUIREMENTS_REAL_VERIFIED_AT_KEY = "requirements_real_verified_at"

def _env_truthy(name: str, default: str = "0") -> bool:
    val = (os.getenv(name) or default).strip().lower()
    return val in {"1", "true", "yes", "on", "enabled"}


def _env_csv(name: str) -> List[str]:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return []
    parts = []
    for x in raw.split(","):
        s = x.strip()
        if s:
            parts.append(s)
    # de-dup preserve order
    return list(dict.fromkeys(parts))


def _command_exit_code(result: Any) -> Optional[int]:
    if not isinstance(result, dict):
        return None
    for key in ("exit_code", "returncode", "return_code", "code"):
        value = result.get(key)
        if isinstance(value, int):
            return value
    ok = result.get("ok")
    if ok is False:
        return 1
    return None


def _command_output(result: Any) -> tuple[str, str]:
    if not isinstance(result, dict):
        return "", ""
    return str(result.get("stdout") or ""), str(result.get("stderr") or "")


def _tail(text: str, limit: int = 4000) -> str:
    value = str(text or "")
    return value[-limit:] if len(value) > limit else value


def _sandbox_default_environment() -> Dict[str, str]:
    """默认注入到沙箱的运行环境。"""
    browsers_path = (os.getenv("PLAYWRIGHT_BROWSERS_PATH") or "/ms-playwright").strip()
    env: Dict[str, str] = {}
    if browsers_path:
        env["PLAYWRIGHT_BROWSERS_PATH"] = browsers_path
    return env


def _requirements_b64(content: str) -> str:
    normalized = (content or "").strip()
    if not normalized:
        return ""
    return base64.b64encode(normalized.encode("utf-8")).decode("ascii")


def _env_float(name: str) -> Optional[float]:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        logger.warning("sandbox_env_invalid_float name=%s value=%s", name, raw)
        return None
    if value <= 0:
        logger.warning("sandbox_env_non_positive_float name=%s value=%s", name, raw)
        return None
    return value


def _env_int(name: str) -> Optional[int]:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        logger.warning("sandbox_env_invalid_int name=%s value=%s", name, raw)
        return None
    if value <= 0:
        logger.warning("sandbox_env_non_positive_int name=%s value=%s", name, raw)
        return None
    return value

def _network_allowed_for_tool(tool_name: str) -> bool:
    """
    Decide whether sandbox may access network for a given tool.

    - SANDBOX_ALLOW_NETWORK=1 and SANDBOX_NETWORK_TOOL_ALLOWLIST empty => allow for all tools (legacy behavior)
    - SANDBOX_NETWORK_TOOL_ALLOWLIST non-empty => only allow if tool_name in allowlist (or '*')
    - 配置里常写 run_skill_script，实际工具名为 run_skill_script_<skill_id>，二者等价放行
    - SANDBOX_ALLOW_NETWORK=0 => deny unless allowlist is explicitly configured (opt-in)
    """
    name = (tool_name or "").strip()
    allowlist = _env_csv("SANDBOX_NETWORK_TOOL_ALLOWLIST")
    allow_global = _env_truthy("SANDBOX_ALLOW_NETWORK", default="0")
    if allowlist:
        if "*" in allowlist:
            return True
        if name in allowlist:
            return True
        if name.startswith("run_skill_script_") and "run_skill_script" in allowlist:
            return True
        return False
    return bool(allow_global)


@dataclass
class SandboxExecutionRequest:
    user_id: str
    session_id: str
    turn_id: str
    tool_call_id: str
    tool_name: str
    tool_kind: str
    payload: Dict[str, Any]
    timeout_ms: int
    runner: Any
    workspace_path: Path
    skill_home: Optional[Path] = None
    skill_scripts_path: Optional[Path] = None
    skill_config_path: Optional[Path] = None
    runtime_backend: str = "docker"
    runtime_profile: str = "standard"
    policy: Optional[SandboxPolicy] = None
    cwd: str = ""


def policy_mount_fingerprint(policy: SandboxPolicy) -> str:
    parts = [policy.fs_root or ""]
    for m in sorted(policy.volume_mounts or [], key=lambda x: (x.target, x.source)):
        parts.append(f"{m.source}|{m.target}|{int(m.read_only)}|{m.mount_type}")
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:16]


def handle_cache_key(user_id: str, session_id: str = "") -> str:
    uid = (user_id or "").strip() or "anonymous"
    sid = (session_id or "").strip()
    return f"{uid}:{sid}" if sid else uid


def to_workspace_inner_path(rel: str) -> str:
    r = (rel or "").strip().lstrip("/").replace("..", "")
    return f"/workspace/{r}" if r else "/workspace"


def _sandbox_image_for_user(user_id: str) -> tuple[str, str]:
    uid = (user_id or "").strip()
    if uid:
        try:
            variant = read_sandbox_variant(get_user_context_for(uid).config_dir / "sandbox")
        except Exception:
            variant = "standard"
    else:
        variant = "standard"
    return variant, image_for_variant(variant)


class SandboxService:
    """Manage user sandbox lifecycle and OpenSandbox request mapping."""

    def __init__(
        self,
        sandbox_adapter: Optional[SandboxAdapter] = None,
        session_ttl_sec: int = 1800,
    ):
        self._adapter = sandbox_adapter or OpenSandboxAdapter()
        logger.info("sandbox_backend_selected backend=%s", self._describe_adapter(self._adapter))
        self._session_ttl_sec = max(60, int(session_ttl_sec))
        self._always_on = _env_truthy("SANDBOX_ALWAYS_ON", default="0")
        # 默认启用：仅在首次创建或 requirements 变更时重建用户级沙箱。
        self._restart_only_on_requirements_update = _env_truthy(
            "SANDBOX_RESTART_ONLY_ON_REQUIREMENTS_UPDATE", default="1"
        )
        try:
            self._requirements_real_verify_ttl_sec = max(
                0,
                int(os.getenv("SANDBOX_REQUIREMENTS_REAL_VERIFY_TTL_SEC", "300") or "300"),
            )
        except ValueError:
            logger.warning(
                "sandbox_env_invalid_int name=%s value=%s",
                "SANDBOX_REQUIREMENTS_REAL_VERIFY_TTL_SEC",
                os.getenv("SANDBOX_REQUIREMENTS_REAL_VERIFY_TTL_SEC"),
            )
            self._requirements_real_verify_ttl_sec = 300
        self._fixed_cpu = _env_float("SANDBOX_FIXED_CPU")
        self._fixed_memory_mb = _env_int("SANDBOX_FIXED_MEMORY_MB")
        self._lock = asyncio.Lock()
        self._user_handles: Dict[str, Tuple[SandboxHandle, float]] = {}
        self._user_ensure_locks: Dict[str, asyncio.Lock] = {}

    async def _ensure_lock_for_key(self, key: str) -> asyncio.Lock:
        async with self._lock:
            lock = self._user_ensure_locks.get(key)
            if lock is None:
                lock = asyncio.Lock()
                self._user_ensure_locks[key] = lock
            return lock

    @staticmethod
    def _describe_adapter(adapter: SandboxAdapter) -> str:
        if isinstance(adapter, OpenSandboxAdapter):
            return "opensandbox"
        return adapter.__class__.__name__

    def backend_label(self) -> str:
        return self._describe_adapter(self._adapter)

    @staticmethod
    def _is_sandbox_not_found_error(exc: Exception) -> bool:
        msg = str(exc).lower()
        if "sandbox" not in msg:
            return False
        return ("not found" in msg) or ("no such" in msg) or ("invalid sandbox" in msg)

    def _apply_fixed_resource_policy(self, policy: SandboxPolicy) -> SandboxPolicy:
        updates: Dict[str, Any] = {}
        if self._fixed_cpu is not None and float(policy.cpu_limit) != float(self._fixed_cpu):
            updates["cpu_limit"] = self._fixed_cpu
        if self._fixed_memory_mb is not None and int(policy.memory_limit_mb) != int(self._fixed_memory_mb):
            updates["memory_limit_mb"] = self._fixed_memory_mb
        default_env = _sandbox_default_environment()
        merged_env = {**default_env, **dict(policy.environment or {})}
        if merged_env != dict(policy.environment or {}):
            updates["environment"] = merged_env
        if updates:
            return replace(policy, **updates)
        return policy

    def _apply_user_image_policy(self, policy: SandboxPolicy, user_id: str) -> SandboxPolicy:
        variant, image_ref = _sandbox_image_for_user(user_id)
        if policy.image_ref == image_ref:
            return policy
        env = {**dict(policy.environment or {}), "SANDBOX_IMAGE_VARIANT": variant}
        return replace(policy, image_ref=image_ref, environment=env)

    def _build_mounts_for_request(
        self, req: SandboxExecutionRequest
    ) -> tuple[Path, Optional[Path], list]:
        host_sessions_root = host_sessions_root_from_workspace(req.workspace_path)
        skills_root: Optional[Path] = None
        uid = (req.user_id or "").strip()
        if uid:
            try:
                skills_root = get_user_context_for(uid).skills_dir.resolve()
            except Exception:
                skills_root = None
        if skills_root is not None:
            mounts = SandboxMountPolicy.workspace_with_all_skills(
                workspace_sessions_host_path=host_sessions_root,
                skills_root_host_path=skills_root,
                workspace_target=sandbox_sessions_root(),
            )
        else:
            mounts = SandboxMountPolicy.workspace_sessions_root_only(
                workspace_sessions_host_path=host_sessions_root
            )
        return host_sessions_root, skills_root, mounts

    @staticmethod
    def _resolve_cwd(policy: SandboxPolicy, req: SandboxExecutionRequest) -> str:
        desired = (req.cwd or "").strip() or sandbox_session_dir(req.session_id)
        targets = {str(m.target or "").strip() for m in (policy.volume_mounts or []) if str(m.target or "").strip()}
        if desired == "/":
            return desired
        if desired.startswith("/workspace"):
            if "/workspace" in targets:
                return desired
            return "/"
        return desired

    def _workspace_only_policy(self, sessions_root_path: Path, *, timeout_ms: int = 60_000) -> SandboxPolicy:
        mounts = SandboxMountPolicy.workspace_sessions_root_only(workspace_sessions_host_path=sessions_root_path)
        return SandboxPolicy(
            fs_root=str(sessions_root_path.resolve()),
            workspace_host_path=str(sessions_root_path.resolve()),
            volume_mounts=mounts,
            timeout_ms=max(1000, int(timeout_ms)),
            tool_allowlist=[],
            runtime_backend=os.getenv("SANDBOX_RUNTIME_BACKEND", "docker"),
            runtime_profile=os.getenv("SANDBOX_RUNTIME_PROFILE", "standard"),
            allow_network=False,
            allowed_hosts=_env_csv("SANDBOX_ALLOWED_HOSTS"),
        )

    def _workspace_with_skills_policy(
        self,
        sessions_root_path: Path,
        *,
        skills_root_path: Path,
        timeout_ms: int = 60_000,
    ) -> SandboxPolicy:
        mounts = SandboxMountPolicy.workspace_with_all_skills(
            workspace_sessions_host_path=sessions_root_path,
            skills_root_host_path=skills_root_path,
            workspace_target=SANDBOX_WORKSPACE_ROOT,
        )
        return SandboxPolicy(
            fs_root=str(sessions_root_path.resolve()),
            workspace_host_path=str(sessions_root_path.resolve()),
            skill_scripts_host_path=str(skills_root_path.resolve()),
            timeout_ms=max(1000, int(timeout_ms)),
            tool_allowlist=[],
            runtime_backend=os.getenv("SANDBOX_RUNTIME_BACKEND", "docker"),
            runtime_profile=os.getenv("SANDBOX_RUNTIME_PROFILE", "standard"),
            allow_network=False,
            allowed_hosts=_env_csv("SANDBOX_ALLOWED_HOSTS"),
            volume_mounts=mounts,
        )

    @staticmethod
    def _cached_handle_still_valid(handle: SandboxHandle, policy: SandboxPolicy, tool_name: str) -> bool:
        """
        单用户沙箱会复用同一 OpenSandbox 会话。创建时写入的 policy.tool_allowlist 与挂载指纹若与当前请求不一致，
        必须丢弃缓存，否则会误拦后续工具（例如先跑 A 技能再跑 sandbox-dep-check）。
        """
        meta = handle.metadata if isinstance(handle.metadata, dict) else {}
        old_fp = str(meta.get("mount_fingerprint") or "").strip()
        new_fp = policy_mount_fingerprint(policy)
        if not old_fp or old_fp != new_fp:
            return False
        old_image_ref = str(meta.get("image_ref") or "").strip()
        new_image_ref = str(policy.image_ref or "").strip()
        if old_image_ref != new_image_ref:
            return False
        old_policy = meta.get("policy")
        old_allow: list[str] = []
        if isinstance(old_policy, dict):
            old_allow = list(old_policy.get("tool_allowlist") or [])
        tn = (tool_name or "").strip()
        if old_allow and tn and tn not in old_allow:
            return False
        stored_net = meta.get("policy_allow_network")
        if stored_net is not None and bool(stored_net) != bool(policy.allow_network):
            return False
        return True

    def _requirements_hash_for_user(self, user_id: str) -> str:
        txt = self._read_user_sandbox_requirements(user_id)
        normalized = (txt or "").strip()
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]

    def _requirements_b64_for_user(self, user_id: str) -> str:
        return _requirements_b64(self._read_user_sandbox_requirements(user_id))

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
        verified_at_raw = handle.metadata.get(_REQUIREMENTS_REAL_VERIFIED_AT_KEY)
        try:
            verified_at = float(verified_at_raw)
        except (TypeError, ValueError):
            return False
        if verified_at <= 0:
            return False
        return (now - verified_at) <= self._requirements_real_verify_ttl_sec

    async def _verify_installed_user_requirements(
        self,
        handle: SandboxHandle,
        *,
        user_id: str,
        policy: SandboxPolicy,
    ) -> bool:
        """Verify installed Python packages match the user's requirements metadata."""
        normalized = (self._read_user_sandbox_requirements(user_id) or "").strip()
        dep_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
        if not normalized:
            return True
        if not hasattr(self._adapter, "exec_command"):
            logger.warning(
                "st49_sandbox_requirements_verify_failed code=adapter_no_exec_command user_id=%s dep_hash=%s sandbox_id=%s",
                user_id,
                dep_hash,
                str((handle.metadata or {}).get("sandbox_id") or ""),
            )
            return False
        quoted_requirements = shlex.quote(normalized)
        cmd = [
            "sh",
            "-lc",
            (
                f"set -e; SANDBOX_REQUIREMENTS_TEXT={quoted_requirements}; export SANDBOX_REQUIREMENTS_TEXT; "
                "python3 - <<'PY'\n"
                "import importlib, importlib.metadata as md, os, re, sys\n"
                "from packaging.version import Version\n"
                "raw=os.environ.get('SANDBOX_REQUIREMENTS_TEXT','')\n"
                "if not raw.strip():\n"
                "    raise SystemExit('requirements verify received empty requirements text')\n"
                "print('requirements_verify_start')\n"
                "import_names={'xlrd':['xlrd'], 'openpyxl':['openpyxl'], 'pandas':['pandas']}\n"
                "min_versions={'xlrd':'2.0.1'}\n"
                "missing=[]\n"
                "version_too_low=[]\n"
                "import_missing=[]\n"
                "seen=[]\n"
                "for raw_line in raw.splitlines():\n"
                "    line=raw_line.strip()\n"
                "    if not line or line.startswith('#') or line.startswith(('-', '--')) or '://' in line or line.startswith(('git+', 'http:')):\n"
                "        continue\n"
                "    name=line.split(';',1)[0].split('[',1)[0].strip()\n"
                "    name=re.split(r'===|==|>=|<=|~=|!=|>|<', name, 1)[0].strip()\n"
                "    if not name:\n"
                "        continue\n"
                "    try:\n"
                "        version=md.version(name)\n"
                "        seen.append(f'{name}=={version}')\n"
                "        minimum=min_versions.get(name.lower())\n"
                "        if minimum and Version(version) < Version(minimum):\n"
                "            version_too_low.append(f'{name}=={version} < {minimum}')\n"
                "        for mod in import_names.get(name.lower(), []):\n"
                "            try:\n"
                "                importlib.import_module(mod)\n"
                "                print(f'import_ok:{mod}')\n"
                "            except Exception as exc:\n"
                "                import_missing.append(f'{mod}: {exc}')\n"
                "    except md.PackageNotFoundError:\n"
                "        missing.append(name)\n"
                "for item in seen:\n"
                "    print(item)\n"
                "print('requirements_verify_end')\n"
                "if missing:\n"
                "    raise SystemExit('missing packages after metadata hit: ' + ', '.join(missing))\n"
                "if version_too_low:\n"
                "    raise SystemExit('packages installed but version too low: ' + '; '.join(version_too_low))\n"
                "if import_missing:\n"
                "    raise SystemExit('packages installed but import failed: ' + '; '.join(import_missing))\n"
                "PY"
            ),
        ]
        try:
            verify_result = await self._adapter.exec_command(  # type: ignore[attr-defined]
                handle,
                cmd,
                cwd="/",
                timeout_ms=min(max(30_000, int(policy.timeout_ms or 120_000)), 120_000),
                env={**_sandbox_default_environment(), "SANDBOX_REQUIREMENTS_TEXT": normalized},
            )
            exit_code = _command_exit_code(verify_result)
            stdout, stderr = _command_output(verify_result)
            if isinstance(exit_code, int) and exit_code == 0:
                if isinstance(handle.metadata, dict):
                    handle.metadata[_REQUIREMENTS_REAL_VERIFIED_AT_KEY] = time.time()
                logger.info(
                    "st49_sandbox_requirements_verify_done code=requirements_real_verify_done user_id=%s dep_hash=%s sandbox_id=%s stdout_tail=%r stderr_tail=%r",
                    user_id,
                    dep_hash,
                    str((handle.metadata or {}).get("sandbox_id") or ""),
                    _tail(stdout, 2000),
                    _tail(stderr, 2000),
                )
                return True
            logger.warning(
                "st49_sandbox_requirements_verify_failed code=requirements_real_verify_nonzero user_id=%s dep_hash=%s exit_code=%s sandbox_id=%s stdout_tail=%r stderr_tail=%r",
                user_id,
                dep_hash,
                exit_code,
                str((handle.metadata or {}).get("sandbox_id") or ""),
                _tail(stdout),
                _tail(stderr),
            )
            return False
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "st49_sandbox_requirements_verify_failed code=requirements_real_verify_exception user_id=%s dep_hash=%s sandbox_id=%s err=%s",
                user_id,
                dep_hash,
                str((handle.metadata or {}).get("sandbox_id") or ""),
                str(e)[:500],
            )
            return False

    def _prepare_command_env(self, req: SandboxExecutionRequest, raw_env: Any) -> Dict[str, str]:
        env: Dict[str, str] = {}
        if isinstance(raw_env, dict):
            env.update({str(k): str(v) for k, v in raw_env.items() if v is not None})
        user_id = (req.user_id or "").strip() or f"session:{req.session_id}"
        req_b64 = self._requirements_b64_for_user(user_id)
        current_b64 = (env.get("SKILL_REQUIREMENTS_B64") or "").strip()
        if req_b64 and not current_b64:
            env["SKILL_REQUIREMENTS_B64"] = req_b64
            logger.debug(
                "st49_sandbox_command_env_injected code=requirements_env_injected user_id=%s session_id=%s tool_name=%s requirements_hash=%s",
                user_id,
                req.session_id,
                req.tool_name,
                self._requirements_hash_for_user(user_id),
            )
        elif req_b64 and current_b64:
            logger.debug(
                "st49_sandbox_command_env_present code=requirements_env_present user_id=%s session_id=%s tool_name=%s requirements_hash=%s",
                user_id,
                req.session_id,
                req.tool_name,
                self._requirements_hash_for_user(user_id),
            )
        else:
            logger.debug(
                "st49_sandbox_command_env_empty code=requirements_env_empty user_id=%s session_id=%s tool_name=%s requirements_hash=%s",
                user_id,
                req.session_id,
                req.tool_name,
                self._requirements_hash_for_user(user_id),
            )
        return env

    def requirements_hash_for_user(self, user_id: str) -> str:
        """Public diagnostic wrapper for the current user's sandbox requirements hash."""
        return self._requirements_hash_for_user(user_id)

    @staticmethod
    def _installed_requirements_hash(handle: SandboxHandle) -> str:
        if not isinstance(handle.metadata, dict):
            return ""
        return str(handle.metadata.get("installed_requirements_hash") or "").strip()

    async def _build_policy(self, req: SandboxExecutionRequest) -> SandboxPolicy:
        if req.policy is not None:
            env_net = _network_allowed_for_tool(req.tool_name)
            final_net = bool(env_net or req.policy.allow_network)
            policy = req.policy
            if final_net != bool(req.policy.allow_network):
                policy = replace(req.policy, allow_network=final_net)
            host_sessions_root, skills_root, mounts = self._build_mounts_for_request(req)
            updates: Dict[str, Any] = {}
            # 用户级单沙箱复用模式：不按工具名做 allowlist 限制，避免跨工具调用被旧策略误拦截。
            if list(policy.tool_allowlist or []):
                updates["tool_allowlist"] = []
            if not list(policy.volume_mounts or []):
                updates["fs_root"] = str(host_sessions_root.resolve())
                updates["volume_mounts"] = mounts
            if not (policy.workspace_host_path or "").strip():
                updates["workspace_host_path"] = str(host_sessions_root.resolve())
            if skills_root is not None and not (policy.skill_scripts_host_path or "").strip():
                updates["skill_scripts_host_path"] = str(skills_root.resolve())
            if updates:
                policy = replace(policy, **updates)
            return self._apply_user_image_policy(self._apply_fixed_resource_policy(policy), req.user_id)
        host_sessions_root, skills_root, mounts = self._build_mounts_for_request(req)
        return self._apply_user_image_policy(self._apply_fixed_resource_policy(SandboxPolicy(
            fs_root=str(host_sessions_root.resolve()),
            workspace_host_path=str(host_sessions_root.resolve()),
            skill_scripts_host_path=str(skills_root) if skills_root else "",
            skill_config_host_path="",
            runtime_backend=req.runtime_backend,
            runtime_profile=req.runtime_profile,
            timeout_ms=max(1000, int(req.timeout_ms)),
            # 全量挂载模式下，用户级沙箱在同一挂载策略下复用，不按工具名触发重建。
            tool_allowlist=[],
            volume_mounts=mounts,
            allow_network=_network_allowed_for_tool(req.tool_name),
            allowed_hosts=_env_csv("SANDBOX_ALLOWED_HOSTS"),
        )), req.user_id)

    async def _ensure_user_handle(self, req: SandboxExecutionRequest, policy: SandboxPolicy) -> SandboxHandle:
        user_id = (req.user_id or "").strip() or f"session:{req.session_id}"
        key = handle_cache_key(user_id, req.session_id)
        user_lock = await self._ensure_lock_for_key(key)
        async with user_lock:
            return await self._ensure_user_handle_locked(req, policy, user_id=user_id, key=key)

    async def _ensure_user_handle_locked(
        self,
        req: SandboxExecutionRequest,
        policy: SandboxPolicy,
        *,
        user_id: str,
        key: str,
    ) -> SandboxHandle:
        now = time.time()
        ensure_started_at = time.perf_counter()
        logical_sid = key
        async with self._lock:
            existing = self._user_handles.get(key)
            if existing is not None:
                handle, touched = existing
                if self._restart_only_on_requirements_update:
                    current_req_hash = self._requirements_hash_for_user(user_id)
                    installed_req_hash = self._installed_requirements_hash(handle)
                    verified_req_hash = str((handle.metadata or {}).get("verified_requirements_hash") or "").strip()
                    verifier_version = str((handle.metadata or {}).get("requirements_verifier_version") or "").strip()
                    old_mount_fp = str((handle.metadata or {}).get("mount_fingerprint") or "").strip()
                    new_mount_fp = policy_mount_fingerprint(policy)
                    old_image_ref = str((handle.metadata or {}).get("image_ref") or "").strip()
                    new_image_ref = str(policy.image_ref or "").strip()
                    stored_net = (handle.metadata or {}).get("policy_allow_network")
                    network_policy_matches = stored_net is None or bool(stored_net) == bool(policy.allow_network)
                    if (
                        current_req_hash == installed_req_hash
                        and current_req_hash == verified_req_hash
                        and verifier_version == _REQUIREMENTS_VERIFIER_VERSION
                        and old_image_ref == new_image_ref
                        and old_mount_fp == new_mount_fp
                        and network_policy_matches
                    ):
                        self._user_handles[key] = (handle, now)
                        if self._requirements_real_verify_is_fresh(handle, dep_hash=current_req_hash, now=now):
                            logger.info(
                                "st49_sandbox_requirements_skip code=requirements_real_verify_ttl_hit user_id=%s session_id=%s dep_hash=%s sandbox_id=%s ttl_sec=%s",
                                user_id,
                                req.session_id,
                                current_req_hash,
                                str((handle.metadata or {}).get("sandbox_id") or ""),
                                self._requirements_real_verify_ttl_sec,
                            )
                            return handle
                        real_verified = await self._verify_installed_user_requirements(
                            handle,
                            user_id=user_id,
                            policy=policy,
                        )
                        if real_verified:
                            return handle
                        if isinstance(handle.metadata, dict):
                            handle.metadata.pop("installed_requirements_hash", None)
                            handle.metadata.pop("verified_requirements_hash", None)
                            handle.metadata.pop("requirements_verifier_version", None)
                            handle.metadata.pop(_REQUIREMENTS_REAL_VERIFIED_AT_KEY, None)
                        logger.info(
                            "st49_sandbox_reinstall code=user_requirements_real_verify_failed user_id=%s session_id=%s dep_hash=%s sandbox_id=%s",
                            user_id,
                            req.session_id,
                            current_req_hash,
                            str((handle.metadata or {}).get("sandbox_id") or ""),
                        )
                        await self._maybe_install_user_requirements(handle, user_id=user_id, policy=policy)
                        self._user_handles[key] = (handle, now)
                        return handle
                    if old_image_ref != new_image_ref:
                        logger.info(
                            "st49_sandbox_recreate code=user_image_updated user_id=%s session_id=%s old_image=%s new_image=%s",
                            user_id,
                            req.session_id,
                            old_image_ref,
                            new_image_ref,
                        )
                    elif old_mount_fp != new_mount_fp:
                        logger.info(
                            "st49_sandbox_recreate code=user_mount_policy_updated user_id=%s session_id=%s old_mount_fp=%s new_mount_fp=%s",
                            user_id,
                            req.session_id,
                            old_mount_fp,
                            new_mount_fp,
                        )
                    elif not network_policy_matches:
                        logger.info(
                            "st49_sandbox_recreate code=user_network_policy_updated user_id=%s session_id=%s old_allow_network=%s new_allow_network=%s",
                            user_id,
                            req.session_id,
                            bool(stored_net),
                            bool(policy.allow_network),
                        )
                    else:
                        logger.info(
                            "st49_sandbox_recreate code=user_requirements_updated user_id=%s session_id=%s old_hash=%s new_hash=%s",
                            user_id,
                            req.session_id,
                            installed_req_hash,
                            current_req_hash,
                        )
                else:
                    ttl_ok = self._always_on or (now - touched <= self._session_ttl_sec)
                    if ttl_ok and self._cached_handle_still_valid(
                        handle, policy, req.tool_name
                    ):
                        self._user_handles[key] = (handle, now)
                        await self._maybe_install_user_requirements(handle, user_id=user_id, policy=policy)
                        return handle
                try:
                    await self._adapter.dispose_sandbox(handle)
                except Exception as e:  # noqa: BLE001
                    if not self._is_sandbox_not_found_error(e):
                        logger.warning("sandbox_dispose_stale_failed user_id=%s err=%s", user_id, e)
                self._user_handles.pop(key, None)

            handle = await self._adapter.create_session_sandbox(logical_sid, policy)
            if isinstance(handle.metadata, dict):
                handle.metadata["mount_fingerprint"] = policy_mount_fingerprint(policy)
                handle.metadata["policy_allow_network"] = bool(policy.allow_network)
                handle.metadata["image_ref"] = policy.image_ref
                handle.metadata["user_id"] = user_id
                handle.metadata["app_session_id"] = req.session_id
            self._user_handles[key] = (handle, now)
        # 出锁后做安装：避免长时间持锁阻塞其他请求
        await self._maybe_install_user_requirements(handle, user_id=user_id, policy=policy)
        ensure_elapsed_ms = int((time.perf_counter() - ensure_started_at) * 1000)
        async with self._lock:
            logger.info(
                "st49_sandbox_user_bound code=user_sandbox_bound user_id=%s session_id=%s cache_key=%s mount_fp=%s backend=%s sandbox_id=%s image_ref=%s elapsed_ms=%s",
                user_id,
                req.session_id,
                key,
                policy_mount_fingerprint(policy),
                self._describe_adapter(self._adapter),
                handle.metadata.get("sandbox_id", ""),
                str((handle.metadata or {}).get("image_ref") or ""),
                ensure_elapsed_ms,
            )
            append_sandbox_event(
                session_id=req.session_id,
                event_type="sandbox_session_created",
                turn_id=req.turn_id,
                payload={
                    "user_id": user_id,
                    "tool_call_id": req.tool_call_id,
                    "sandbox_id": handle.metadata.get("sandbox_id", ""),
                    "sandbox_mode": "user_session_sandbox",
                    "mount_fingerprint": policy_mount_fingerprint(policy),
                    "runtime": handle.runtime,
                    "runtime_backend": policy.runtime_backend,
                    "runtime_profile": policy.runtime_profile,
                    "image_ref": policy.image_ref,
                    "mount_count": len(policy.volume_mounts or []),
                    "workspace_root_in_sandbox": SANDBOX_WORKSPACE_ROOT,
                    "resource_limit": {
                        "cpu": policy.cpu_limit,
                        "memory_mb": policy.memory_limit_mb,
                    },
                },
            )
            mounts_payload = [
                {"source": m.source, "target": m.target, "read_only": m.read_only, "type": m.mount_type}
                for m in (policy.volume_mounts or [])
            ]
            append_sandbox_event(
                session_id=req.session_id,
                event_type="sandbox_mount_applied",
                turn_id=req.turn_id,
                payload={
                    "user_id": user_id,
                    "sandbox_mode": "user_session_sandbox",
                    "mount_fingerprint": policy_mount_fingerprint(policy),
                    "mounts": mounts_payload,
                    "mount_targets": [str(m.get("target") or "") for m in mounts_payload],
                    "mounts_empty": len(mounts_payload) == 0,
                },
            )
            return handle

    async def _invalidate_user_handle(self, user_id: str, *, expected_handle: Optional[SandboxHandle] = None) -> None:
        target: Optional[SandboxHandle] = None
        async with self._lock:
            target_key = ""
            if expected_handle is not None:
                for k, (handle, _touched) in self._user_handles.items():
                    if handle is expected_handle:
                        target_key = k
                        target = handle
                        break
            else:
                key_prefix = handle_cache_key(user_id)
                existing = self._user_handles.get(key_prefix)
                if existing is not None:
                    target_key = key_prefix
                    target = existing[0]
            if not target_key or target is None:
                return
            self._user_handles.pop(target_key, None)
        if target is None:
            return
        try:
            await self._adapter.dispose_sandbox(target)
        except Exception as e:  # noqa: BLE001
            if not self._is_sandbox_not_found_error(e):
                logger.warning("sandbox_invalidate_dispose_failed user_id=%s err=%s", user_id, e)

    def _read_user_sandbox_requirements(self, user_id: str) -> str:
        """读取当前用户的沙箱 requirements.txt 内容（允许为空）。"""
        try:
            ctx = get_user_context_for(user_id)
        except Exception as e:
            logger.warning(
                "st49_sandbox_requirements_read_failed code=user_context_error user_id=%s err=%s",
                user_id,
                str(e)[:500],
            )
            return ""
        path = (ctx.config_dir / "sandbox" / "requirements.txt").resolve()
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
        """按内容 hash 在沙箱内安装 requirements（变更时才执行一次）。仅用户级 config/sandbox/requirements.txt。"""
        started_at = time.perf_counter()
        if not isinstance(handle.metadata, dict):
            logger.info("sandbox_requirements_skip reason=metadata_not_dict user_id=%s", user_id)
            return
        user_txt = self._read_user_sandbox_requirements(user_id)
        normalized = (user_txt or "").strip()
        dep_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
        last = str(handle.metadata.get("installed_requirements_hash") or "")
        verified = str(handle.metadata.get("verified_requirements_hash") or "")
        verifier_version = str(handle.metadata.get("requirements_verifier_version") or "")
        logger.debug(
            "st49_sandbox_requirements_check code=requirements_check user_id=%s dep_hash=%s installed_hash=%s verified_hash=%s verifier_version=%s required_verifier=%s has_requirements=%s req_bytes=%s sandbox_id=%s image_ref=%s allow_network=%s timeout_ms=%s",
            user_id,
            dep_hash,
            last,
            verified,
            verifier_version,
            _REQUIREMENTS_VERIFIER_VERSION,
            bool(normalized),
            len(normalized.encode("utf-8")),
            str((handle.metadata or {}).get("sandbox_id") or ""),
            str((handle.metadata or {}).get("image_ref") or ""),
            bool(policy.allow_network),
            int(policy.timeout_ms or 0),
        )
        if dep_hash == last and dep_hash == verified and verifier_version == _REQUIREMENTS_VERIFIER_VERSION:
            handle.metadata.setdefault(_REQUIREMENTS_REAL_VERIFIED_AT_KEY, time.time())
            logger.info(
                "st49_sandbox_requirements_skip code=requirements_hash_verified user_id=%s dep_hash=%s sandbox_id=%s",
                user_id,
                dep_hash,
                str((handle.metadata or {}).get("sandbox_id") or ""),
            )
            return
        # 空清单：只更新 hash，不执行 pip
        if not normalized:
            handle.metadata["installed_requirements_hash"] = dep_hash
            handle.metadata["verified_requirements_hash"] = dep_hash
            handle.metadata["requirements_verifier_version"] = _REQUIREMENTS_VERIFIER_VERSION
            handle.metadata[_REQUIREMENTS_REAL_VERIFIED_AT_KEY] = time.time()
            logger.info(
                "st49_sandbox_requirements_skip code=requirements_empty user_id=%s dep_hash=%s sandbox_id=%s",
                user_id,
                dep_hash,
                str((handle.metadata or {}).get("sandbox_id") or ""),
            )
            return
        # 若禁网，很可能装不成；仍尝试一次并把错误抛出（方便测试验证）。
        b64 = base64.b64encode(normalized.encode("utf-8")).decode("ascii")
        quoted_b64 = shlex.quote(b64)
        cmd = [
            "sh",
            "-lc",
            (
                f"set -eux; SANDBOX_REQUIREMENTS_B64={quoted_b64}; export SANDBOX_REQUIREMENTS_B64; "
                "echo '=== sandbox requirements diagnostics ==='; "
                "echo python3_path=$(command -v python3 || true); "
                "python3 -V; "
                "python3 -m pip --version; "
                'REQ_B64="${SANDBOX_REQUIREMENTS_B64:-}"; '
                'python3 - <<\'PY\'\n'
                "import base64,os,sys\n"
                "b=os.environ.get('SANDBOX_REQUIREMENTS_B64','')\n"
                "data=base64.b64decode(b.encode('ascii')) if b else b''\n"
                "open('/tmp/requirements.txt','wb').write(data)\n"
                "print('wrote_requirements_bytes', len(data))\n"
                "if not data.strip():\n"
                "    raise SystemExit('requirements install received empty requirements payload')\n"
                "print('requirements_preview_start')\n"
                "for line in data.decode('utf-8', 'replace').splitlines():\n"
                "    text=line.strip()\n"
                "    if text and not text.startswith('#'):\n"
                "        print(text)\n"
                "print('requirements_preview_end')\n"
                "PY\n"
                "python3 -m pip install --disable-pip-version-check --no-input --upgrade -r /tmp/requirements.txt\n"
                "python3 - <<'PY'\n"
                "import importlib, importlib.metadata as md\n"
                "from packaging.version import Version\n"
                "print('requirements_verify_start')\n"
                "missing=[]\n"
                "import_missing=[]\n"
                "version_too_low=[]\n"
                "seen=[]\n"
                "import_names={'xlrd':['xlrd'], 'openpyxl':['openpyxl'], 'pandas':['pandas']}\n"
                "min_versions={'xlrd':'2.0.1'}\n"
                "for raw in open('/tmp/requirements.txt', encoding='utf-8'):\n"
                "    line=raw.strip()\n"
                "    if not line or line.startswith('#') or line.startswith(('-', '--')) or '://' in line or line.startswith(('git+', 'http:')):\n"
                "        continue\n"
                "    name=line.split(';',1)[0].split('[',1)[0].strip()\n"
                "    for sep in ('===','==','>=','<=','~=','!=','>','<'):\n"
                "        name=name.split(sep,1)[0].strip()\n"
                "    if not name:\n"
                "        continue\n"
                "    try:\n"
                "        version=md.version(name)\n"
                "        seen.append(f'{name}=={version}')\n"
                "        minimum=min_versions.get(name.lower())\n"
                "        if minimum and Version(version) < Version(minimum):\n"
                "            version_too_low.append(f'{name}=={version} < {minimum}')\n"
                "        for mod in import_names.get(name.lower(), []):\n"
                "            try:\n"
                "                importlib.import_module(mod)\n"
                "                print(f'import_ok:{mod}')\n"
                "            except Exception as exc:\n"
                "                import_missing.append(f'{mod}: {exc}')\n"
                "    except md.PackageNotFoundError:\n"
                "        missing.append(name)\n"
                "for item in seen:\n"
                "    print(item)\n"
                "print('requirements_verify_end')\n"
                "if missing:\n"
                "    raise SystemExit('missing packages after pip install: ' + ', '.join(missing))\n"
                "if version_too_low:\n"
                "    raise SystemExit('packages installed but version too low: ' + '; '.join(version_too_low))\n"
                "if import_missing:\n"
                "    raise SystemExit('packages installed but import failed: ' + '; '.join(import_missing))\n"
                "PY\n"
                "if { [ \"${SANDBOX_AUTO_INSTALL_BROWSERS:-0}\" = \"1\" ] || [ \"${SANDBOX_IMAGE_VARIANT:-}\" = \"playwright\" ]; } && grep -Eiq '^(playwright|patchright)([<=> ]|$)' /tmp/requirements.txt; then\n"
                "  echo 'browser_install_start variant='\"${SANDBOX_IMAGE_VARIANT:-}\";\n"
                "  if python3 -m patchright --help >/dev/null 2>&1; then\n"
                "    python3 -m patchright install chromium || python3 -m playwright install chromium\n"
                "  else\n"
                "    python3 -m playwright install chromium\n"
                "  fi\n"
                "  echo 'browser_install_done'\n"
                "fi"
            ),
        ]
        env = {**_sandbox_default_environment(), **dict(policy.environment or {}), "SANDBOX_REQUIREMENTS_B64": b64}
        logger.info(
            "st49_sandbox_requirements_install_start code=requirements_install_start user_id=%s dep_hash=%s sandbox_id=%s image_ref=%s req_bytes=%s timeout_ms=%s",
            user_id,
            dep_hash,
            str((handle.metadata or {}).get("sandbox_id") or ""),
            str((handle.metadata or {}).get("image_ref") or ""),
            len(normalized.encode("utf-8")),
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
                )  # type: ignore[attr-defined]
                exit_code = _command_exit_code(install_result)
                stdout, stderr = _command_output(install_result)
                if isinstance(exit_code, int) and exit_code != 0:
                    logger.warning(
                        "st49_sandbox_requirements_install_failed code=requirements_install_nonzero user_id=%s dep_hash=%s exit_code=%s sandbox_id=%s stdout_tail=%r stderr_tail=%r",
                        user_id,
                        dep_hash,
                        exit_code,
                        str((handle.metadata or {}).get("sandbox_id") or ""),
                        _tail(stdout),
                        _tail(stderr),
                    )
                    raise RuntimeError(
                        "沙箱 requirements 安装失败"
                        f"（exit_code={exit_code}）。stdout_tail={_tail(stdout)} stderr_tail={_tail(stderr)}"
                    )
                handle.metadata["installed_requirements_hash"] = dep_hash
                handle.metadata["verified_requirements_hash"] = dep_hash
                handle.metadata["requirements_verifier_version"] = _REQUIREMENTS_VERIFIER_VERSION
                handle.metadata[_REQUIREMENTS_REAL_VERIFIED_AT_KEY] = time.time()
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
                    _tail(stdout, 2000),
                    _tail(stderr, 2000),
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
            # 不更新 hash：下次仍会重试，便于用户修复 requirements 后再次验证
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

    async def _ensure_workspace_handle(
        self,
        *,
        user_id: str,
        session_id: str,
        workspace_path: Path,
        turn_id: str,
        tool_call_id: str,
        timeout_ms: int,
    ) -> SandboxHandle:
        host_sessions_root = host_sessions_root_from_workspace(workspace_path)
        policy = self._workspace_only_policy(host_sessions_root, timeout_ms=timeout_ms)
        req = SandboxExecutionRequest(
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            tool_call_id=tool_call_id,
            tool_name="__sandbox_workspace_fs__",
            tool_kind="internal",
            payload={},
            timeout_ms=policy.timeout_ms,
            runner=lambda: asyncio.sleep(0),
            workspace_path=workspace_path,
            policy=policy,
        )
        return await self._ensure_user_handle(req, policy)

    async def read_workspace_text(
        self,
        *,
        user_id: str,
        session_id: str,
        workspace_path: Path,
        rel_path: str,
        turn_id: str = "workspace-fs",
        tool_call_id: str = "read",
    ) -> str:
        started_at = time.perf_counter()
        handle = await self._ensure_workspace_handle(
            user_id=user_id,
            session_id=session_id,
            workspace_path=workspace_path,
            turn_id=turn_id,
            tool_call_id=tool_call_id,
            timeout_ms=60_000,
        )
        session_rel = normalize_rel_path(rel_path)
        inner = f"{sandbox_session_dir(session_id)}/{session_rel}".rstrip("/")
        sandbox_id = str((handle.metadata or {}).get("sandbox_id") or "")
        try:
            data = await self._adapter.read_file(handle, inner)
            text = data.decode("utf-8")
            logger.info(
                "sandbox_workspace_read_done user_id=%s session_id=%s path=%s bytes=%s elapsed_ms=%s sandbox_id=%s",
                user_id,
                session_id,
                session_rel,
                len(data),
                int((time.perf_counter() - started_at) * 1000),
                sandbox_id,
            )
            return text
        except Exception as e:
            status = "not_found" if "404" in str(e) or "not found" in str(e).lower() else "error"
            logger.warning(
                "sandbox_workspace_read_failed status=%s user_id=%s session_id=%s path=%s elapsed_ms=%s sandbox_id=%s err=%s",
                status,
                user_id,
                session_id,
                session_rel,
                int((time.perf_counter() - started_at) * 1000),
                sandbox_id,
                str(e)[:500],
            )
            if status == "not_found":
                raise FileNotFoundError(session_rel) from e
            raise

    async def write_workspace_text(
        self,
        *,
        user_id: str,
        session_id: str,
        workspace_path: Path,
        rel_path: str,
        content: str,
        turn_id: str = "workspace-fs",
        tool_call_id: str = "write",
    ) -> None:
        started_at = time.perf_counter()
        handle = await self._ensure_workspace_handle(
            user_id=user_id,
            session_id=session_id,
            workspace_path=workspace_path,
            turn_id=turn_id,
            tool_call_id=tool_call_id,
            timeout_ms=60_000,
        )
        session_rel = normalize_rel_path(rel_path)
        inner = f"{sandbox_session_dir(session_id)}/{session_rel}".rstrip("/")
        sandbox_id = str((handle.metadata or {}).get("sandbox_id") or "")
        data = content.encode("utf-8")
        try:
            await self._adapter.write_file(handle, inner, data)
            logger.info(
                "sandbox_workspace_write_done user_id=%s session_id=%s path=%s bytes=%s elapsed_ms=%s sandbox_id=%s",
                user_id,
                session_id,
                session_rel,
                len(data),
                int((time.perf_counter() - started_at) * 1000),
                sandbox_id,
            )
        except Exception as e:
            logger.warning(
                "sandbox_workspace_write_failed user_id=%s session_id=%s path=%s bytes=%s elapsed_ms=%s sandbox_id=%s err=%s",
                user_id,
                session_id,
                session_rel,
                len(data),
                int((time.perf_counter() - started_at) * 1000),
                sandbox_id,
                str(e)[:500],
            )
            raise

    async def mkdir_workspace(
        self,
        *,
        user_id: str,
        session_id: str,
        workspace_path: Path,
        rel_path: str,
        turn_id: str = "workspace-fs",
    ) -> None:
        started_at = time.perf_counter()
        handle = await self._ensure_workspace_handle(
            user_id=user_id,
            session_id=session_id,
            workspace_path=workspace_path,
            turn_id=turn_id,
            tool_call_id="mkdir",
            timeout_ms=60_000,
        )
        session_rel = normalize_rel_path(rel_path)
        inner = f"{sandbox_session_dir(session_id)}/{session_rel}".rstrip("/")
        sandbox_id = str((handle.metadata or {}).get("sandbox_id") or "")
        if hasattr(self._adapter, "exec_command"):
            try:
                await self._adapter.exec_command(handle, ["mkdir", "-p", inner])  # type: ignore[attr-defined]
                logger.info(
                    "sandbox_workspace_mkdir_done user_id=%s session_id=%s path=%s elapsed_ms=%s sandbox_id=%s",
                    user_id,
                    session_id,
                    session_rel,
                    int((time.perf_counter() - started_at) * 1000),
                    sandbox_id,
                )
            except Exception as e:
                logger.warning(
                    "sandbox_workspace_mkdir_failed user_id=%s session_id=%s path=%s elapsed_ms=%s sandbox_id=%s err=%s",
                    user_id,
                    session_id,
                    session_rel,
                    int((time.perf_counter() - started_at) * 1000),
                    sandbox_id,
                    str(e)[:500],
                )
                raise
            return
        # Tests / minimal fakes: create on host workspace root (same bind mount as /workspace)
        p = ensure_within_root(workspace_path / session_rel, workspace_path)
        p.mkdir(parents=True, exist_ok=True)

    async def list_workspace_files_flat(
        self,
        *,
        user_id: str,
        session_id: str,
        workspace_path: Path,
        rel_prefix: str = "",
        turn_id: str = "workspace-fs",
    ) -> List[Dict[str, Any]]:
        started_at = time.perf_counter()
        handle = await self._ensure_workspace_handle(
            user_id=user_id,
            session_id=session_id,
            workspace_path=workspace_path,
            turn_id=turn_id,
            tool_call_id="list",
            timeout_ms=120_000,
        )
        root_rel = normalize_rel_path(rel_prefix)
        root = f"{sandbox_session_dir(session_id)}/{root_rel}".rstrip("/")
        sandbox_id = str((handle.metadata or {}).get("sandbox_id") or "")
        try:
            items = await self._adapter.list_artifacts(handle, task_id=root)
            logger.info(
                "sandbox_workspace_list_done user_id=%s session_id=%s path=%s count=%s elapsed_ms=%s sandbox_id=%s",
                user_id,
                session_id,
                root_rel or ".",
                len(items or []),
                int((time.perf_counter() - started_at) * 1000),
                sandbox_id,
            )
            return items
        except Exception as e:
            logger.warning(
                "sandbox_workspace_list_failed user_id=%s session_id=%s path=%s elapsed_ms=%s sandbox_id=%s err=%s",
                user_id,
                session_id,
                root_rel or ".",
                int((time.perf_counter() - started_at) * 1000),
                sandbox_id,
                str(e)[:500],
            )
            raise

    async def exec_workspace_shell(
        self,
        *,
        user_id: str,
        session_id: str,
        workspace_path: Path,
        argv: List[str],
        turn_id: str = "workspace-fs",
        tool_call_id: str = "exec",
        timeout_ms: int = 120_000,
    ) -> Dict[str, Any]:
        started_at = time.perf_counter()
        handle = await self._ensure_workspace_handle(
            user_id=user_id,
            session_id=session_id,
            workspace_path=workspace_path,
            turn_id=turn_id,
            tool_call_id=tool_call_id,
            timeout_ms=timeout_ms,
        )
        if hasattr(self._adapter, "exec_command"):
            sandbox_id = str((handle.metadata or {}).get("sandbox_id") or "")
            try:
                result = await self._adapter.exec_command(
                    handle,
                    argv,
                    cwd=sandbox_session_dir(session_id),
                    timeout_ms=timeout_ms,
                )  # type: ignore[attr-defined]
                logger.info(
                    "sandbox_workspace_exec_done user_id=%s session_id=%s argv0=%s argc=%s exit_code=%s elapsed_ms=%s sandbox_id=%s",
                    user_id,
                    session_id,
                    str(argv[0] if argv else ""),
                    len(argv or []),
                    result.get("exit_code") if isinstance(result, dict) else "",
                    int((time.perf_counter() - started_at) * 1000),
                    sandbox_id,
                )
                return result
            except Exception as e:
                logger.warning(
                    "sandbox_workspace_exec_failed user_id=%s session_id=%s argv0=%s argc=%s elapsed_ms=%s sandbox_id=%s err=%s",
                    user_id,
                    session_id,
                    str(argv[0] if argv else ""),
                    len(argv or []),
                    int((time.perf_counter() - started_at) * 1000),
                    sandbox_id,
                    str(e)[:500],
                )
                raise
        raise RuntimeError("当前沙箱适配器不支持 exec_command，无法执行目录/重命名等 shell 操作。")

    async def execute(self, req: SandboxExecutionRequest) -> Dict[str, Any]:
        policy = await self._build_policy(req)
        cwd = self._resolve_cwd(policy, req)
        mount_targets = [str(m.target or "") for m in (policy.volume_mounts or []) if str(m.target or "")]
        payload = req.payload if isinstance(req.payload, dict) else {}
        command = payload.get("__sandbox_command")
        env = self._prepare_command_env(req, payload.get("__sandbox_env"))
        started = time.time()
        user_id = (req.user_id or "").strip() or f"session:{req.session_id}"
        for attempt in range(2):
            handle: Optional[SandboxHandle] = None
            try:
                handle = await self._ensure_user_handle(req, policy)
                append_sandbox_event(
                    session_id=req.session_id,
                    event_type="sandbox_command_started",
                    turn_id=req.turn_id,
                    payload={
                        "tool_name": req.tool_name,
                        "tool_kind": req.tool_kind,
                        "tool_call_id": req.tool_call_id,
                        "user_id": req.user_id,
                        "sandbox_id": handle.metadata.get("sandbox_id", ""),
                        "cwd": cwd,
                        "mount_count": len(policy.volume_mounts or []),
                        "mount_targets": mount_targets,
                        "attempt": attempt + 1,
                    },
                )
                result = await self._adapter.run_tool_in_sandbox(
                    handle,
                    {
                        "tool_name": req.tool_name,
                        "tool_kind": req.tool_kind,
                        "payload": payload,
                        "timeout_ms": req.timeout_ms,
                        "runner": req.runner,
                        "cwd": cwd,
                        "command": command if isinstance(command, list) else None,
                            "env": env,
                    },
                )
                if isinstance(result, dict):
                    trace = result.get("_sandbox_trace")
                    if not isinstance(trace, dict):
                        trace = {}
                    trace.setdefault("sandbox_id", str((handle.metadata or {}).get("sandbox_id") or ""))
                    trace.setdefault("image_ref", str((handle.metadata or {}).get("image_ref") or ""))
                    trace.setdefault(
                        "installed_requirements_hash",
                        str((handle.metadata or {}).get("installed_requirements_hash") or ""),
                    )
                    trace.setdefault(
                        "verified_requirements_hash",
                        str((handle.metadata or {}).get("verified_requirements_hash") or ""),
                    )
                    trace.setdefault(
                        "requirements_verifier_version",
                        str((handle.metadata or {}).get("requirements_verifier_version") or ""),
                    )
                    result["_sandbox_trace"] = trace
                append_sandbox_event(
                    session_id=req.session_id,
                    event_type="sandbox_command_finished",
                    turn_id=req.turn_id,
                    payload={
                        "tool_name": req.tool_name,
                        "tool_call_id": req.tool_call_id,
                        "user_id": req.user_id,
                        "sandbox_id": handle.metadata.get("sandbox_id", ""),
                        "elapsed_ms": int((time.time() - started) * 1000),
                        "attempt": attempt + 1,
                    },
                )
                return result
            except TimeoutError:
                append_sandbox_event(
                    session_id=req.session_id,
                    event_type="sandbox_command_timeout",
                    turn_id=req.turn_id,
                    payload={"tool_name": req.tool_name, "tool_call_id": req.tool_call_id},
                )
                raise
            except Exception as exc:  # noqa: BLE001
                if attempt == 0 and self._is_sandbox_not_found_error(exc):
                    await self._invalidate_user_handle(user_id, expected_handle=handle)
                    append_sandbox_event(
                        session_id=req.session_id,
                        event_type="sandbox_session_recreated",
                        turn_id=req.turn_id,
                        payload={
                            "tool_name": req.tool_name,
                            "tool_call_id": req.tool_call_id,
                            "user_id": req.user_id,
                            "reason": "sandbox_not_found",
                        },
                    )
                    continue
                if attempt == 0 and "all connection attempts failed" in str(exc).lower():
                    await self._invalidate_user_handle(user_id, expected_handle=handle)
                    append_sandbox_event(
                        session_id=req.session_id,
                        event_type="sandbox_session_recreated",
                        turn_id=req.turn_id,
                        payload={
                            "tool_name": req.tool_name,
                            "tool_call_id": req.tool_call_id,
                            "user_id": req.user_id,
                            "reason": "sandbox_connectivity_error",
                        },
                    )
                    continue
                if attempt == 0 and "tool not allowed by sandbox policy" in str(exc).lower():
                    await self._invalidate_user_handle(user_id, expected_handle=handle)
                    append_sandbox_event(
                        session_id=req.session_id,
                        event_type="sandbox_session_recreated",
                        turn_id=req.turn_id,
                        payload={
                            "tool_name": req.tool_name,
                            "tool_call_id": req.tool_call_id,
                            "user_id": req.user_id,
                            "reason": "sandbox_tool_policy_mismatch",
                        },
                    )
                    continue
                append_sandbox_event(
                    session_id=req.session_id,
                    event_type="sandbox_command_failed",
                    turn_id=req.turn_id,
                    payload={
                        "tool_name": req.tool_name,
                        "tool_call_id": req.tool_call_id,
                        "user_id": req.user_id,
                        "error": str(exc),
                        "cwd": cwd,
                        "mount_count": len(policy.volume_mounts or []),
                        "mount_targets": mount_targets,
                        "attempt": attempt + 1,
                    },
                )
                diag = {
                    "sandbox_id": str(((handle.metadata if handle is not None else {}) or {}).get("sandbox_id") or ""),
                    "sandbox_cwd": cwd,
                    "mount_count": len(policy.volume_mounts or []),
                    "mount_targets": mount_targets,
                    "resource_limit": {
                        "cpu": policy.cpu_limit,
                        "memory_mb": policy.memory_limit_mb,
                    },
                    "last_sandbox_error_code": "INVALID_REQUEST_BODY"
                    if "INVALID_REQUEST_BODY" in str(exc)
                    else ("HTTP_400" if "Status code: 400" in str(exc) else ""),
                }
                raise RuntimeError(f"{exc} | sandbox_diag={json.dumps(diag, ensure_ascii=False)}") from exc
        raise RuntimeError("sandbox execution failed without terminal error")

    async def dispose_user(self, user_id: str, *, turn_id: str = "") -> None:
        async with self._lock:
            keys = [k for k in list(self._user_handles.keys()) if k == user_id or k.startswith(f"{user_id}:")]
            handles = [(k, self._user_handles.pop(k)) for k in keys]
        for _k, (_handle, _) in handles:
            await self._adapter.dispose_sandbox(_handle)
            append_sandbox_event(
                session_id=user_id,
                event_type="sandbox_session_disposed",
                turn_id=turn_id,
                payload={"sandbox_id": _handle.metadata.get("sandbox_id", ""), "user_id": user_id},
            )

    async def dispose_session(self, session_id: str, *, turn_id: str = "") -> None:
        sid = (session_id or "").strip()
        async with self._lock:
            keys = [
                k
                for k, (handle, _touched) in list(self._user_handles.items())
                if str((handle.metadata or {}).get("app_session_id") or "").strip() == sid
            ]
            handles = [(k, self._user_handles.pop(k)) for k in keys]
        for _k, (_handle, _) in handles:
            await self._adapter.dispose_sandbox(_handle)
            append_sandbox_event(
                session_id=session_id,
                event_type="sandbox_session_disposed",
                turn_id=turn_id,
                payload={
                    "sandbox_id": _handle.metadata.get("sandbox_id", ""),
                    "session_id": session_id,
                    "mode": "user_session_sandbox",
                },
            )

    async def prewarm_user_sandbox(
        self,
        user_id: str,
        *,
        reason: str = "manual",
        timeout_ms: int = 60_000,
    ) -> Dict[str, Any]:
        """提前创建并缓存用户级沙箱，减少首次工具调用冷启动延迟。"""
        uid = (user_id or "").strip()
        if not uid:
            raise ValueError("user_id is required")
        user_ctx = get_user_context_for(uid)
        workspaces_subdir = (os.getenv("WORKSPACES_SUBDIR") or "workspaces").strip() or "workspaces"
        workspaces_root = (user_ctx.agent_outputs_dir / workspaces_subdir).resolve()
        workspaces_root.mkdir(parents=True, exist_ok=True)
        policy = self._workspace_with_skills_policy(
            workspaces_root,
            skills_root_path=user_ctx.skills_dir.resolve(),
            timeout_ms=timeout_ms,
        )
        policy = self._apply_user_image_policy(self._apply_fixed_resource_policy(policy), uid)
        if (self._read_user_sandbox_requirements(uid) or "").strip() and not policy.allow_network:
            policy = replace(policy, allow_network=True)
        req = SandboxExecutionRequest(
            user_id=uid,
            session_id=f"prewarm:{uid}",
            turn_id=f"prewarm:{reason}",
            tool_call_id=f"prewarm:{reason}",
            tool_name="__sandbox_prewarm__",
            tool_kind="internal",
            payload={},
            timeout_ms=policy.timeout_ms,
            runner=lambda: asyncio.sleep(0),
            workspace_path=workspaces_root,
            policy=policy,
        )
        handle = await self._ensure_user_handle(req, policy)
        if hasattr(self._adapter, "exec_command"):
            try:
                await self._adapter.exec_command(  # type: ignore[attr-defined]
                    handle,
                    ["sh", "-lc", "true"],
                    cwd="/",
                    timeout_ms=min(10_000, int(policy.timeout_ms)),
                )
            except Exception as e:  # noqa: BLE001
                if self._is_sandbox_not_found_error(e):
                    await self._invalidate_user_handle(uid, expected_handle=handle)
                    handle = await self._ensure_user_handle(req, policy)
                else:
                    raise
        return {
            "status": "ok",
            "user_id": uid,
            "sandbox_id": str((handle.metadata or {}).get("sandbox_id") or ""),
            "image_ref": str((handle.metadata or {}).get("image_ref") or ""),
            "requirements_hash": self._requirements_hash_for_user(uid),
            "installed_requirements_hash": str((handle.metadata or {}).get("installed_requirements_hash") or ""),
            "verified_requirements_hash": str((handle.metadata or {}).get("verified_requirements_hash") or ""),
            "requirements_verifier_version": str((handle.metadata or {}).get("requirements_verifier_version") or ""),
            "requirements_real_verified_at": float((handle.metadata or {}).get(_REQUIREMENTS_REAL_VERIFIED_AT_KEY) or 0),
            "backend": self.backend_label(),
            "reason": reason,
        }

    async def prewarm_all_known_users(
        self,
        *,
        reason: str = "startup",
        timeout_ms: int = 60_000,
    ) -> Dict[str, Any]:
        root = users_data_root()
        if not root.exists():
            return {"status": "ok", "users_total": 0, "ok": 0, "failed": 0, "errors": []}
        users = sorted([p.name for p in root.iterdir() if p.is_dir() and p.name.strip()])
        ok_count = 0
        errors: List[Dict[str, str]] = []
        for uid in users:
            try:
                await self.prewarm_user_sandbox(uid, reason=reason, timeout_ms=timeout_ms)
                ok_count += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning("sandbox_prewarm_known_user_failed user=%s err=%s", uid, exc)
                errors.append({"user_id": uid, "error": str(exc)})
        return {
            "status": "ok",
            "users_total": len(users),
            "ok": ok_count,
            "failed": len(errors),
            "errors": errors,
        }
