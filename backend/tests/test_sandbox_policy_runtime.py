from app.agent import sandbox_policy_runtime as policy


def test_network_allowed_for_tool_matches_run_skill_script_prefix(monkeypatch):
    monkeypatch.setenv("SANDBOX_NETWORK_TOOL_ALLOWLIST", "run_skill_script")
    monkeypatch.setenv("SANDBOX_ALLOW_NETWORK", "0")

    assert policy.network_allowed_for_tool("run_skill_script_demo") is True
    assert policy.network_allowed_for_tool("read_file") is False


def test_network_allowed_for_tool_allows_global_when_no_allowlist(monkeypatch):
    monkeypatch.delenv("SANDBOX_NETWORK_TOOL_ALLOWLIST", raising=False)
    monkeypatch.setenv("SANDBOX_ALLOW_NETWORK", "1")

    assert policy.network_allowed_for_tool("any_tool") is True


def test_sandbox_default_environment_uses_playwright_browsers_path(monkeypatch):
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", "/custom-browsers")

    assert policy.sandbox_default_environment() == {"PLAYWRIGHT_BROWSERS_PATH": "/custom-browsers"}
