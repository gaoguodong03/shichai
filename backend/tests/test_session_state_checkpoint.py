from __future__ import annotations

import asyncio
import json
import os
import tempfile
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

from app.api.group_chat_state import ACTIVE_GROUP_RUNS, save_group_history
from app.core.user_context import reset_current_user_identity, set_current_user_identity


@pytest.fixture(scope="module")
def _state_test_env():
    with tempfile.TemporaryDirectory() as d:
        old_root = os.environ.get("SHUTONG_USER_DATA_ROOT")
        old_anon = os.environ.get("ALLOW_ANONYMOUS_API")
        os.environ["SHUTONG_USER_DATA_ROOT"] = d
        os.environ["ALLOW_ANONYMOUS_API"] = "1"
        try:
            yield
        finally:
            if old_root is None:
                os.environ.pop("SHUTONG_USER_DATA_ROOT", None)
            else:
                os.environ["SHUTONG_USER_DATA_ROOT"] = old_root
            if old_anon is None:
                os.environ.pop("ALLOW_ANONYMOUS_API", None)
            else:
                os.environ["ALLOW_ANONYMOUS_API"] = old_anon


@pytest.fixture
def client(_state_test_env):
    from app.main import app

    return TestClient(app)


def _set_user():
    return set_current_user_identity(user_id="free4inno", username="free4inno")


def _user_msg(message_id: str, content: str, created_at: str = "2026062400000000") -> dict:
    return {
        "message_id": message_id,
        "speaker": {"type": "user"},
        "message": {"content": content},
        "created_at": created_at,
    }


def _expert_msg(message_id: str, content: str, created_at: str = "2026062400010000") -> dict:
    return {
        "message_id": message_id,
        "speaker": {"type": "expert", "agent_name": "agent-demo"},
        "message": {"content": content},
        "created_at": created_at,
    }


@contextmanager
def _session_running(session_id: str):
    loop = asyncio.new_event_loop()
    task = loop.create_task(asyncio.sleep(60))
    ACTIVE_GROUP_RUNS[session_id] = {"run_id": "run-test", "task": task, "phase": "executing"}
    try:
        yield
    finally:
        ACTIVE_GROUP_RUNS.pop(session_id, None)
        task.cancel()
        loop.run_until_complete(asyncio.gather(task, return_exceptions=True))
        loop.close()


def test_checkpoint_object_uses_contract_fields_without_secondary_markdown_snapshot(client: TestClient):
    create_resp = client.post("/api/sessions", json={"title": "检查点契约"})
    assert create_resp.status_code == 200
    session_id = create_resp.json()["data"]["id"]

    client.post(
        f"/api/workspaces/{session_id}/files",
        json={"filename": "note.txt", "content": "checkpoint"},
    )
    token = _set_user()
    try:
        save_group_history(session_id, [_user_msg("msg-1", "第一条")])
    finally:
        reset_current_user_identity(token)

    snapshot_resp = client.post(f"/api/sessions/{session_id}/snapshot")
    assert snapshot_resp.status_code == 200
    checkpoint = snapshot_resp.json()["data"]

    assert checkpoint["checkpoint_id"]
    assert checkpoint["parent_checkpoint_id"] is not None
    assert checkpoint["trigger"] == "manual_snapshot"
    assert checkpoint["session_blob"]
    assert checkpoint["history_blob"]
    assert "orchestration_state_blob" in checkpoint
    assert checkpoint["workspace_tree"]
    assert checkpoint["memory_tree"]
    assert checkpoint["last_message_id"] == "msg-1"
    assert "commit_id" not in checkpoint
    assert "id" not in checkpoint
    assert "parent" not in checkpoint
    assert "reason" not in checkpoint
    assert "chat_blob" not in checkpoint
    assert "session_definition" not in checkpoint
    assert "message_count" not in checkpoint

    from app.core.user_context import build_user_context

    user_ctx = build_user_context(user_id="free4inno", username="free4inno")
    assert not (user_ctx.sessions_dir / session_id / "chat.md").exists()


