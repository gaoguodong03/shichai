"""Real installed-package verification for user sandbox requirements."""
from __future__ import annotations

import logging
import shlex
import time
from typing import Any

from app.agent.sandbox_adapter import SandboxHandle, SandboxPolicy
from app.agent.sandbox_policy_runtime import sandbox_default_environment as _sandbox_default_environment
from app.agent.sandbox_requirements_runtime import (
    command_exit_code,
    command_output,
    tail,
)

logger = logging.getLogger(__name__)

REQUIREMENTS_REAL_VERIFIED_AT_KEY = "requirements_real_verified_at"


def build_requirements_verify_command(normalized_requirements: str) -> list[str]:
    quoted_requirements = shlex.quote((normalized_requirements or "").strip())
    return [
        "sh",
        "-lc",
        (
            f"set -e; SANDBOX_REQUIREMENTS_TEXT={quoted_requirements}; export SANDBOX_REQUIREMENTS_TEXT; "
            "python3 - <<'PY'\n"
            "import importlib, importlib.metadata as md, os, re, sys\n"
            "from packaging.requirements import InvalidRequirement, Requirement\n"
            "from packaging.version import InvalidVersion, Version\n"
            "raw=os.environ.get('SANDBOX_REQUIREMENTS_TEXT','')\n"
            "if not raw.strip():\n"
            "    raise SystemExit('requirements verify received empty requirements text')\n"
            "print('requirements_verify_start')\n"
            "import_names={'xlrd':['xlrd'], 'openpyxl':['openpyxl'], 'pandas':['pandas']}\n"
            "min_versions={'xlrd':'2.0.1'}\n"
            "missing=[]\n"
            "version_too_low=[]\n"
            "version_mismatch=[]\n"
            "import_missing=[]\n"
            "seen=[]\n"
            "for raw_line in raw.splitlines():\n"
            "    line=raw_line.strip()\n"
            "    if not line or line.startswith('#') or line.startswith(('-', '--')) or '://' in line or line.startswith(('git+', 'http:')):\n"
            "        continue\n"
            "    try:\n"
            "        req=Requirement(line)\n"
            "        name=req.name\n"
            "        specifier=req.specifier\n"
            "    except InvalidRequirement:\n"
            "        name=line.split(';',1)[0].split('[',1)[0].strip()\n"
            "        name=re.split(r'===|==|>=|<=|~=|!=|>|<', name, 1)[0].strip()\n"
            "        specifier=None\n"
            "    if not name:\n"
            "        continue\n"
            "    try:\n"
            "        version=md.version(name)\n"
            "        seen.append(f'{name}=={version}')\n"
            "        if specifier:\n"
            "            try:\n"
            "                if Version(version) not in specifier:\n"
            "                    version_mismatch.append(f'{name}=={version} not in {specifier}')\n"
            "            except InvalidVersion:\n"
            "                version_mismatch.append(f'{name}=={version} invalid version for {specifier}')\n"
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
            "if version_mismatch:\n"
            "    raise SystemExit('packages installed but specifier mismatch: ' + '; '.join(version_mismatch))\n"
            "if import_missing:\n"
            "    raise SystemExit('packages installed but import failed: ' + '; '.join(import_missing))\n"
            "PY"
        ),
    ]


async def verify_installed_user_requirements(
    adapter: Any,
    handle: SandboxHandle,
    *,
    user_id: str,
    policy: SandboxPolicy,
    normalized_requirements: str,
    dep_hash: str,
) -> bool:
    normalized = (normalized_requirements or "").strip()
    if not normalized:
        return True
    if not hasattr(adapter, "exec_command"):
        logger.warning(
            "st49_sandbox_requirements_verify_failed code=adapter_no_exec_command user_id=%s dep_hash=%s sandbox_id=%s",
            user_id,
            dep_hash,
            str((handle.metadata or {}).get("sandbox_id") or ""),
        )
        return False
    try:
        verify_result = await adapter.exec_command(
            handle,
            build_requirements_verify_command(normalized),
            cwd="/",
            timeout_ms=min(max(30_000, int(policy.timeout_ms or 120_000)), 120_000),
            env={**_sandbox_default_environment(), "SANDBOX_REQUIREMENTS_TEXT": normalized},
        )
        exit_code = command_exit_code(verify_result)
        stdout, stderr = command_output(verify_result)
        if isinstance(exit_code, int) and exit_code == 0:
            if isinstance(handle.metadata, dict):
                handle.metadata[REQUIREMENTS_REAL_VERIFIED_AT_KEY] = time.time()
            logger.info(
                "st49_sandbox_requirements_verify_done code=requirements_real_verify_done user_id=%s dep_hash=%s sandbox_id=%s stdout_tail=%r stderr_tail=%r",
                user_id,
                dep_hash,
                str((handle.metadata or {}).get("sandbox_id") or ""),
                tail(stdout, 2000),
                tail(stderr, 2000),
            )
            return True
        logger.warning(
            "st49_sandbox_requirements_verify_failed code=requirements_real_verify_nonzero user_id=%s dep_hash=%s exit_code=%s sandbox_id=%s stdout_tail=%r stderr_tail=%r",
            user_id,
            dep_hash,
            exit_code,
            str((handle.metadata or {}).get("sandbox_id") or ""),
            tail(stdout),
            tail(stderr),
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
