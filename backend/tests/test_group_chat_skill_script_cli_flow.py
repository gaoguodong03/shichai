from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage


class _SeqClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self._idx = 0

    def bind_tools(self, tools, *args, **kwargs):
        return self

    async def ainvoke(self, messages):
        if self._idx >= len(self._responses):
            return self._responses[-1]
        response = self._responses[self._idx]
        self._idx += 1
        return response


class _FakeLLM:
    def __init__(self, responses):
        self._client = _SeqClient(responses)

    def get_client(self):
        return self._client


class _FakeScriptGateway:
    def __init__(self):
        self.calls = []

    async def execute(self, *, tool_name, tool_kind, payload, context, runner):
        self.calls.append(
            {
                "tool_name": tool_name,
                "tool_kind": tool_kind,
                "payload": payload,
                "context": context,
            }
        )
        return SimpleNamespace(
            ok=True,
            output={
                "exit_code": 0,
                "stdout": "pendulum==3.0.0",
                "stderr": "",
            },
            elapsed_ms=12,
            error="",
            interrupt_reason=None,
        )


@pytest.fixture
def _frontend_flow_env(tmp_path, monkeypatch):
    user = "frontend-flow@example.test"
    monkeypatch.setenv("SHUTONG_USER_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("ALLOW_ANONYMOUS_API", "1")

    user_root = tmp_path / user
    config_dir = user_root / "config"
    skill_dir = user_root / "skills" / "sandbox-dependency-verify"
    scripts_dir = skill_dir / "scripts"
    config_dir.mkdir(parents=True, exist_ok=True)
    scripts_dir.mkdir(parents=True, exist_ok=True)

    (config_dir / "dha_instances.json").write_text(
        json.dumps(
            [
                {
                    "agent_id": "sandbox-dependency-expert",
                    "name": "沙箱依赖验证专家",
                    "role": "验证沙箱 Python 包依赖是否可用",
                    "system_prompt": "收到运行脚本请求时，使用 run_skill_script 调用指定脚本。",
                    "skill_ids": ["sandbox-dependency-verify"],
                    "mcp_server_ids": [],
                    "is_leader": False,
                    "llm_provider_id": "fake",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (skill_dir / "SKILL.md").write_text(
        """---
name: 沙箱依赖验证
description: 运行 check_pkg_version.py 检查包版本。
---
当用户要求运行脚本并传参时，调用 run_skill_script，传入 script_path 和 cli_args_json。
""",
        encoding="utf-8",
    )
    (scripts_dir / "check_pkg_version.py").write_text(
        """import argparse

parser = argparse.ArgumentParser()
parser.add_argument('--package', required=True)
args = parser.parse_args()
print(f'{args.package}==3.0.0')
""",
        encoding="utf-8",
    )

    from app.skills.loader import invalidate_skills_cache_for_user

    invalidate_skills_cache_for_user(user)
    yield user
    invalidate_skills_cache_for_user(user)


def test_frontend_at_mention_runs_skill_script_with_cli_args(_frontend_flow_env, monkeypatch):
    from app.api import group_chat
    from app.main import app
    from app.tools import run_skill_script

    user = _frontend_flow_env
    fake_gateway = _FakeScriptGateway()
    fake_llm = _FakeLLM(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "call-check-pkg",
                        "name": "run_skill_script",
                        "args": {
                            "script_path": "check_pkg_version.py",
                            "cli_args_json": '["--package","pendulum"]',
                        },
                    }
                ],
            ),
            AIMessage(content="pendulum 版本检查通过。"),
        ]
    )

    monkeypatch.setattr(group_chat, "_get_llm_for_dha", lambda dha, app_settings: fake_llm)
    monkeypatch.setattr(run_skill_script, "_SCRIPT_GATEWAY", fake_gateway)

    client = TestClient(app)
    headers = {"X-User-Name": user}
    create_resp = client.post(
        "/api/sessions",
        json={
            "title": "固定测试标题",
            "agent_ids": ["sandbox-dependency-expert"],
        },
        headers=headers,
    )
    assert create_resp.status_code == 200
    session_id = create_resp.json()["data"]["id"]

    chat_resp = client.post(
        f"/api/sessions/{session_id}/chat",
        json={
            "message": "@沙箱依赖验证专家 运行脚本并传参：\n\nscript_path: check_pkg_version.py\ncli_args_json: [\"--package\",\"pendulum\"]"
        },
        headers=headers,
    )
    assert chat_resp.status_code == 200
    data = chat_resp.json()["data"]
    assistant_msg = data["message"]

    assert data["route"]["agent_id"] == "agent-sandbox-dependency-expert"
    assert assistant_msg["agent_id"] == "agent-sandbox-dependency-expert"
    assert assistant_msg["skill_id"] == "sandbox-dependency-verify"
    assert "版本检查通过" in assistant_msg["content"]
    assert fake_gateway.calls

    call = fake_gateway.calls[0]
    assert call["tool_kind"] == "script"
    assert call["payload"]["script_path"] == "check_pkg_version.py"
    assert call["payload"]["cli_argv"] == ["--package", "pendulum"]
    assert call["tool_name"].startswith("run_skill_script_")

    raw_results = assistant_msg.get("tool_raw_results") or []
    assert raw_results
    assert "pendulum==3.0.0" in raw_results[0]