def test_checkpoint_session_blob_uses_only_session_contract_fields(client: TestClient):
    create_resp = client.post("/api/sessions", json={"title": "检查点会话字段"})
    assert create_resp.status_code == 200
    session_id = create_resp.json()["data"]["id"]

    from app.core.user_context import build_user_context

    user_ctx = build_user_context(user_id="free4inno", username="free4inno")
    session_path = user_ctx.sessions_dir / session_id / "session.json"
    polluted = json.loads(session_path.read_text(encoding="utf-8"))
    polluted.update(
        {
            "add_agent_names": ["临时专家"],
            "remove_agent_names": ["移除专家"],
            "runtime_state": {"running": True},
            "speaker_task": "旧任务",
            "instruction": "旧指令",
            "next_prompt": "旧提示",
        }
    )
    session_path.write_text(json.dumps(polluted, ensure_ascii=False, indent=2), encoding="utf-8")

    snapshot_resp = client.post(f"/api/sessions/{session_id}/snapshot")
    assert snapshot_resp.status_code == 200
    checkpoint = snapshot_resp.json()["data"]
    blob_path = user_ctx.sessions_dir / session_id / "checkpoints" / "objects" / "blobs" / checkpoint["session_blob"]
    session_blob = json.loads(blob_path.read_text(encoding="utf-8"))

    assert session_blob == {
        "title": "检查点会话字段",
        "title_auto_generated": False,
        "agent_names": [],
        "host": session_blob["host"],
        "created_at": session_blob["created_at"],
        "updated_at": session_blob["updated_at"],
    }


def test_clone_reuses_blob_objects(client: TestClient):
    create_resp = client.post("/api/sessions", json={"title": "blob复用"})
    assert create_resp.status_code == 200
    session_id = create_resp.json()["data"]["id"]

    client.post(
        f"/api/workspaces/{session_id}/files",
        json={"filename": "shared.txt", "content": "dedup-me"},
    )
    client.post(f"/api/sessions/{session_id}/snapshot")

    clone_resp = client.post(f"/api/sessions/{session_id}/clone")
    assert clone_resp.status_code == 200
    cloned_session_id = clone_resp.json()["data"]["session_id"]

    from app.core.user_context import build_user_context

    user_ctx = build_user_context(user_id="free4inno", username="free4inno")
    src_file = user_ctx.sessions_dir / session_id / "workspace" / "shared.txt"
    dst_file = user_ctx.sessions_dir / cloned_session_id / "workspace" / "shared.txt"
    assert src_file.exists() and dst_file.exists()

    src_store_root = user_ctx.sessions_dir / session_id / "checkpoints" / "objects" / "blobs"
    dst_store_root = user_ctx.sessions_dir / cloned_session_id / "checkpoints" / "objects" / "blobs"
    assert src_store_root.is_dir()
    assert dst_store_root.is_dir()
    assert not (user_ctx.base_dir / "blob").exists()
    assert not (user_ctx.base_dir / "trees").exists()

    # session 自包含：clone/fork 复制所需对象到目标 session，不跨 session 引用用户级对象库。
    src_matching = [p.name for p in src_store_root.iterdir() if p.is_file() and p.read_bytes() == b"dedup-me"]
    dst_matching = [p.name for p in dst_store_root.iterdir() if p.is_file() and p.read_bytes() == b"dedup-me"]
    assert len(src_matching) == 1
    assert dst_matching == src_matching


def test_session_layout_is_per_session_directory(client: TestClient):
    create_resp = client.post("/api/sessions", json={"title": "布局"})
    assert create_resp.status_code == 200
    session_id = create_resp.json()["data"]["id"]

    client.post(
        f"/api/workspaces/{session_id}/files",
        json={"filename": "note.txt", "content": "layout"},
    )

    from app.core.user_context import build_user_context

    user_ctx = build_user_context(user_id="free4inno", username="free4inno")
    session_root = user_ctx.sessions_dir / session_id
    assert (session_root / "workspace" / "note.txt").exists()
    assert (session_root / "checkpoints").is_dir()
    assert not (user_ctx.sessions_dir / "workspaces" / session_id).exists()


