"""Canonical path allowlist checks for session-scoped workspace isolation."""
from __future__ import annotations

from pathlib import Path
from typing import Iterable


def _as_path(value: str | Path) -> Path:
    return value if isinstance(value, Path) else Path(value)


def normalize_rel_path(path: str) -> str:
    p = (path or "").replace("\\", "/").strip()
    while p.startswith("./"):
        p = p[2:]
    return p.lstrip("/")


def ensure_within_root(path: str | Path, root: str | Path) -> Path:
    rp = _as_path(path).resolve()
    rr = _as_path(root).resolve()
    if rp != rr and rr not in rp.parents:
        raise ValueError(f"path out of root: {rp}")
    return rp


def ensure_within_any_root(path: str | Path, roots: Iterable[str | Path]) -> Path:
    rp = _as_path(path).resolve()
    for one in roots:
        rr = _as_path(one).resolve()
        if rp == rr or rr in rp.parents:
            return rp
    raise ValueError(f"path out of allowlist: {rp}")
