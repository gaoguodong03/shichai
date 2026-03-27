"""执行 Skill 目录下 scripts/ 中的脚本，作为一等步骤能力。"""
import asyncio
import os
import subprocess
import json
import shutil
import sys
import uuid
from pathlib import Path
from typing import Any

from langchain_core.tools import tool

from app.agent.sandbox_adapter import SandboxPolicy
from app.agent.tool_gateway import ToolExecutionContext, UnifiedToolGateway
from app.api.files import get_workspace_root_path
from app.core.feature_flags import is_feature_enabled

_ALLOWED_SCRIPT_SUFFIX = {".py", ".sh", ".bash", ".ps1", ".cmd", ".bat"}
_SCRIPT_GATEWAY = UnifiedToolGateway()
_BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _get_skills_dir() -> Path:
    from app.core.user_context import get_current_user_context

    user_ctx = get_current_user_context(default_fallback=False)
    if user_ctx is None:
        raise RuntimeError("缺少用户上下文，无法定位用户技能目录。")
    return user_ctx.skills_dir.resolve()


def _get_workspace_root(workspace_id: str) -> Path:
    return get_workspace_root_path(workspace_id).resolve()


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


def _load_manifest(script_root: Path) -> dict[str, Any]:
    """读取 scripts/manifest.json（可选）。"""
    manifest_path = script_root / "manifest.json"
    if not manifest_path.exists():
        return {}
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(raw, dict):
        return {}
    scripts = raw.get("scripts")
    if isinstance(scripts, dict):
        return scripts
    return raw if all(isinstance(v, dict) for v in raw.values()) else {}


def _script_meta_for(manifest: dict[str, Any], script_path: str) -> dict[str, Any]:
    """从 manifest 中取脚本配置（精确匹配文件名，兼容 basename 兜底）。"""
    meta = manifest.get(script_path)
    if isinstance(meta, dict):
        return meta
    basename = Path(script_path).name
    fallback = manifest.get(basename)
    return fallback if isinstance(fallback, dict) else {}


def _parse_input_json(input_json: str) -> tuple[Any, str | None]:
    """解析 input_json；为空返回空对象。"""
    raw = (input_json or "").strip()
    if not raw:
        return {}, None
    try:
        return json.loads(raw), None
    except Exception as e:
        return None, f"input_json 不是合法 JSON: {e}"


def _validate_against_manifest(script_path: str, script_meta: dict[str, Any], parsed_input: Any) -> str | None:
    """按 manifest.input_schema 做最小校验（仅 required）。"""
    schema = script_meta.get("input_schema")
    if not isinstance(schema, dict):
        return None
    required = schema.get("required")
    if not isinstance(required, list) or not required:
        return None
    if not isinstance(parsed_input, dict):
        return f"脚本 {script_path} 要求 input_json 为对象，且包含字段: {required}"
    missing = [k for k in required if k not in parsed_input]
    if missing:
        return f"脚本 {script_path} 缺少必填字段: {missing}"
    return None


def _json_result(**kwargs: Any) -> str:
    """统一结构化输出。"""
    return json.dumps(kwargs, ensure_ascii=False)


def _build_script_command(full: Path) -> list[str]:
    """按脚本后缀构造执行命令，优先兼容当前 Python/Windows 环境。"""
    suffix = full.suffix.lower()
    if suffix == ".py":
        # 使用当前解释器，保证 conda/venv 环境一致
        return [sys.executable or "python", str(full)]
    if suffix in (".sh", ".bash"):
        bash = shutil.which("bash")
        if not bash:
            raise RuntimeError("当前环境未找到 bash，无法执行 .sh/.bash 脚本。")
        return [bash, str(full)]
    if suffix == ".ps1":
        pwsh = shutil.which("pwsh") or shutil.which("powershell")
        if not pwsh:
            raise RuntimeError("当前环境未找到 PowerShell，无法执行 .ps1 脚本。")
        return [pwsh, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(full)]
    if suffix in (".cmd", ".bat"):
        comspec = os.environ.get("ComSpec") or "cmd.exe"
        return [comspec, "/c", str(full)]
    raise RuntimeError(f"不支持的脚本后缀: {suffix}")


