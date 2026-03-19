#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class Result:
    server_id: str
    name: str
    enabled: bool
    transport_type: str
    ok: bool
    tool_count: int | None = None
    reason: str | None = None


def _subst_env(val: str) -> str:
    return re.sub(r"\$\{(\w+)\}", lambda m: os.environ.get(m.group(1), ""), str(val))

def _load_dotenv(dotenv_path: Path) -> None:
    """极简 .env 解析器：支持 KEY=VALUE（VALUE 可包含空格，不做 shell 执行）。"""
    if not dotenv_path.exists():
        return
    for raw in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip()
        # 去掉包裹引号
        if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
            v = v[1:-1]
        if k and k not in os.environ:
            os.environ[k] = v


def _find_missing_env_placeholders(config: dict[str, Any]) -> list[str]:
    missing: set[str] = set()

    def walk(x: Any):
        if isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
        elif isinstance(x, str):
            for m in re.finditer(r"\$\{(\w+)\}", x):
                key = m.group(1)
                if not os.environ.get(key):
                    missing.add(key)

    walk(config)
    return sorted(missing)


async def _verify_one(cfg: dict[str, Any], timeout_s: float = 20.0) -> Result:
    # ensure backend root on sys.path so "app" can be imported
    backend_root = Path(__file__).resolve().parents[1]
    if str(backend_root) not in sys.path:
        sys.path.insert(0, str(backend_root))
    from app.mcp.manager import MCPToolManager

    server_id = str(cfg.get("id") or "")
    name = str(cfg.get("name") or server_id)
    enabled = bool(cfg.get("enabled", True))
    transport = cfg.get("transport") or {}
    transport_type = str(transport.get("type") or "stdio")

    missing_env = _find_missing_env_placeholders(cfg)
    if missing_env:
        return Result(
            server_id=server_id,
            name=name,
            enabled=enabled,
            transport_type=transport_type,
            ok=False,
            tool_count=None,
            reason=f"缺少环境变量: {', '.join(missing_env)}",
        )

    # 给验证单次连接更短的 session initialize 超时
    cfg = dict(cfg)
    md = dict(cfg.get("metadata") or {})
    md.setdefault("session_init_timeout_sec", min(8.0, timeout_s))
    cfg["metadata"] = md

    mgr = MCPToolManager()
    try:
        ok = await asyncio.wait_for(mgr.connect_server(server_id, cfg), timeout=timeout_s)
        if not ok:
            return Result(server_id, name, enabled, transport_type, False, None, "connect_server 返回 False")
        tools = [t for t in mgr.get_tools() if getattr(t, "name", "").startswith(server_id + "_")]
        return Result(server_id, name, enabled, transport_type, True, len(tools), None)
    except asyncio.TimeoutError:
        return Result(server_id, name, enabled, transport_type, False, None, f"超时（>{timeout_s}s）")
    except Exception as e:
        return Result(server_id, name, enabled, transport_type, False, None, f"{type(e).__name__}: {e}")
    finally:
        try:
            await mgr.cleanup()
        except Exception:
            pass


async def main() -> int:
    root = Path(__file__).resolve().parents[1]
    _load_dotenv(root / ".env")
    cfg_path = root / "config" / "mcp_servers.json"
    if not cfg_path.exists():
        print(f"config not found: {cfg_path}", file=sys.stderr)
        return 2
    cfgs = json.loads(cfg_path.read_text(encoding="utf-8"))
    if not isinstance(cfgs, list):
        print("invalid config: expected list", file=sys.stderr)
        return 2

    timeout_s = float(os.getenv("MCP_VERIFY_TIMEOUT", "20"))
    results: list[Result] = []
    for cfg in cfgs:
        if not isinstance(cfg, dict):
            continue
        try:
            r = await _verify_one(cfg, timeout_s=timeout_s)
        except BaseException as e:
            r = Result(
                server_id=str(cfg.get("id") or ""),
                name=str(cfg.get("name") or cfg.get("id") or ""),
                enabled=bool(cfg.get("enabled", True)),
                transport_type=str((cfg.get("transport") or {}).get("type") or "unknown"),
                ok=False,
                tool_count=None,
                reason=f"{type(e).__name__}: {e}",
            )
        results.append(r)

    # pretty output
    headers = ["id", "enabled", "transport", "ok", "tools", "reason"]
    rows = []
    for r in results:
        rows.append(
            [
                r.server_id,
                "Y" if r.enabled else "N",
                r.transport_type,
                "Y" if r.ok else "N",
                "" if r.tool_count is None else str(r.tool_count),
                r.reason or "",
            ]
        )

    colw = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            colw[i] = max(colw[i], len(cell))

    def fmt(row: list[str]) -> str:
        return " | ".join(cell.ljust(colw[i]) for i, cell in enumerate(row))

    print(fmt(headers))
    print("-+-".join("-" * w for w in colw))
    for row in rows:
        print(fmt(row))

    failed = [r for r in results if not r.ok]
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