def test_clone_copies_workspace_and_chat_state(client: TestClient):
    create_resp = client.post("/api/sessions", json={"title": "克隆会话"})
    assert create_resp.status_code == 200
    session_id = create_resp.json()["data"]["id"]

    file_resp = client.post(
        f"/api/workspaces/{session_id}/files",
        json={"filename": "note.txt", "content": "hello clone"},
    )
    assert file_resp.status_code == 200

    token = _set_user()
    try:
        save_group_history(
            session_id,
            [_user_msg("msg-1", "先记录一条消息")],
        )
    finally:
        reset_current_user_identity(token)

    snapshot_resp = client.post(f"/api/sessions/{session_id}/snapshot")
    assert snapshot_resp.status_code == 200

    clone_resp = client.post(f"/api/sessions/{session_id}/clone")
    assert clone_resp.status_code == 200
    cloned_session_id = clone_resp.json()["data"]["session_id"]
    assert cloned_session_id != session_id

    detail_resp = client.get(f"/api/sessions/{cloned_session_id}")
    assert detail_resp.status_code == 200
    detail = detail_resp.json()["data"]
    assert detail["messages"][0]["message"]["content"] == "先记录一条消息"

    content_resp = client.get(
        f"/api/workspaces/{cloned_session_id}/files/content",
        params={"path": "note.txt"},
    )
    assert content_resp.status_code == 200
    assert content_resp.json()["data"]["content"] == "hello clone"

    snapshots_resp = client.get(f"/api/sessions/{cloned_session_id}/snapshots")
    assert snapshots_resp.status_code == 200
    checkpoints = snapshots_resp.json()["data"]["checkpoints"]
    assert len(checkpoints) == 1
    assert checkpoints[0]["trigger"] == "clone"


def test_clone_and_rollback_reject_running_session(client: TestClient):
    create_resp = client.post("/api/sessions", json={"title": "运行中禁止分叉回滚"})
    assert create_resp.status_code == 200
    session_id = create_resp.json()["data"]["id"]

    token = _set_user()
    try:
        save_group_history(session_id, [_user_msg("msg-1", "第一条")])
    finally:
        reset_current_user_identity(token)
    checkpoint_id = client.post(f"/api/sessions/{session_id}/snapshot").json()["data"]["checkpoint_id"]

    with _session_running(session_id):
        clone_resp = client.post(f"/api/sessions/{session_id}/clone")
        rollback_resp = client.post(
            f"/api/sessions/{session_id}/rollback",
            json={"checkpoint_id": checkpoint_id},
        )

    assert clone_resp.status_code == 409
    assert rollback_resp.status_code == 409


def test_snapshots_expose_contract_ids_and_last_message_id(client: TestClient):
    create_resp = client.post("/api/sessions", json={"title": "快照映射"})
    assert create_resp.status_code == 200
    session_id = create_resp.json()["data"]["id"]

    token = _set_user()
    try:
        save_group_history(
            session_id,
            [_user_msg("msg-1", "第一条")],
        )
        save_group_history(
            session_id,
            [_user_msg("msg-1", "第一条"), _expert_msg("msg-2", "第二条")],
        )
    finally:
        reset_current_user_identity(token)

    snapshots_resp = client.get(f"/api/sessions/{session_id}/snapshots")
    assert snapshots_resp.status_code == 200
    checkpoints = snapshots_resp.json()["data"]["checkpoints"]
    assert len(checkpoints) >= 2
    for checkpoint in checkpoints:
        assert checkpoint["checkpoint_id"]
        assert "id" not in checkpoint
        assert "message_count" not in checkpoint
        assert "message_ids" not in checkpoint
        assert "reason" not in checkpoint
    assert any(item.get("last_message_id") == "msg-1" for item in checkpoints)
    assert any(item.get("last_message_id") == "msg-2" for item in checkpoints)

    rollback_resp = client.post(
        f"/api/sessions/{session_id}/rollback",
        json={"message_id": "msg-1"},
    )
    assert rollback_resp.status_code == 200
    detail_resp = client.get(f"/api/sessions/{session_id}")
    messages = detail_resp.json()["data"]["messages"]
    assert len(messages) == 1
    assert messages[0]["message_id"] == "msg-1"


