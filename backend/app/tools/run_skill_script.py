"""执行 Skill 目录下 scripts/ 中的脚本，作为一等步骤能力。"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import os
import shlex
import subprocess
import json
import re
import shutil
import sys
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

logger = logging.getLogger(__name__)

_ALLOWED_SCRIPT_SUFFIX = {".py", ".sh", ".bash", ".ps1", ".cmd", ".bat"}
# 命令行参数上限（防滥用）；单段长度上限（兼顾长文本与 --input_text）
_CLI_ARGV_MAX_ITEMS = 64
_CLI_ARGV_MAX_STRLEN = 32_768
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
_EFFECTIVELY_UNLIMITED_SCRIPT_TIMEOUT_SEC = 24 * 60 * 60


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
    """用于组装工具列表：仅当磁盘上存在该 skill 目录且含 SKILL.md 时才注册 run_skill_script，避免 Agent 里陈旧 directory_name 指向空壳目录。"""
    sid = (directory_name or "").strip()
    if not sid:
        return False
    try:
        home = (_get_skills_dir() / sid).resolve()
        return (home / "SKILL.md").is_file()
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
    """从 manifest 中按脚本相对路径精确读取配置。"""
    meta = manifest.get(script_path)
    return meta if isinstance(meta, dict) else {}


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
        recovered = _recover_concatenated_cli_args_json(raw) or _recover_embedded_cli_args_json(raw)
        if recovered is None:
            return None, f"cli_args_json 不是合法 JSON: {e}"
        data = recovered
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


def _recover_concatenated_cli_args_json(raw: str) -> list[Any] | None:
    """容错 LLM 把多个 JSON 字符串/数组片段拼到 cli_args_json 的常见错误。"""
    decoder = json.JSONDecoder()
    pos = 0
    parts: list[Any] = []
    length = len(raw)
    try:
        while pos < length:
            while pos < length and raw[pos].isspace():
                pos += 1
            if pos >= length:
                break
            value, end = decoder.raw_decode(raw, pos)
            parts.append(value)
            pos = end
    except Exception:
        return None
    if len(parts) <= 1:
        return None
    out: list[Any] = []
    for part in parts:
        if isinstance(part, list):
            out.extend(part)
        elif isinstance(part, str):
            out.append(part)
        else:
            return None
    return out


def _recover_embedded_cli_args_json(raw: str) -> list[Any] | None:
    """容错从混入说明文字的 cli_args_json 中提取第一个 JSON 数组。"""
    decoder = json.JSONDecoder()
    for pos, ch in enumerate(raw):
        if ch != "[":
            continue
        try:
            value, _end = decoder.raw_decode(raw, pos)
        except Exception:
            continue
        if isinstance(value, list):
            return value
    try:
        value = json.loads(f"[{raw}]")
    except Exception:
        return None
    return value if isinstance(value, list) else None


def _normalize_cli_field_name(name: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(name or "").strip().lower()).strip("_")


def _cli_required_missing(required: list[Any], cli_argv: list[str]) -> list[Any]:
    normalized_required = [_normalize_cli_field_name(item) for item in required]
    named_values: dict[str, str] = {}
    positionals: list[str] = []
    i = 0
    while i < len(cli_argv):
        item = str(cli_argv[i] or "")
        if item.startswith("--") and len(item) > 2:
            flag, sep, inline_value = item[2:].partition("=")
            key = _normalize_cli_field_name(flag)
            if sep:
                named_values[key] = inline_value
            elif i + 1 < len(cli_argv) and not str(cli_argv[i + 1]).startswith("-"):
                named_values[key] = str(cli_argv[i + 1])
                i += 1
            else:
                named_values[key] = "true"
        elif not item.startswith("-"):
            positionals.append(item)
        i += 1

    missing: list[Any] = []
    positional_index = 0
    for original, normalized in zip(required, normalized_required):
        named_value = named_values.get(normalized)
        if named_value is not None and str(named_value).strip():
            continue
        if positional_index < len(positionals) and str(positionals[positional_index]).strip():
            positional_index += 1
            continue
        missing.append(original)
    return missing


def _validate_against_manifest(
    script_path: str,
    script_meta: dict[str, Any],
    parsed_input: Any,
    cli_argv: list[str] | None = None,
) -> str | None:
    """按 manifest.input_schema 做最小校验（仅 required）。"""
    schema = script_meta.get("input_schema")
    if not isinstance(schema, dict):
        return None
    required = schema.get("required")
    if not isinstance(required, list) or not required:
        return None
    if cli_argv is not None:
        missing = _cli_required_missing(required, cli_argv)
        if missing:
            return f"脚本 {script_path} 缺少必填字段: {missing}"
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


def _build_sandbox_script_command(
    script_path: str,
    suffix: str,
    extra_argv: list[str] | None = None,
) -> list[str]:
    """构造在沙箱内执行脚本的命令（不依赖宿主机解释器路径）。"""
    argv = list(extra_argv or [])
    quoted_argv = " ".join(shlex.quote(a) for a in argv)
    script_choice = f'echo {shlex.quote(script_path)}'
    if suffix == ".py":
        # 兼容最小镜像：优先 python3，回退 python
        write_requirements = (
            "import base64, os, pathlib; "
            "raw=os.environ.get('SKILL_REQUIREMENTS_B64',''); "
            "expected=os.environ.get('SKILL_REQUIREMENTS_HASH','').strip(); "
            "path=pathlib.Path('/tmp/requirements.txt'); "
            "path.write_bytes(base64.b64decode(raw.encode('ascii'))) if raw else None; "
            "size=path.stat().st_size if path.exists() else 0; "
            "print('skill_python_requirements_bytes='+str(size), file=__import__('sys').stderr); "
            "print('skill_python_requirements_hash='+expected, file=__import__('sys').stderr) if expected else None; "
            "print('skill_python_requirements_env_missing expected_hash='+expected, file=__import__('sys').stderr) if expected and not raw else None"
        )
        preflight = (
            "import importlib, importlib.metadata as md, pathlib, re, sys; "
            "req=pathlib.Path('/tmp/requirements.txt'); "
            "import_names={'xlrd':['xlrd'],'pandas':['pandas'],'openpyxl':['openpyxl']}; "
            "min_versions={'xlrd':(2,0,1)}; ok=True; names=[]; "
            "\nif req.exists():\n"
            "    for raw in req.read_text(encoding='utf-8').splitlines():\n"
            "        line=raw.strip()\n"
            "        if not line or line.startswith('#') or line.startswith(('-', 'git+', 'http:', 'https:')): continue\n"
            "        name=line.split(';',1)[0].split('[',1)[0].strip()\n"
            "        name=re.split(r'===|==|>=|<=|~=|!=|>|<', name, 1)[0].strip().lower()\n"
            "        if name and name not in names: names.append(name)\n"
            "    for name in names:\n"
            "        try:\n"
            "            version=md.version(name)\n"
            "            for mod in import_names.get(name, []): importlib.import_module(mod)\n"
            "            minimum=min_versions.get(name)\n"
            "            if minimum:\n"
            "                parsed=tuple(int(x) for x in re.findall(r'\\d+', version)[:3])\n"
            "                if parsed < minimum:\n"
            "                    print(f'skill_python_preflight version_too_low {name}=={version} < {minimum[0]}.{minimum[1]}.{minimum[2]}', file=sys.stderr); ok=False\n"
            "        except Exception as exc:\n"
            "            print(f'skill_python_preflight missing_or_broken {name}: {exc}', file=sys.stderr); ok=False\n"
            "sys.exit(0 if ok else 42)\n"
        )
        probe = (
            "import importlib, importlib.metadata as md, pathlib, re, sys; "
            "req=pathlib.Path('/tmp/requirements.txt'); mods=[]; "
            "\nif req.exists():\n"
            "    for raw in req.read_text(encoding='utf-8').splitlines():\n"
            "        line=raw.strip()\n"
            "        if not line or line.startswith('#') or line.startswith(('-', 'git+', 'http:', 'https:')): continue\n"
            "        name=line.split(';',1)[0].split('[',1)[0].strip()\n"
            "        name=re.split(r'===|==|>=|<=|~=|!=|>|<', name, 1)[0].strip().lower()\n"
            "        if name in {'pandas','xlrd','openpyxl'} and name not in mods: mods.append(name)\n"
            "print('skill_python_probe executable='+sys.executable, file=sys.stderr)\n"
            "for m in mods:\n"
            "    try:\n"
            "        importlib.import_module(m); print('skill_python_probe '+m+'='+md.version(m)+' import=ok', file=sys.stderr)\n"
            "    except Exception as exc:\n"
            "        print('skill_python_probe '+m+' import=failed '+str(exc), file=sys.stderr)\n"
        )
        return [
            "sh",
            "-lc",
            f'set -e; SCRIPT_PATH="$({script_choice})"; '
            f'if command -v python3 >/dev/null 2>&1; then '
            f'python3 -c {shlex.quote(write_requirements)}; '
            f'python3 -c {shlex.quote(preflight)} || {{ if [ -s /tmp/requirements.txt ]; then python3 -m pip install --disable-pip-version-check --no-input --upgrade -r /tmp/requirements.txt; else echo "skill_python_preflight empty /tmp/requirements.txt" 1>&2; exit 42; fi; }}; '
            f'python3 -c {shlex.quote(preflight)}; '
            f'python3 -c {shlex.quote(probe)} || true; exec python3 "$SCRIPT_PATH" {quoted_argv}; '
            f'elif command -v python >/dev/null 2>&1; then '
            f'python -c {shlex.quote(write_requirements)}; '
            f'python -c {shlex.quote(preflight)} || {{ if [ -s /tmp/requirements.txt ]; then python -m pip install --disable-pip-version-check --no-input --upgrade -r /tmp/requirements.txt; else echo "skill_python_preflight empty /tmp/requirements.txt" 1>&2; exit 42; fi; }}; '
            f'python -c {shlex.quote(preflight)}; '
            f'python -c {shlex.quote(probe)} || true; exec python "$SCRIPT_PATH" {quoted_argv}; '
            f'else echo "python runtime not found" 1>&2; exit 127; fi',
        ]
    if suffix in (".sh", ".bash"):
        return ["sh", "-lc", f'SCRIPT_PATH="$({script_choice})"; exec bash "$SCRIPT_PATH" {quoted_argv}']
    if suffix == ".ps1":
        return [
            "sh",
            "-lc",
            f'SCRIPT_PATH="$({script_choice})"; exec pwsh -NoProfile -ExecutionPolicy Bypass -File "$SCRIPT_PATH" {quoted_argv}',
        ]
    if suffix in (".cmd", ".bat"):
        return ["sh", "-lc", f'SCRIPT_PATH="$({script_choice})"; exec cmd.exe /c "$SCRIPT_PATH" {quoted_argv}']
    raise RuntimeError(f"不支持的脚本后缀: {suffix}")


def _build_sandbox_exec_request(
    *,
    directory_name: str,
    workspace_id: str,
    script_path: str,
    suffix: str,
    cli_argv: list[str],
    input_json: str,
) -> tuple[list[str], dict[str, str], str]:
    """
    返回 (command, env, cwd)：
    - command 统一走 sh -lc，先确保会话目录存在并 cd
    - input_json 通过环境变量注入并管道到 stdin
    """
    sandbox_workspace_dir = sandbox_session_dir(workspace_id)
    skill_home = f"{SANDBOX_SKILLS_ROOT}/{directory_name}"
    sandbox_script_path = f"{skill_home}/scripts/{script_path.lstrip('/')}"
    base_argv = _build_sandbox_script_command(
        sandbox_script_path,
        suffix,
        cli_argv,
    )
    quoted = " ".join(shlex.quote(str(x)) for x in base_argv)
    env: dict[str, str] = {}
    if input_json:
        shell_cmd = f'mkdir -p {shlex.quote(sandbox_workspace_dir)} && cd {shlex.quote(sandbox_workspace_dir)} && printf "%s" {shlex.quote(input_json)} | {quoted}'
    else:
        shell_cmd = f'mkdir -p {shlex.quote(sandbox_workspace_dir)} && cd {shlex.quote(sandbox_workspace_dir)} && {quoted}'
    return ["sh", "-lc", shell_cmd], env, "/workspace"


def _inline_shell_env(command: list[str], env: dict[str, str]) -> list[str]:
    """Inline critical env vars because some OpenSandbox command envs are not propagated."""
    if len(command) < 3 or command[0] != "sh" or command[1] != "-lc":
        return command
    exports = []
    for key, value in env.items():
        if not key or not key.replace("_", "").isalnum():
            continue
        exports.append(f"{key}={shlex.quote(str(value))}; export {key};")
    if not exports:
        return command
    return [command[0], command[1], " ".join(exports) + " " + command[2]]


def _resolve_script_timeout_sec(script_meta: dict[str, Any]) -> int:
    raw = script_meta.get("timeout_sec")
    if raw is None or raw == "":
        raw = os.getenv("SKILL_SCRIPT_TIMEOUT", "60")
    try:
        timeout_sec = int(raw)
    except (TypeError, ValueError):
        timeout_sec = 60
    if timeout_sec <= 0:
        return int(os.getenv("SKILL_SCRIPT_UNLIMITED_TIMEOUT_SEC", str(_EFFECTIVELY_UNLIMITED_SCRIPT_TIMEOUT_SEC)))
    return timeout_sec


def _execute_script_subprocess(
    *,
    script_full_path: Path,
    script_path: str,
    directory_name: str,
    workspace_id: str,
    write_mode: str,
    input_json: str,
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
            input=input_json if input_json else None,
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
    脚本可在 SKILL.md 或 scripts 中被描述，由 LLM 在需要时调用。
    """
    skills_dir = _get_skills_dir()
    owner_user_id = _get_current_user_id()
    skill_home = (skills_dir / directory_name).resolve()
    script_root = (skill_home / "scripts").resolve()
    # 仅当该 skill 目录真实存在且含 SKILL.md 时才新建 scripts/，避免 stale directory_name（如改名后未更新的 Agent）生成空壳目录
    if (skill_home / "SKILL.md").is_file():
        script_root.mkdir(parents=True, exist_ok=True)

    async def run_skill_script(script_path: str, input_json: str = "", cli_args_json: str = "") -> str:
        """执行当前技能 scripts 目录下的脚本。script_path 为相对该目录的文件名（如 kb_document_store_cli.py）；若误写成 scripts/xxx.py 会自动纠正。仅支持 cli_args_json（argv 数组 JSON）。支持 .py/.sh/.ps1/.cmd/.bat。"""
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
        if (input_json or "").strip():
            return _json_result(
                ok=False,
                code="invalid_input_mode",
                message=(
                    "run_skill_script 已统一为 CLI-only：不再支持 input_json/stdin。"
                    "请改用 cli_args_json（JSON 数组字符串）传参。"
                ),
            )
        workspace_root = _get_workspace_root(workspace_id)
        workspace_root.mkdir(parents=True, exist_ok=True)
        available_scripts = _list_available_scripts(script_root)
        manifest = _load_manifest(script_root)

        # 兼容 LLM 把整个 JSON 对象字符串塞进 script_path 的情况，例如：
        # script_path='{"script_path": "hello_agent.py", "input_json": ""}'
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

        parsed_input, parse_error = _parse_input_json(input_json)
        if parse_error:
            return _json_result(ok=False, code="invalid_input_json", message=parse_error)
        cli_argv, cli_err = _parse_cli_args_json(cli_args_json)
        if cli_err:
            return _json_result(ok=False, code="invalid_cli_args_json", message=cli_err)
        script_meta = _script_meta_for(manifest, script_path)
        schema_error = _validate_against_manifest(script_path, script_meta, parsed_input, cli_argv)
        if schema_error:
            return _json_result(ok=False, code="manifest_validation_failed", message=schema_error, meta=script_meta)

        timeout_sec = _resolve_script_timeout_sec(script_meta)

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
                input_json=input_json,
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

    available_scripts = _list_available_scripts(script_root)
    manifest = _load_manifest(script_root)
    if available_scripts:
        script_descriptions = []
        for script_name in available_scripts:
            meta = _script_meta_for(manifest, script_name)
            desc = str(meta.get("description") or "").strip()
            script_descriptions.append(f"{script_name}: {desc}" if desc else script_name)
        script_inventory = "当前可用脚本：" + "；".join(script_descriptions) + "。"
    else:
        script_inventory = "当前没有可用脚本；可先用 __list__ 确认可执行脚本。"

    return ToolSpec.from_function(
        name="run_skill_script",
        description=(
            "执行当前技能 scripts/ 下脚本。script_path 填相对路径；"
            "cli_args_json 填 JSON 数组字符串，如 [\"--query\",\"问题\"]。"
            "不要使用 input_json/stdin；可用 __list__/__manifest__/__describe__:<script> 查看脚本。"
            f"{script_inventory}"
        ),
        coroutine=run_skill_script,
        args_schema={
            "type": "object",
            "properties": {
                "script_path": {
                    "type": "string",
                    "description": "scripts/ 下的相对脚本路径，或 __list__/__manifest__/__describe__:<script>。",
                },
                "input_json": {
                    "type": "string",
                    "description": "已废弃；不要使用，统一改用 cli_args_json。",
                    "default": "",
                },
                "cli_args_json": {
                    "type": "string",
                    "description": "命令行 argv 数组 JSON 字符串，如 [\"--query\", \"用户原话\"]。",
                    "default": "",
                },
            },
            "required": ["script_path"],
        },
    )
