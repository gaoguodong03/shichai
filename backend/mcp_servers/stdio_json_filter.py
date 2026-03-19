"""
stdin/stdout JSON-RPC 过滤包装器：

某些 MCP server（尤其通过 npx 拉起）会把 npm 安装/告警的文本打印到 stdout，
但 MCP stdio 协议要求 stdout 必须是逐行的 JSONRPC 消息。

此包装器会：
1) 启动子进程（例如 npx ...）
2) 逐行读取子进程 stdout
3) 能被 json.loads 解析的行按原样转发到当前 stdout
4) 其它文本行转发到当前 stderr（不污染 JSONRPC）
"""

from __future__ import annotations

import json
import subprocess
import sys


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: stdio_json_filter.py <command> [args...]", file=sys.stderr)
        return 2

    cmd = sys.argv[1:]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=sys.stderr,
        text=True,
        bufsize=1,
    )

    assert proc.stdout is not None
    try:
        for line in proc.stdout:
            s = (line or "").rstrip("\n")
            if not s.strip():
                # 空行直接忽略（避免额外行导致 JSONRPC 解析报错）
                continue
            try:
                json.loads(s)
            except Exception:
                # npm warn / install log 等非 JSON 行，丢到 stderr
                print(s, file=sys.stderr)
                continue
            print(s, flush=True)
    finally:
        try:
            proc.stdout.close()  # type: ignore[union-attr]
        except Exception:
            pass

    return proc.wait()


if __name__ == "__main__":
    raise SystemExit(main())