def test_rollback_rejects_legacy_message_count(client: TestClient):
    create_resp = client.post("/api/sessions", json={"title": "回溯优先级"})
    assert create_resp.status_code == 200
    session_id = create_resp.json()["data"]["id"]

    token = _set_user()
    try:
        save_group_history(
            session_id,
            [_user_msg("msg-1", "第一条")],
        )
        save_group_history(
            session_id,
            [_user_msg("msg-1", "第一条"), _expert_msg("msg-2", "第二条")],
        )
    finally:
        reset_current_user_identity(token)

    rollback_resp = client.post(
        f"/api/sessions/{session_id}/rollback",
        json={"message_count": 1},
    )
    assert rollback_resp.status_code == 422


def test_rollback_restores_previous_checkpoint_and_trims_later_state(client: TestClient):
    create_resp = client.post("/api/sessions", json={"title": "回溯会话"})
    assert create_resp.status_code == 200
    session_id = create_resp.json()["data"]["id"]

    client.put(
        f"/api/workspaces/{session_id}/files/content",
        params={"path": "draft.txt"},
        json={"content": "version-1"},
    )

    token = _set_user()
    try:
        save_group_history(
            session_id,
            [_user_msg("msg-1", "第一版")],
        )
    finally:
        reset_current_user_identity(token)

    cp1 = client.post(f"/api/sessions/{session_id}/snapshot").json()["data"]["checkpoint_id"]

    client.put(
        f"/api/workspaces/{session_id}/files/content",
        params={"path": "draft.txt"},
        json={"content": "version-2"},
    )

    token = _set_user()
    try:
        save_group_history(
            session_id,
            [_user_msg("msg-1", "第一版"), _expert_msg("msg-2", "第二版回复")],
        )
    finally:
        reset_current_user_identity(token)

    cp2 = client.post(f"/api/sessions/{session_id}/snapshot").json()["data"]["checkpoint_id"]
    assert cp2 != cp1

    rollback_resp = client.post(
        f"/api/sessions/{session_id}/rollback",
        json={"checkpoint_id": cp1},
    )
    assert rollback_resp.status_code == 200
    rollback_checkpoint_id = rollback_resp.json()["data"]["checkpoint_id"]
    assert rollback_resp.json()["data"]["source_checkpoint_id"] == cp1
    assert rollback_checkpoint_id not in {cp1, cp2}

    content_resp = client.get(
        f"/api/workspaces/{session_id}/files/content",
        params={"path": "draft.txt"},
    )
    assert content_resp.status_code == 200
    assert content_resp.json()["data"]["content"] == "version-1"

    detail_resp = client.get(f"/api/sessions/{session_id}")
    assert detail_resp.status_code == 200
    messages = detail_resp.json()["data"]["messages"]
    assert len(messages) == 1
    assert messages[0]["message"]["content"] == "第一版"

    snapshots_resp = client.get(f"/api/sessions/{session_id}/snapshots")
    checkpoints = snapshots_resp.json()["data"]["checkpoints"]
    checkpoint_ids = [item["checkpoint_id"] for item in checkpoints if isinstance(item, dict)]
    assert checkpoint_ids[-1] == rollback_checkpoint_id
    assert cp1 in checkpoint_ids
    assert cp2 in checkpoint_ids
    rollback_checkpoint = checkpoints[-1]
    assert rollback_checkpoint["trigger"] == "rollback"
    assert rollback_checkpoint["parent_checkpoint_id"] == cp2
