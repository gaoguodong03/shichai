"""Skill script command and sandbox request builders.

This module owns command construction for local script execution and OpenSandbox
requests. It does not parse manifests, execute tools, or inspect user resources.
"""
from __future__ import annotations

import os
import shlex
import shutil
import sys
from pathlib import Path
from typing import Any

from app.agent.sandbox_mount_policy import SANDBOX_SKILLS_ROOT
from app.agent.session_workspace_policy import sandbox_session_dir

EFFECTIVELY_UNLIMITED_SCRIPT_TIMEOUT_SEC = 24 * 60 * 60


def build_script_command(full: Path, extra_argv: list[str] | None = None) -> list[str]:
    """Build a local command for a script path and suffix."""
    argv = list(extra_argv or [])
    suffix = full.suffix.lower()
    if suffix == ".py":
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


def build_sandbox_exec_request(
    *,
    directory_name: str,
    workspace_id: str,
    script_path: str,
    suffix: str,
    cli_argv: list[str],
) -> tuple[list[str], dict[str, str], str]:
    """Build the command/env/cwd tuple sent to OpenSandbox."""
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
    shell_cmd = f'mkdir -p {shlex.quote(sandbox_workspace_dir)} && cd {shlex.quote(sandbox_workspace_dir)} && {quoted}'
    return ["sh", "-lc", shell_cmd], env, "/workspace"


def inline_shell_env(command: list[str], env: dict[str, str]) -> list[str]:
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


def resolve_script_timeout_sec(script_meta: dict[str, Any]) -> int:
    """Resolve script timeout from manifest metadata and environment defaults."""
    raw = script_meta.get("timeout_sec")
    if raw is None or raw == "":
        raw = os.getenv("SKILL_SCRIPT_TIMEOUT", "60")
    try:
        timeout_sec = int(raw)
    except (TypeError, ValueError):
        timeout_sec = 60
    if timeout_sec <= 0:
        return int(os.getenv("SKILL_SCRIPT_UNLIMITED_TIMEOUT_SEC", str(EFFECTIVELY_UNLIMITED_SCRIPT_TIMEOUT_SEC)))
    return timeout_sec


def _build_sandbox_script_command(
    script_path: str,
    suffix: str,
    extra_argv: list[str] | None = None,
) -> list[str]:
    """Build the command that runs a script inside the sandbox."""
    argv = list(extra_argv or [])
    quoted_argv = " ".join(shlex.quote(a) for a in argv)
    script_choice = f'echo {shlex.quote(script_path)}'
    if suffix == ".py":
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
