"""Host-side workspace filesystem helpers for sandbox sessions."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from app.agent.path_whitelist_guard import ensure_within_root, normalize_rel_path
from app.agent.session_workspace_policy import sandbox_session_dir


def workspace_host_file(*, workspace_path: Path, rel_path: str) -> tuple[str, Path]:
    session_rel = normalize_rel_path(rel_path)
    target = ensure_within_root(workspace_path / session_rel, workspace_path)
    return session_rel, target


def read_workspace_text_on_host(*, workspace_path: Path, rel_path: str) -> str:
    session_rel, target = workspace_host_file(workspace_path=workspace_path, rel_path=rel_path)
    if not target.exists() or target.is_dir():
        raise FileNotFoundError(session_rel)
    return target.read_bytes().decode("utf-8")


def write_workspace_text_on_host(*, workspace_path: Path, rel_path: str, content: str) -> tuple[str, int]:
    session_rel, target = workspace_host_file(workspace_path=workspace_path, rel_path=rel_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    data = str(content or "").encode("utf-8")
    target.write_bytes(data)
    return session_rel, len(data)


def mkdir_workspace_on_host(*, workspace_path: Path, rel_path: str) -> str:
    session_rel, target = workspace_host_file(workspace_path=workspace_path, rel_path=rel_path)
    target.mkdir(parents=True, exist_ok=True)
    return session_rel


def list_workspace_files_on_host(
    *,
    workspace_path: Path,
    session_id: str,
    rel_prefix: str = "",
) -> list[dict[str, Any]]:
    root_rel, root = workspace_host_file(workspace_path=workspace_path, rel_path=rel_prefix)
    if not root.exists():
        return []
    files = [root] if root.is_file() else sorted([p for p in root.rglob("*") if p.is_file()])
    session_root = sandbox_session_dir(session_id).rstrip("/")
    out: list[dict[str, Any]] = []
    for p in files:
        rel = str(p.relative_to(workspace_path)).replace("\\", "/")
        out.append(
            {
                "path": f"{session_root}/{rel}",
                "name": p.name,
                "size": p.stat().st_size,
                "is_dir": False,
                "task_id": f"{session_root}/{root_rel}".rstrip("/"),
            }
        )
    return out


def workspace_rel_from_shell_arg(*, session_id: str, raw_path: str) -> str:
    raw = str(raw_path or "").strip().replace("\\", "/")
    session_root = sandbox_session_dir(session_id).rstrip("/")
    if raw == session_root:
        return ""
    if raw.startswith(session_root + "/"):
        return normalize_rel_path(raw[len(session_root) + 1 :])
    if raw.startswith("/workspace/"):
        raise ValueError("路径不在当前工作区")
    return normalize_rel_path(raw)


def exec_workspace_shell_on_host(
    *,
    session_id: str,
    workspace_path: Path,
    argv: List[str],
) -> Dict[str, Any] | None:
    args = [str(x) for x in (argv or [])]
    if len(args) >= 3 and args[0] == "mkdir" and args[1] == "-p":
        rel = workspace_rel_from_shell_arg(session_id=session_id, raw_path=args[2])
        mkdir_workspace_on_host(workspace_path=workspace_path, rel_path=rel)
        return {"exit_code": 0, "stdout": "", "stderr": "", "complete": True}
    if len(args) == 3 and args[0] == "mv":
        src_rel = workspace_rel_from_shell_arg(session_id=session_id, raw_path=args[1])
        dst_rel = workspace_rel_from_shell_arg(session_id=session_id, raw_path=args[2])
        _src_rel, src = workspace_host_file(workspace_path=workspace_path, rel_path=src_rel)
        _dst_rel, dst = workspace_host_file(workspace_path=workspace_path, rel_path=dst_rel)
        if not src.exists():
            raise FileNotFoundError(src_rel)
        dst.parent.mkdir(parents=True, exist_ok=True)
        src.rename(dst)
        return {"exit_code": 0, "stdout": "", "stderr": "", "complete": True}
    return None
