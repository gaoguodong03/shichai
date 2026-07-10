"""执行 Skill 目录下 scripts/ 中的脚本，作为一等步骤能力。"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import os
import subprocess
import json
import re
import uuid
from pathlib import Path
from typing import Any, Optional

from app.agent.skill_tool_naming import build_skill_script_tool_name
from app.agent.sandbox_mount_policy import SANDBOX_SKILLS_ROOT
from app.agent.session_workspace_policy import sandbox_session_dir
from app.agent.structured_output_contracts import SkillScriptStdoutPayload, strict_json_object_from_text
from app.agent.tool_spec import ToolSpec
from app.agent.tool_gateway import ToolExecutionContext, UnifiedToolGateway
from app.api.files import get_workspace_root_path
from app.core.feature_flags import is_feature_enabled
from app.tools.skill_script_manifest import (
    ALLOWED_SCRIPT_SUFFIX as _ALLOWED_SCRIPT_SUFFIX,
    input_schema_from_manifest as _input_schema_from_manifest,
    load_skill_script_manifest as _load_manifest,
    manifest_args_to_cli_argv as _manifest_args_to_cli_argv,
    normalize_skill_script_path as _normalize_skill_script_path,
)
from app.tools.skill_script_sandbox_request import (
    build_sandbox_exec_request as _build_sandbox_exec_request,
    build_script_command as _build_script_command,
    inline_shell_env as _inline_shell_env,
    resolve_script_timeout_sec as _resolve_script_timeout_sec,
)

logger = logging.getLogger(__name__)

_SCRIPT_GATEWAY: Optional[UnifiedToolGateway] = None
_SANDBOX_ENV_PASSTHROUGH_KEYS = (
    "JENIYA_API_KEY",
    "JENIYA_IMAGE_BASE_URL",
    "JENIYA_IMAGE_MODEL",
    "QWEN_AUDIO_CHUNK_SECONDS",
    "QWEN_AUDIO_REQUEST_TIMEOUT_SEC",
    "PLAYWRIGHT_BROWSERS_PATH",
)
_DEFAULT_PLAYWRIGHT_BROWSERS_PATH = "/ms-playwright"


def _get_script_gateway() -> UnifiedToolGateway:
    global _SCRIPT_GATEWAY
    if _SCRIPT_GATEWAY is None:
        _SCRIPT_GATEWAY = UnifiedToolGateway()
    return _SCRIPT_GATEWAY
_BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _collect_sandbox_passthrough_env() -> dict[str, str]:
    """将宿主进程中的少量必要变量透传到沙箱命令环境。"""
    out: dict[str, str] = {}
    missing_keys: list[str] = []
    for key in _SANDBOX_ENV_PASSTHROUGH_KEYS:
        val = (os.environ.get(key) or "").strip()
        if val:
            out[key] = val
        else:
            missing_keys.append(key)
    out.setdefault("PLAYWRIGHT_BROWSERS_PATH", _DEFAULT_PLAYWRIGHT_BROWSERS_PATH)
    logger.debug(
        "st49_skill_env_passthrough code=skill_env_passthrough present_keys=%s missing_keys=%s",
        sorted(out.keys()),
        sorted(missing_keys),
    )
    return out


def _get_skills_dir() -> Path:
    from app.core.user_context import get_current_user_context

    user_ctx = get_current_user_context(default_fallback=False)
    if user_ctx is None:
        raise RuntimeError("缺少用户上下文，无法定位用户技能目录。")
    return user_ctx.skills_dir.resolve()


def skill_has_skill_md(directory_name: str) -> bool:
    """Return whether the Skill has the files required for script-tool injection."""
    sid = (directory_name or "").strip()
    if not sid:
        return False
    try:
        home = (_get_skills_dir() / sid).resolve()
        if not (home / "SKILL.md").is_file():
            return False
        manifest = _load_manifest(home / "scripts")
        return bool(manifest)
    except Exception:
        return False


def _get_workspace_root(workspace_id: str) -> Path:
    return get_workspace_root_path(workspace_id).resolve()


def _get_current_user_id() -> str:
    try:
        from app.core.user_context import get_current_user_context

        user_ctx = get_current_user_context(default_fallback=False)
        return user_ctx.user_id if user_ctx is not None else ""
    except Exception:
        return ""


def _current_user_requirements_b64(user_id: str = "") -> str:
    try:
        from app.core.user_context import get_current_user_context, get_user_context_for

        uid = (user_id or "").strip()
        user_ctx = get_user_context_for(uid) if uid else get_current_user_context(default_fallback=False)
        if user_ctx is None:
            return ""
        path = (user_ctx.settings_dir / "sandbox" / "requirements.txt").resolve()
        if not path.exists():
            return ""
        content = path.read_text(encoding="utf-8").strip()
        if not content:
            return ""
        return base64.b64encode(content.encode("utf-8")).decode("ascii")
    except Exception:
        return ""


def _requirements_hash_from_b64(requirements_b64: str) -> str:
    raw = (requirements_b64 or "").strip()
    if not raw:
        return hashlib.sha256(b"").hexdigest()[:16]
    try:
        decoded = base64.b64decode(raw.encode("ascii"))
    except Exception:
        decoded = b""
    return hashlib.sha256(decoded.strip()).hexdigest()[:16]


def _list_available_scripts(script_root: Path) -> list[str]:
    """列出当前 skill 可执行脚本（相对 scripts 目录）。"""
    if not script_root.exists():
        return []
    files: list[str] = []
    for p in script_root.rglob("*"):
        if p.is_file() and p.suffix.lower() in _ALLOWED_SCRIPT_SUFFIX:
            files.append(str(p.relative_to(script_root)).replace("\\", "/"))
    files.sort()
    return files


def _json_result(**kwargs: Any) -> str:
    """统一结构化输出。"""
    return json.dumps(kwargs, ensure_ascii=False)


def _validate_skill_script_stdout(stdout: str) -> str | None:
    raw = str(stdout or "").strip()
    if not raw:
        return "脚本 stdout 必须输出标准 JSON 对象。"
    try:
        payload = strict_json_object_from_text(raw, schema_name="SkillScriptStdoutPayload")
        SkillScriptStdoutPayload.model_validate(payload)
    except Exception as exc:
        return f"脚本 stdout 不符合标准 JSON 协议: {exc}"
    return None


def _extract_sandbox_diag(gateway_error: str) -> dict[str, Any]:
    text = str(gateway_error or "")
    m = re.search(r"sandbox_diag=(\{.*\})", text)
    if not m:
        return {}
    raw = m.group(1)
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _execute_script_subprocess(
    *,
    script_full_path: Path,
    script_path: str,
    directory_name: str,
    workspace_id: str,
    write_mode: str,
    cli_argv: list[str],
    script_root: Path,
    timeout_sec: int,
    run_in_sandbox: bool = False,
) -> dict[str, Any]:
    workspace_root = _get_workspace_root(workspace_id)
    workspace_root.mkdir(parents=True, exist_ok=True)
    sandbox_workspace_dir = sandbox_session_dir(workspace_id)
    script_exec_path = (
        f"{SANDBOX_SKILLS_ROOT}/{directory_name}/scripts/{script_path.lstrip('/')}"
        if run_in_sandbox
        else str(script_full_path)
    )
    cwd_path = sandbox_workspace_dir if run_in_sandbox else str(workspace_root)
    workspace_env_root = sandbox_workspace_dir if run_in_sandbox else str(workspace_root)
    try:
        cmd = _build_script_command(Path(script_exec_path), cli_argv)
    except RuntimeError as e:
        return {"ok": False, "code": "runtime_missing", "message": str(e)}
    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd_path,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            env={
                **os.environ,
                "SKILL_ID": directory_name,
                "SKILL_WRITE_MODE": write_mode,
                "SKILL_WORKSPACE_ID": workspace_id,
                "SKILL_WORKSPACE_ROOT": workspace_env_root,
                "SKILL_SCRIPT_ROOT": (
                    f"{SANDBOX_SKILLS_ROOT}/{directory_name}/scripts"
                    if run_in_sandbox
                    else str(script_root)
                ),
                # 确保用户目录中的 skill 脚本也能 import app.*
                "PYTHONPATH": (
                    str(_BACKEND_ROOT)
                    + (
                        os.pathsep + os.environ.get("PYTHONPATH", "")
                        if os.environ.get("PYTHONPATH")
                        else ""
                    )
                ),
            },
        )
        out = (proc.stdout or "").strip()
        err = (proc.stderr or "").strip()

        if proc.returncode != 0:
            return {
                "ok": False,
                "code": "script_exit_nonzero",
                "message": f"脚本退出码 {proc.returncode}",
                "returncode": proc.returncode,
                "stdout": out,
                "stderr": err,
                "script": script_path,
            }
        return {
            "ok": True,
            "code": "script_executed",
            "script": script_path,
            "returncode": proc.returncode,
            "stdout": out,
            "stderr": err,
            "message": "脚本执行成功。",
        }
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "code": "script_timeout",
            "message": f"脚本执行超时（{timeout_sec} 秒）。",
            "script": script_path,
        }
    except Exception as e:
        return {
            "ok": False,
            "code": "script_execution_error",
            "message": f"执行失败: {e}",
            "script": script_path,
        }


def create_run_skill_script_tool(directory_name: str, workspace_id: str = "", write_mode: str = "readonly"):
    """
    新建「执行当前技能下脚本」的工具，仅允许运行该 skill 的 scripts/ 目录内脚本。
    脚本入口与 LLM 可见参数只来自 scripts/manifest.json。
    """
    skills_dir = _get_skills_dir()
    owner_user_id = _get_current_user_id()
    skill_home = (skills_dir / directory_name).resolve()
    script_root = (skill_home / "scripts").resolve()
    # 仅当该 skill 目录真实存在且含 SKILL.md 时才新建 scripts/，避免 stale directory_name（如改名后未更新的 Agent）生成空壳目录
    if (skill_home / "SKILL.md").is_file():
        script_root.mkdir(parents=True, exist_ok=True)

    async def run_skill_script(**tool_args: Any) -> str:
        """执行 manifest entry 指定的脚本，并把 manifest args 转换为 CLI argv。"""
        if write_mode != "workspace_all":
            return _json_result(
                ok=False,
                code="readonly_mode",
                message="当前 skill 为只读模式，禁止执行脚本。",
            )
        if not workspace_id:
            return _json_result(
                ok=False,
                code="missing_workspace_id",
                message="缺少 workspace_id，无法安全执行脚本。",
            )
        workspace_root = _get_workspace_root(workspace_id)
        workspace_root.mkdir(parents=True, exist_ok=True)
        available_scripts = _list_available_scripts(script_root)
        manifest = _load_manifest(script_root)
        script_path = str(manifest.get("entry") or "").strip()
        if not manifest or not script_path:
            return _json_result(
                ok=False,
                code="missing_script_manifest",
                message="当前 Skill 缺少标准 scripts/manifest.json，无法注入或执行脚本工具。",
            )
        full = (script_root / script_path).resolve()
        if not str(full).startswith(str(script_root)) or not full.is_file():
            hint = ""
            if not available_scripts:
                hint = (
                    f"当前绑定 directory_name={directory_name!r}，脚本目录为 {str(script_root)}。"
                    "若专家配置里仍有已改名/已删除的旧 directory_name，请只保留实际存在的目录名，"
                    f"脚本应放在该目录的 scripts/ 下。"
                )
            return _json_result(
                ok=False,
                code="script_not_found",
                message=f"脚本不存在或不在允许目录内: {script_path}" + (f" {hint}" if hint else ""),
                directory_name=directory_name,
                script_root=str(script_root),
                available_scripts=available_scripts,
            )
        if full.suffix.lower() not in _ALLOWED_SCRIPT_SUFFIX:
            return _json_result(
                ok=False,
                code="unsupported_suffix",
                message=f"不支持脚本后缀: {full.suffix.lower()}",
                available_scripts=available_scripts,
            )

        cli_argv, cli_err = _manifest_args_to_cli_argv(manifest, dict(tool_args or {}))
        if cli_err:
            return _json_result(ok=False, code="manifest_validation_failed", message=cli_err)

        timeout_sec = _resolve_script_timeout_sec(manifest)

        if not is_feature_enabled("UNIFIED_TOOL_GATEWAY_ENABLED", default=True):
            return _json_result(
                ok=False,
                code="gateway_required",
                message=(
                    "技能脚本已取消宿主机子进程兜底，必须与线上一致走 OpenSandbox 统一网关。"
                    "请在环境中设置 UNIFIED_TOOL_GATEWAY_ENABLED=1，并配置 OPENSANDBOX_DOMAIN。"
                ),
            )
        try:
            sandbox_command, sandbox_extra_env, sandbox_cwd = _build_sandbox_exec_request(
                directory_name=directory_name,
                workspace_id=workspace_id,
                script_path=script_path,
                suffix=full.suffix.lower(),
                cli_argv=cli_argv or [],
            )
        except RuntimeError as e:
            return _json_result(ok=False, code="runtime_missing", message=str(e))
        script_tool_name = build_skill_script_tool_name(directory_name)
        current_user_id = owner_user_id
        if not current_user_id:
            logger.warning(
                "st49_skill_script_blocked code=missing_user_context directory_name=%s workspace_id=%s script=%s",
                directory_name,
                workspace_id,
                script_path,
            )
            return _json_result(
                ok=False,
                code="missing_user_context",
                message="缺少用户上下文，无法选择用户沙箱与 requirements.txt。",
            )
        requirements_b64 = _current_user_requirements_b64(current_user_id)
        requirements_hash = _requirements_hash_from_b64(requirements_b64)
        ctx = ToolExecutionContext(
            session_id=workspace_id,
            workspace_id=str(workspace_root),
            agent_name=f"skill:{directory_name}",
            user_id=current_user_id,
            directory_name=directory_name,
            task_id=f"skill-script:{directory_name}",
            turn_id=f"script:{uuid.uuid4().hex}",
            tool_call_id=f"run_skill_script:{script_path}:{uuid.uuid4().hex}",
            timeout_ms=max(1000, timeout_sec * 1000),
            retry_count=1,
            sandbox_cwd=sandbox_cwd,
        )
        logger.info(
            "st49_skill_script_execute_start code=skill_script_start user_id=%s directory_name=%s tool=%s workspace_id=%s script=%s argv_count=%s timeout_ms=%s cwd=%s requirements_hash=%s requirements_present=%s",
            current_user_id,
            directory_name,
            script_tool_name,
            workspace_id,
            script_path,
            len(cli_argv or []),
            int(ctx.timeout_ms or 0),
            sandbox_cwd,
            requirements_hash,
            bool(requirements_b64),
        )
        sandbox_env = {
            "SKILL_ID": directory_name,
            "SKILL_WRITE_MODE": write_mode,
            "SKILL_WORKSPACE_ID": workspace_id,
            "SKILL_WORKSPACE_ROOT": sandbox_session_dir(workspace_id),
            "SKILL_SCRIPT_ROOT": f"{SANDBOX_SKILLS_ROOT}/{directory_name}/scripts",
            "SKILL_HOME": f"{SANDBOX_SKILLS_ROOT}/{directory_name}",
            "SKILL_REQUIREMENTS_B64": requirements_b64,
            "SKILL_REQUIREMENTS_HASH": requirements_hash if requirements_b64 else "",
            **sandbox_extra_env,
            **_collect_sandbox_passthrough_env(),
        }
        sandbox_command = _inline_shell_env(sandbox_command, sandbox_env)
        gw = await _get_script_gateway().execute(
            tool_name=script_tool_name,
            tool_kind="script",
            payload={
                "script_path": script_path,
                "cli_argv": cli_argv or [],
                "__sandbox_command": sandbox_command,
                "__sandbox_env": sandbox_env,
            },
            context=ctx,
            runner=lambda: asyncio.sleep(0, result={}),
        )
        if not gw.ok:
            reason = getattr(gw.interrupt_reason, "value", str(gw.interrupt_reason))
            gateway_error = gw.error or "统一网关执行失败"
            sandbox_diag = _extract_sandbox_diag(gateway_error)
            logger.warning(
                "st49_skill_script_execute_failed code=skill_script_gateway_failed user_id=%s directory_name=%s tool=%s workspace_id=%s script=%s reason=%s elapsed_ms=%s sandbox_id=%s cwd=%s requirements_hash=%s err=%s",
                current_user_id,
                directory_name,
                script_tool_name,
                workspace_id,
                script_path,
                reason,
                int(gw.elapsed_ms or 0),
                str(sandbox_diag.get("sandbox_id") or ""),
                str(sandbox_diag.get("sandbox_cwd") or sandbox_cwd or ""),
                requirements_hash,
                gateway_error[:500],
            )
            if str(reason) == "timeout_or_budget_exceeded":
                return _json_result(
                    ok=False,
                    code="gateway_timeout",
                    message=(
                        "网关等待沙箱执行超时。"
                        "常见原因：OpenSandbox 冷启动慢、首次安装依赖耗时、脚本本身执行过慢。"
                    ),
                    gateway_error=gateway_error,
                    gateway_interrupt_reason=reason,
                    gateway_timeout_ms=int(ctx.timeout_ms or 0),
                    gateway_elapsed_ms=int(gw.elapsed_ms or 0),
                    sandbox_id=str(sandbox_diag.get("sandbox_id") or ""),
                    sandbox_cwd=str(sandbox_diag.get("sandbox_cwd") or ""),
                    mount_count=int(sandbox_diag.get("mount_count") or 0),
                    mount_targets=list(sandbox_diag.get("mount_targets") or []),
                    last_sandbox_error_code=str(sandbox_diag.get("last_sandbox_error_code") or ""),
                )
            if str(reason) == "tool_unavailable":
                return _json_result(
                    ok=False,
                    code="gateway_tool_unavailable",
                    message="网关执行器不可用（沙箱策略/连通性/运行时异常）。",
                    gateway_error=gateway_error,
                    gateway_interrupt_reason=reason,
                    gateway_elapsed_ms=int(gw.elapsed_ms or 0),
                    sandbox_id=str(sandbox_diag.get("sandbox_id") or ""),
                    sandbox_cwd=str(sandbox_diag.get("sandbox_cwd") or ""),
                    mount_count=int(sandbox_diag.get("mount_count") or 0),
                    mount_targets=list(sandbox_diag.get("mount_targets") or []),
                    last_sandbox_error_code=str(sandbox_diag.get("last_sandbox_error_code") or ""),
                )
            return _json_result(
                ok=False,
                code="gateway_execution_error",
                message="统一网关执行失败。",
                gateway_error=gateway_error,
                gateway_interrupt_reason=reason,
                gateway_elapsed_ms=int(gw.elapsed_ms or 0),
                sandbox_id=str(sandbox_diag.get("sandbox_id") or ""),
                sandbox_cwd=str(sandbox_diag.get("sandbox_cwd") or ""),
                mount_count=int(sandbox_diag.get("mount_count") or 0),
                mount_targets=list(sandbox_diag.get("mount_targets") or []),
                last_sandbox_error_code=str(sandbox_diag.get("last_sandbox_error_code") or ""),
            )
        out = dict(gw.output or {})
        exit_code = out.get("exit_code")
        stdout = str(out.get("stdout") or "").strip()
        stderr = str(out.get("stderr") or "").strip()
        sandbox_trace = out.get("_sandbox_trace") if isinstance(out.get("_sandbox_trace"), dict) else {}
        if isinstance(exit_code, int) and exit_code != 0:
            result_payload = {
                "ok": False,
                "code": "script_exit_nonzero",
                "message": f"脚本退出码 {exit_code}",
                "returncode": exit_code,
                "stdout": stdout,
                "stderr": stderr,
                "script": script_path,
                "sandbox_trace": sandbox_trace,
            }
            logger.warning(
                "st49_skill_script_execute_nonzero code=skill_script_nonzero user_id=%s directory_name=%s tool=%s workspace_id=%s script=%s exit_code=%s elapsed_ms=%s stdout_len=%s stderr_len=%s sandbox_id=%s requirements_hash=%s installed_requirements_hash=%s verified_requirements_hash=%s",
                current_user_id,
                directory_name,
                script_tool_name,
                workspace_id,
                script_path,
                exit_code,
                int(gw.elapsed_ms or 0),
                len(stdout),
                len(stderr),
                str(sandbox_trace.get("sandbox_id") or ""),
                requirements_hash,
                str(sandbox_trace.get("installed_requirements_hash") or ""),
                str(sandbox_trace.get("verified_requirements_hash") or ""),
            )
        else:
            stdout_protocol_error = _validate_skill_script_stdout(stdout)
            if stdout_protocol_error:
                result_payload = {
                    "ok": False,
                    "code": "skill_script_stdout_protocol_error",
                    "message": stdout_protocol_error,
                    "returncode": int(exit_code or 0),
                    "stdout": stdout,
                    "stderr": stderr,
                    "script": script_path,
                    "sandbox_trace": sandbox_trace,
                }
                logger.warning(
                    "st49_skill_script_stdout_protocol_error user_id=%s directory_name=%s tool=%s workspace_id=%s script=%s stdout_len=%s stderr_len=%s",
                    current_user_id,
                    directory_name,
                    script_tool_name,
                    workspace_id,
                    script_path,
                    len(stdout),
                    len(stderr),
                )
                return _json_result(**result_payload)
            result_payload = {
                "ok": True,
                "code": "script_executed",
                "script": script_path,
                "returncode": int(exit_code or 0),
                "stdout": stdout,
                "stderr": stderr,
                "sandbox_trace": sandbox_trace,
                "message": "脚本执行成功。",
            }
            logger.info(
                "st49_skill_script_execute_done code=skill_script_done user_id=%s directory_name=%s tool=%s workspace_id=%s script=%s exit_code=%s elapsed_ms=%s stdout_len=%s stderr_len=%s sandbox_id=%s requirements_hash=%s installed_requirements_hash=%s verified_requirements_hash=%s",
                current_user_id,
                directory_name,
                script_tool_name,
                workspace_id,
                script_path,
                int(exit_code or 0),
                int(gw.elapsed_ms or 0),
                len(stdout),
                len(stderr),
                str(sandbox_trace.get("sandbox_id") or ""),
                requirements_hash,
                str(sandbox_trace.get("installed_requirements_hash") or ""),
                str(sandbox_trace.get("verified_requirements_hash") or ""),
            )
        return _json_result(**result_payload)

    manifest = _load_manifest(script_root)
    tool_description = str(manifest.get("description") or "执行当前 Skill 的标准脚本。").strip()

    return ToolSpec.from_function(
        name="run_skill_script",
        description=(
            f"{tool_description}"
            " 参数由 scripts/manifest.json 定义；模型只填写业务字段，不传脚本入口或命令行数组。"
        ),
        coroutine=run_skill_script,
        args_schema=_input_schema_from_manifest(manifest),
    )
