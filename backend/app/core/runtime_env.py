"""运行时环境变量加载与默认值。"""
import os
from pathlib import Path

from dotenv import load_dotenv

from app.agent.sandbox_image_policy import default_playwright_image, default_standard_image


def load_runtime_env() -> None:
    """加载 backend/.env 与当前工作目录 .env。"""
    env_path = Path(__file__).resolve().parent.parent.parent / ".env"
    load_dotenv(env_path)
    load_dotenv()


def apply_runtime_env_defaults() -> None:
    """填充本地/默认部署所需环境变量；显式环境变量与 .env 优先。"""
    default_sandbox_image = default_standard_image()
    defaults = {
        "OPENSANDBOX_DOMAIN": "127.0.0.1:8091",
        "OPENSANDBOX_PROTOCOL": "http",
        "OPENSANDBOX_USE_SERVER_PROXY": "0",
        "OPENSANDBOX_REQUEST_TIMEOUT_SEC": "900",
        "UNIFIED_TOOL_GATEWAY_ENABLED": "1",
        "SANDBOX_BASE_IMAGE": default_sandbox_image,
        "SANDBOX_STANDARD_IMAGE": default_sandbox_image,
        "SANDBOX_PLAYWRIGHT_IMAGE": default_playwright_image(),
        "PLAYWRIGHT_BROWSERS_PATH": "/ms-playwright",
        "SANDBOX_FIXED_MEMORY_MB": "2048",
        "SANDBOX_ALLOW_NETWORK": "0",
        "SANDBOX_NETWORK_TOOL_ALLOWLIST": "run_skill_script",
        "SKILL_SCRIPT_TIMEOUT": "600",
        "SANDBOX_SCRIPT_GATEWAY_SLACK_MS": "600000",
    }
    for key, value in defaults.items():
        os.environ.setdefault(key, value)


def prepare_runtime_env() -> None:
    """加载环境文件并应用运行时默认值。"""
    load_runtime_env()
    apply_runtime_env_defaults()


def is_truthy_env(name: str, default: str = "1") -> bool:
    return (os.getenv(name, default) or "").strip().lower() in {"1", "true", "yes", "on"}
