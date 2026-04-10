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
# 命令行参数上限（防滥用）；单段长度上限（兼顾长文本与 --input_text）
_CLI_ARGV_MAX_ITEMS = 64
_CLI_ARGV_MAX_STRLEN = 32_768
_SCRIPT_GATEWAY = UnifiedToolGateway()
_BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _get_skills_dir() -> Path:
    from app.core.user_context import get_current_user_context

    user_ctx = get_current_user_context(default_fallback=False)
    if user_ctx is None:
        raise RuntimeError("缺少用户上下文，无法定位用户技能目录。")
    return user_ctx.skills_dir.resolve()


def skill_has_skill_md(skill_id: str) -> bool:
    """用于组装工具列表：仅当磁盘上存在该 skill 目录且含 SKILL.md 时才注册 run_skill_script，避免 DHA 里陈旧 skill_id 指向空壳目录。"""
    sid = (skill_id or "").strip()
    if not sid:
        return False
    try:
        home = (_get_skills_dir() / sid).resolve()
        return (home / "SKILL.md").is_file()
    except Exception:
        return False


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


def _parse_cli_args_json(cli_args_json: str) -> tuple[list[str] | None, str | None]:
    """
    解析追加到脚本后的 argv（JSON 字符串数组），由 subprocess 列表传入，不经 shell。
    空字符串表示无额外参数。
    """
    raw = (cli_args_json or "").strip()
    if not raw:
        return [], None
    try:
        data = json.loads(raw)
    except Exception as e:
        return None, f"cli_args_json 不是合法 JSON: {e}"
    if not isinstance(data, list):
        return None, "cli_args_json 必须是 JSON 数组（每项为字符串，对应 argv 片段）"
    if len(data) > _CLI_ARGV_MAX_ITEMS:
        return None, f"cli_args_json 数组长度不能超过 {_CLI_ARGV_MAX_ITEMS}"
    out: list[str] = []
    for i, item in enumerate(data):
        if not isinstance(item, str):
            return None, f"cli_args_json[{i}] 必须是字符串"
        if "\x00" in item:
            return None, f"cli_args_json[{i}] 含非法字符"
        if len(item) > _CLI_ARGV_MAX_STRLEN:
            return None, f"cli_args_json[{i}] 长度不能超过 {_CLI_ARGV_MAX_STRLEN}"
        out.append(item)
    return out, None


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


def _normalize_skill_script_path(script_path: str) -> str:
    """
    script_path 约定为相对 skill 的 scripts/ 目录。
    SKILL.md 常写「scripts/foo.py」，模型照抄后会拼成 scripts/scripts/foo.py；
    另如 scripts/__list__ 会误传。此处剥掉多余的 scripts/ 前缀（大小写不敏感）。
    """
    p = (script_path or "").strip().replace("\\", "/")
    while p.startswith("./"):
        p = p[2:].lstrip("/")
    p = p.lstrip("/")
    low = p.lower()
    if low == "scripts":
        return ""
    if low.startswith("scripts/"):
        p = p[8:].lstrip("/")
    return p


def _apply_script_path_normalization(script_path: str) -> str:
    """对 __describe__:<path> 只规范化冒号后的路径。"""
    if script_path.startswith("__describe__:"):
        _, sep, tail = script_path.partition(":")
        return "__describe__:" + _normalize_skill_script_path(tail)
    return _normalize_skill_script_path(script_path)


def _build_script_command(full: Path, extra_argv: list[str] | None = None) -> list[str]:
    """按脚本后缀构造执行命令，优先兼容当前 Python/Windows 环境。extra_argv 追加在脚本路径之后。"""
    argv = list(extra_argv or [])
    suffix = full.suffix.lower()
    if suffix == ".py":
        # 使用当前解释器，保证 conda/venv 环境一致
        return [sys.executable or "python", str(full), *argv]
    if suffix in (".sh", ".bash"):
        bash = shutil.which("bash")
        if not bash:
            raise RuntimeError("当前环境未找到 bash，无法执行 .sh/.bash 脚本。")
        return [bash, str(full), *argv]
    if suffix == ".ps1":
        pwsh = shutil.which("pwsh") or shutil.which("powershell")
        if not pwsh:
            raise RuntimeError("当前环境未找到 PowerShell，无法执行 .ps1 脚本。")
        return [pwsh, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(full), *argv]
    if suffix in (".cmd", ".bat"):
        comspec = os.environ.get("ComSpec") or "cmd.exe"
        return [comspec, "/c", str(full), *argv]
    raise RuntimeError(f"不支持的脚本后缀: {suffix}")


