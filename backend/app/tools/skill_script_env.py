"""Environment builders for Skill script execution."""
from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_SANDBOX_ENV_PASSTHROUGH_KEYS = (
    "PLAYWRIGHT_BROWSERS_PATH",
)
_DEFAULT_PLAYWRIGHT_BROWSERS_PATH = "/ms-playwright"


def subprocess_base_env() -> dict[str, str]:
    """Return the minimal host env needed to start local script subprocesses."""
    inherited_names = (
        "PATH",
        "HOME",
        "TMPDIR",
        "TEMP",
        "TMP",
        "LANG",
        "LC_ALL",
        "SSL_CERT_FILE",
        "REQUESTS_CA_BUNDLE",
        "NODE_EXTRA_CA_CERTS",
    )
    env = {
        key: str(os.environ[key])
        for key in inherited_names
        if os.environ.get(key)
    }
    pythonpath = str(_BACKEND_ROOT)
    if os.environ.get("PYTHONPATH"):
        pythonpath += os.pathsep + os.environ["PYTHONPATH"]
    env["PYTHONPATH"] = pythonpath
    return env


def collect_sandbox_passthrough_env() -> dict[str, str]:
    """Return non-secret runtime env values that every script sandbox may receive."""
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
