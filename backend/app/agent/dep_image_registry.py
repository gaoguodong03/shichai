"""Dependency hash to base image registry mapping."""
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Dict, Optional


@dataclass(frozen=True)
class DepImageRecord:
    dep_hash: str
    image_ref: str
    runtime_backend: str
    runtime_profile: str


class DepImageRegistry:
    """In-memory registry; replace with DB/Redis in production."""

    def __init__(self):
        self._lock = threading.Lock()
        self._store: Dict[str, DepImageRecord] = {}

    def get(self, dep_hash: str) -> Optional[DepImageRecord]:
        with self._lock:
            return self._store.get(dep_hash)

    def ensure(self, *, dep_hash: str, runtime_backend: str, runtime_profile: str, default_repo: str = "shichai/skill-base") -> DepImageRecord:
        with self._lock:
            existing = self._store.get(dep_hash)
            if existing:
                return existing
            image_ref = f"{default_repo}:{dep_hash[:16]}"
            record = DepImageRecord(
                dep_hash=dep_hash,
                image_ref=image_ref,
                runtime_backend=runtime_backend,
                runtime_profile=runtime_profile,
            )
            self._store[dep_hash] = record
            return record
