from __future__ import annotations

from pathlib import Path

from app.agent.dep_image_registry import DepImageRegistry
from app.agent.dependency_resolver import DependencyResolver


def test_dependency_hash_is_stable(tmp_path: Path):
    skill_home = tmp_path / "skill_a"
    skill_home.mkdir(parents=True, exist_ok=True)
    (skill_home / "requirements.txt").write_text("requests==2.32.0\npydantic==2.12.5\n", encoding="utf-8")

    resolver = DependencyResolver()
    fp1 = resolver.resolve_for_skill(skill_home, runtime="python3.11", os_arch="linux/amd64")
    fp2 = resolver.resolve_for_skill(skill_home, runtime="python3.11", os_arch="linux/amd64")
    assert fp1.dep_hash == fp2.dep_hash
    assert "requirements.txt" in fp1.sources


def test_dep_image_registry_reuses_same_hash():
    reg = DepImageRegistry()
    a = reg.ensure(dep_hash="abc", runtime_backend="docker", runtime_profile="standard")
    b = reg.ensure(dep_hash="abc", runtime_backend="docker", runtime_profile="standard")
    assert a.image_ref == b.image_ref
    assert reg.get("abc") is not None
