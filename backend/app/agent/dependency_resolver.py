"""Resolve skill dependency fingerprint for base image reuse."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple


@dataclass(frozen=True)
class DependencyFingerprint:
    dep_hash: str
    sources: List[str]
    normalized_payload: str


class DependencyResolver:
    """Build deterministic dependency hash from skill manifests."""

    def resolve_for_skill(self, skill_home: Path, *, runtime: str, os_arch: str) -> DependencyFingerprint:
        home = skill_home.resolve()
        candidates = [
            "requirements.txt",
            "requirements.lock",
            "pyproject.toml",
            "poetry.lock",
            "Pipfile.lock",
            "package-lock.json",
            "pnpm-lock.yaml",
            "yarn.lock",
        ]
        payload: Dict[str, str] = {}
        sources: List[str] = []
        for rel in candidates:
            p = home / rel
            if p.is_file():
                payload[rel] = p.read_text(encoding="utf-8")
                sources.append(rel)
        normalized = json.dumps(
            {
                "runtime": runtime,
                "os_arch": os_arch,
                "deps": {k: payload[k] for k in sorted(payload.keys())},
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        dep_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        return DependencyFingerprint(dep_hash=dep_hash, sources=sources, normalized_payload=normalized)

    def parse_runtime(self, policy_runtime: str, profile: str) -> Tuple[str, str]:
        runtime = (policy_runtime or "python3.11").strip().lower()
        os_arch = (profile or "linux/amd64").strip().lower()
        return runtime, os_arch