def _execute_script_subprocess(
    *,
    script_full_path: Path,
    script_path: str,
    skill_id: str,
    workspace_id: str,
    write_mode: str,
    input_json: str,
    cli_argv: list[str],
    script_root: Path,
    timeout_sec: int,
) -> dict[str, Any]:
    workspace_root = _get_workspace_root(workspace_id)
    workspace_root.mkdir(parents=True, exist_ok=True)
    try:
        cmd = _build_script_command(script_full_path, cli_argv)
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
    skill_home = (skills_dir / skill_id).resolve()
    script_root = (skill_home / "scripts").resolve()
    # 仅当该 skill 目录真实存在且含 SKILL.md 时才创建 scripts/，避免 stale skill_id（如改名后未更新的 DHA）生成空壳目录
    if (skill_home / "SKILL.md").is_file():
        script_root.mkdir(parents=True, exist_ok=True)

    @tool
    async def run_skill_script(script_path: str, input_json: str = "", cli_args_json: str = "") -> str:
        """执行当前技能 scripts 目录下的脚本。script_path 为相对该目录的文件名（如 kb_document_store_cli.py）；若误写成 scripts/xxx.py 会自动纠正。input_json 可选（stdin）；cli_args_json 可选（argv 数组 JSON）。支持 .py/.sh/.ps1/.cmd/.bat。"""
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
                    if "cli_args_json" in maybe_obj and not (cli_args_json or "").strip():
                        caj = maybe_obj["cli_args_json"]
                        cli_args_json = (
                            caj if isinstance(caj, str) else json.dumps(caj, ensure_ascii=False)
                        )
                else:
                    script_path = raw_script_param
            else:
                script_path = raw_script_param
        except Exception:
            script_path = raw_script_param

        script_path = _apply_script_path_normalization(script_path)

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
        script_path = _normalize_skill_script_path(script_path)
        full = (script_root / script_path).resolve()
        if not str(full).startswith(str(script_root)) or not full.is_file():
            hint = ""
            if not available_scripts:
                hint = (
                    f"当前绑定 skill_id={skill_id!r}，脚本目录为 {str(script_root)}。"
                    "若专家配置里仍有已改名/已删除的旧 skill_id，请只保留实际存在的目录名，"
                    f"脚本应放在该目录的 scripts/ 下。"
                )
            return _json_result(
                ok=False,
                code="script_not_found",
                message=f"脚本不存在或不在允许目录内: {script_path}" + (f" {hint}" if hint else ""),
                skill_id=skill_id,
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

        parsed_input, parse_error = _parse_input_json(input_json)
        if parse_error:
            return _json_result(ok=False, code="invalid_input_json", message=parse_error)
        cli_argv, cli_err = _parse_cli_args_json(cli_args_json)
        if cli_err:
            return _json_result(ok=False, code="invalid_cli_args_json", message=cli_err)
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
                cli_argv=cli_argv or [],
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
                payload={"script_path": script_path, "cli_argv": cli_argv or []},
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
        "script_path 填相对该 scripts 目录的路径（如 kb_document_store_cli.py）；"
        "若 SKILL.md 写 scripts/foo.py 而误带上 scripts/ 前缀，会自动剥掉。"
        "传参两种方式等价支持："
        "（1）input_json：整段作为进程 stdin，适合读 JSON 的脚本；"
        "（2）cli_args_json：JSON 数组字符串，每项为一段 argv，与在终端执行 python script.py --foo bar 一致，路径相对工作区根，"
        '例如 ["--input_text","你好"] 或 ["--query","问题"]。'
        "可只用其中一种，或按脚本需要同时使用。"
        "支持命令：__list__（列出脚本）、__manifest__（查看 manifest）、__describe__:<script>。"
        "技能说明或 scripts 中若要求「运行某脚本」时使用本工具。"
    )
    return run_skill_script
