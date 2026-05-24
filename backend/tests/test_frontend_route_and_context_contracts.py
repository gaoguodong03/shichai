from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_router_exposes_canonical_business_routes():
    src = read("frontend/src/router/index.ts")
    assert "path: '/workspace'" in src
    assert "path: '/resources/:section?'" in src
    assert "path: '/settings/:section?'" in src
    assert "'agent'" in src
    assert "/resources/dha" not in src


def test_main_view_uses_route_as_navigation_source():
    src = read("frontend/src/views/MainView.vue")
    assert "const currentModule = computed<ModuleId>" in src
    assert "router.push(resourceRoutePath(id))" in src
    assert "router.push(settingsRoutePath(" in src
    assert "type ResourceSubModule = 'scenario' | 'agent' | 'skill' | 'mcp' | 'llm' | 'files'" in src
