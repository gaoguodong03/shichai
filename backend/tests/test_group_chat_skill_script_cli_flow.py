from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from app.agent.messages import AIMessage


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
    def __init__(self, *, write_workspace_file: bool = False):
        self.calls = []
        self.write_workspace_file = write_workspace_file

    async def execute(self, *, tool_name, tool_kind, payload, context, runner):
        self.calls.append(
            {
                "tool_name": tool_name,
                "tool_kind": tool_kind,
                "payload": payload,
                "context": context,
            }
        )
        if self.write_workspace_file:
            from pathlib import Path

            workspace_root = Path(str(context.workspace_id))
            workspace_root.mkdir(parents=True, exist_ok=True)
            (workspace_root / "script-output.md").write_text("script output", encoding="utf-8")
        return SimpleNamespace(
            ok=True,
            output={
                "exit_code": 0,
                "stdout": json.dumps(
                    {
                        "execution_status": "succeeded",
                        "content": "pendulum==3.0.0",
                        "artifacts": [],
                        "next_action": {"agent_turn": "respond", "skill_session": "release"},
                    },
                    ensure_ascii=False,
                ),
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
    settings_dir = user_root / "settings"
    agent_dir = user_root / "resources" / "agents" / "沙箱依赖验证专家"
    skill_dir = user_root / "resources" / "skills" / "sandbox-dependency-verify"
    scripts_dir = skill_dir / "scripts"
    settings_dir.mkdir(parents=True, exist_ok=True)
    scripts_dir.mkdir(parents=True, exist_ok=True)
    agent_dir.mkdir(parents=True, exist_ok=True)
    (settings_dir / "sandbox").mkdir(parents=True, exist_ok=True)
    (settings_dir / "sandbox" / "requirements.txt").write_text("pendulum==3.0.0\n", encoding="utf-8")

    (agent_dir / "agent.json").write_text(
        json.dumps(
            {
                "name": "沙箱依赖验证专家",
                "description": "验证沙箱 Python 包依赖是否可用",
                "system_prompt": "收到运行脚本请求时，使用 run_skill_script 调用当前技能脚本。",
                "skills": [{"name": "沙箱依赖验证", "directory_name": "sandbox-dependency-verify"}],
                "llm_name": "fake",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (skill_dir / "SKILL.md").write_text(
        """---
name: 沙箱依赖验证
description: 运行 check_pkg_version.py 检查包版本。
---
当用户要求运行脚本并传参时，调用 run_skill_script，并只传入 manifest 中声明的 package 参数。
""",
        encoding="utf-8",
    )
    (scripts_dir / "check_pkg_version.py").write_text(
        """import argparse

parser = argparse.ArgumentParser()
parser.add_argument('--package', required=True)
args = parser.parse_args()
import json
print(json.dumps({
    "execution_status": "succeeded",
    "content": f"{args.package}==3.0.0",
    "artifacts": [],
    "next_action": {"agent_turn": "respond", "skill_session": "release"},
}, ensure_ascii=False))
""",
        encoding="utf-8",
    )
    (scripts_dir / "manifest.json").write_text(
        json.dumps(
            {
                "entry": "check_pkg_version.py",
                "description": "检查 Python 包版本。",
                "args": [{"name": "package", "description": "Python 包名。", "required": True}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    from app.skills.loader import invalidate_skills_cache_for_user

    invalidate_skills_cache_for_user(user)
    yield user
    invalidate_skills_cache_for_user(user)


def test_frontend_at_mention_runs_manifest_skill_script(_frontend_flow_env, monkeypatch):
    from app.agent import group_chat_runtime as group_chat
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
                        "name": "run_skill_script_sandbox-dependency-verify",
                        "args": {"package": "pendulum"},
                    }
                ],
            ),
            AIMessage(content="pendulum 版本检查通过。"),
        ]
    )

    from app.agent import group_chat_expert_resolution as expert_resolution

    monkeypatch.setattr(group_chat, "_get_llm_for_agent", lambda agent_profile, app_settings: fake_llm)
    monkeypatch.setattr(expert_resolution, "_llm_credential_notice_for_agent", lambda agent_profile, app_settings: None)
    monkeypatch.setattr(run_skill_script, "_SCRIPT_GATEWAY", fake_gateway)

    client = TestClient(app)
    headers = {"X-User-Name": user}
    create_resp = client.post(
        "/api/sessions",
        json={
            "title": "固定测试标题",
            "agent_names": ["沙箱依赖验证专家"],
        },
        headers=headers,
    )
    assert create_resp.status_code == 200
    session_id = create_resp.json()["data"]["id"]

    chat_resp = client.post(
        f"/api/sessions/{session_id}/chat",
        json={
            "message": "运行脚本检查 pendulum 这个 Python 包版本。",
            "client_message_id": "script-flow-1",
            "target_agent_name": "沙箱依赖验证专家",
        },
        headers=headers,
    )
    assert chat_resp.status_code == 200
    data = chat_resp.json()["data"]
    assistant_msg = data["message"]

    assert data["route"]["agent_name"] == "沙箱依赖验证专家"
    assert assistant_msg["speaker"]["agent_name"] == "沙箱依赖验证专家"
    assert assistant_msg["speaker"]["skill"] == "sandbox-dependency-verify"
    assert assistant_msg["message"]["content"] == "pendulum==3.0.0"
    assert fake_gateway.calls

    call = fake_gateway.calls[0]
    assert call["tool_kind"] == "script"
    assert call["payload"]["script_path"] == "check_pkg_version.py"
    assert call["payload"]["cli_argv"] == ["--package", "pendulum"]
    assert call["tool_name"].startswith("run_skill_script_")
    assert call["context"].user_id == user
    assert call["payload"]["__sandbox_env"]["SKILL_REQUIREMENTS_B64"]

    snapshots_resp = client.get(f"/api/sessions/{session_id}/snapshots", headers=headers)
    assert snapshots_resp.status_code == 200
    triggers = [item["trigger"] for item in snapshots_resp.json()["data"]["checkpoints"]]
    assert "workspace_changed" not in triggers


def test_skill_script_workspace_write_creates_workspace_changed_checkpoint(_frontend_flow_env, monkeypatch):
    """脚本工具写入 workspace 后，必须形成可回滚的 workspace_changed 检查点。"""
    from app.agent import group_chat_runtime as group_chat
    from app.main import app
    from app.tools import run_skill_script

    user = _frontend_flow_env
    fake_gateway = _FakeScriptGateway(write_workspace_file=True)
    fake_llm = _FakeLLM(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "call-check-pkg",
                        "name": "run_skill_script_sandbox-dependency-verify",
                        "args": {"package": "pendulum"},
                    }
                ],
            ),
            AIMessage(content="pendulum 版本检查通过。"),
        ]
    )

    from app.agent import group_chat_expert_resolution as expert_resolution

    monkeypatch.setattr(group_chat, "_get_llm_for_agent", lambda agent_profile, app_settings: fake_llm)
    monkeypatch.setattr(expert_resolution, "_llm_credential_notice_for_agent", lambda agent_profile, app_settings: None)
    monkeypatch.setattr(run_skill_script, "_SCRIPT_GATEWAY", fake_gateway)

    client = TestClient(app)
    headers = {"X-User-Name": user}
    create_resp = client.post(
        "/api/sessions",
        json={
            "title": "脚本写入检查点",
            "agent_names": ["沙箱依赖验证专家"],
        },
        headers=headers,
    )
    assert create_resp.status_code == 200
    session_id = create_resp.json()["data"]["id"]

    chat_resp = client.post(
        f"/api/sessions/{session_id}/chat",
        json={
            "message": "运行脚本检查 pendulum 这个 Python 包版本。",
            "client_message_id": "script-checkpoint-1",
            "target_agent_name": "沙箱依赖验证专家",
        },
        headers=headers,
    )

    assert chat_resp.status_code == 200
    snapshots_resp = client.get(f"/api/sessions/{session_id}/snapshots", headers=headers)
    assert snapshots_resp.status_code == 200
    triggers = [item["trigger"] for item in snapshots_resp.json()["data"]["checkpoints"]]
    assert "workspace_changed" in triggers