def _execute_script_subprocess(
    *,
    script_full_path: Path,
    script_path: str,
    skill_id: str,
    workspace_id: str,
    write_mode: str,
    input_json: str,
    script_root: Path,
    timeout_sec: int,
) -> dict[str, Any]:
    workspace_root = _get_workspace_root(workspace_id)
    workspace_root.mkdir(parents=True, exist_ok=True)
    try:
        cmd = _build_script_command(script_full_path)
    except RuntimeError as e:
        return {"ok": False, "code": "runtime_missing", "message": str(e)}
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(workspace_root),
            input=input_json if input_json else None,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            env={
                **os.environ,
                "SKILL_ID": skill_id,
                "SKILL_WRITE_MODE": write_mode,
                "SKILL_WORKSPACE_ID": workspace_id,
                "SKILL_WORKSPACE_ROOT": str(workspace_root),
                "SKILL_SCRIPT_ROOT": str(script_root),
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


def create_run_skill_script_tool(skill_id: str, workspace_id: str = "", write_mode: str = "readonly"):
    """
    创建「执行当前技能下脚本」的工具，仅允许运行该 skill 的 scripts/ 目录内脚本。
    脚本可在 SKILL.md 或 scripts 中被描述，由 LLM 在需要时调用。
    """
    skills_dir = _get_skills_dir()
    script_root = (skills_dir / skill_id / "scripts").resolve()
    if not script_root.exists():
        script_root.mkdir(parents=True, exist_ok=True)

    @tool
    async def run_skill_script(script_path: str, input_json: str = "") -> str:
        """执行当前技能 scripts 目录下的脚本。script_path 为相对 scripts 的路径（如 optimize-prompt.py）；input_json 为可选 JSON 字符串，会作为 stdin 传入脚本。支持 .py/.sh/.ps1/.cmd/.bat。"""
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

        # 兼容 LLM 把整个 JSON 对象字符串塞进 script_path 的情况，例如：
        # script_path='{"script_path": "hello_dha.py", "input_json": ""}'
        raw_script_param = (script_path or "").strip()
        try:
            if raw_script_param.startswith("{") and raw_script_param.endswith("}"):
                maybe_obj = json.loads(raw_script_param)
                if isinstance(maybe_obj, dict) and "script_path" in maybe_obj:
                    script_path = str(maybe_obj.get("script_path", "")).strip()
                    if "input_json" in maybe_obj and not input_json:
                        ij = maybe_obj["input_json"]
                        input_json = ij if isinstance(ij, str) else json.dumps(ij, ensure_ascii=False)
                else:
                    script_path = raw_script_param
            else:
                script_path = raw_script_param
        except Exception:
            script_path = raw_script_param

        if script_path in ("__list__", ":list", "list"):
            return _json_result(
                ok=True,
                code="scripts_list",
                scripts=available_scripts,
                count=len(available_scripts),
                message="已返回当前 skill 的可执行脚本列表。",
            )
        if script_path in ("__manifest__", ":manifest", "manifest"):
            return _json_result(
                ok=True,
                code="manifest",
                manifest=manifest,
                message="已返回当前 skill 的脚本 manifest。",
            )
        if script_path.startswith("__describe__:"):
            target = script_path.split(":", 1)[1].strip()
            return _json_result(
                ok=True,
                code="script_description",
                script=target,
                meta=_script_meta_for(manifest, target),
                message="已返回脚本说明。",
            )

        if not script_path or ".." in script_path or script_path.startswith("/"):
            return _json_result(
                ok=False,
                code="invalid_script_path",
                message="script_path 必须为相对路径且不包含 ..。",
            )
        script_path = script_path.strip().lstrip("/")
        full = (script_root / script_path).resolve()
        if not str(full).startswith(str(script_root)) or not full.is_file():
            return _json_result(
                ok=False,
                code="script_not_found",
                message=f"脚本不存在或不在允许目录内: {script_path}",
                available_scripts=available_scripts,
            )
        if full.suffix.lower() not in _ALLOWED_SCRIPT_SUFFIX:
            return _json_result(
                ok=False,
                code="unsupported_suffix",
                message=f"不支持脚本后缀: {full.suffix.lower()}",
                available_scripts=available_scripts,
            )

        parsed_input, parse_error = _parse_input_json(input_json)
        if parse_error:
            return _json_result(ok=False, code="invalid_input_json", message=parse_error)
        script_meta = _script_meta_for(manifest, script_path)
        schema_error = _validate_against_manifest(script_path, script_meta, parsed_input)
        if schema_error:
            return _json_result(ok=False, code="manifest_validation_failed", message=schema_error, meta=script_meta)

        timeout_sec = int(script_meta.get("timeout_sec") or os.getenv("SKILL_SCRIPT_TIMEOUT", "60"))
        async def _runner() -> dict[str, Any]:
            return await asyncio.to_thread(
                _execute_script_subprocess,
                script_full_path=full,
                script_path=script_path,
                skill_id=skill_id,
                workspace_id=workspace_id,
                write_mode=write_mode,
                input_json=input_json,
                script_root=script_root,
                timeout_sec=timeout_sec,
            )

        result_payload: dict[str, Any]
        if is_feature_enabled("UNIFIED_TOOL_GATEWAY_ENABLED", default=True):
            ctx = ToolExecutionContext(
                session_id=workspace_id,
                workspace_id=str(workspace_root),
                agent_id=f"skill:{skill_id}",
                skill_id=skill_id,
                task_id=f"skill-script:{skill_id}",
                turn_id=f"script:{uuid.uuid4().hex}",
                tool_call_id=f"run_skill_script:{script_path}:{uuid.uuid4().hex}",
                timeout_ms=max(1000, timeout_sec * 1000),
                retry_count=0,
                policy=SandboxPolicy(
                    fs_root=str(workspace_root),
                    timeout_ms=max(1000, timeout_sec * 1000),
                    tool_allowlist=["run_skill_script", f"run_skill_script_{skill_id}"],
                ),
            )
            gw = await _SCRIPT_GATEWAY.execute(
                tool_name=f"run_skill_script_{skill_id}",
                tool_kind="script",
                payload={"script_path": script_path},
                context=ctx,
                runner=_runner,
            )
            if not gw.ok:
                return _json_result(
                    ok=False,
                    code="gateway_execution_error",
                    message=gw.error or "统一网关执行失败",
                    gateway_interrupt_reason=getattr(gw.interrupt_reason, "value", str(gw.interrupt_reason)),
                )
            result_payload = dict(gw.output or {})
        else:
            result_payload = await _runner()
        return _json_result(**result_payload)

    run_skill_script.name = "run_skill_script"
    run_skill_script.description = (
        "执行当前技能 scripts 目录下的脚本（如 optimize-prompt.py）。"
        "参数：script_path（相对 scripts 的文件名），input_json（可选，JSON 字符串作为 stdin）。"
        "支持命令：__list__（列出脚本）、__manifest__（查看 manifest）、__describe__:<script>。"
        "技能说明或 scripts 中若要求「运行某脚本」时使用本工具。"
    )
    return run_skill_script
