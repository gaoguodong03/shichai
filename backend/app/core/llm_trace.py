from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _default_trace_file() -> Path:
    # backend/app/core/llm_trace.py -> backend/logs/llm_trace.log
    backend_root = Path(__file__).resolve().parents[2]
    log_dir = backend_root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / "llm_trace.log"


def append_llm_trace(
    *,
    tag: str,
    system_content: str,
    user_content: str,
    model_output: str,
    extra: dict[str, Any] | None = None,
    max_chars: int = 12000,
) -> Path:
    """Append a human-readable LLM trace record into backend/logs/llm_trace.log."""

    def _clip(value: str) -> str:
        text = str(value or "")
        if len(text) <= max_chars:
            return text
        return text[:max_chars] + f"\n... [truncated {len(text) - max_chars} chars]"

    now = datetime.now(timezone.utc).isoformat()
    dst = _default_trace_file()

    lines = [
        f"===== LLM_TRACE {now} tag={tag} =====",
        "--- system_prompt ---",
        _clip(system_content),
        "--- user_prompt ---",
        _clip(user_content),
        "--- model_output ---",
        _clip(model_output),
    ]
    if extra:
        lines.append("--- extra ---")
        for k, v in extra.items():
            lines.append(f"{k}: {v}")
    lines.append("")

    with dst.open("a", encoding="utf-8") as f:
        f.write("\n".join(lines))
        f.write("\n")

    return dst
