from __future__ import annotations

import os
import tempfile

import pytest
from fastapi.testclient import TestClient

from app.api.group_chat_state import save_group_history
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
            [
                {
                    "message_id": "msg-1",
                    "role": "user",
                    "content": "先记录一条消息",
                    "timestamp": "2026-06-24T00:00:00Z",
                }
            ],
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
    assert detail["messages"][0]["content"] == "先记录一条消息"

    content_resp = client.get(
        f"/api/workspaces/{cloned_session_id}/files/content",
        params={"path": "note.txt"},
    )
    assert content_resp.status_code == 200
    assert content_resp.json()["data"]["content"] == "hello clone"

    snapshots_resp = client.get(f"/api/sessions/{cloned_session_id}/snapshots")
    assert snapshots_resp.status_code == 200
    assert len(snapshots_resp.json()["data"]["checkpoints"]) == 1


def test_snapshots_expose_message_count_and_last_message_id(client: TestClient):
    create_resp = client.post("/api/sessions", json={"title": "快照映射"})
    assert create_resp.status_code == 200
    session_id = create_resp.json()["data"]["id"]

    token = _set_user()
    try:
        save_group_history(
            session_id,
            [
                {
                    "message_id": "msg-1",
                    "role": "user",
                    "content": "第一条",
                    "timestamp": "2026-06-24T00:00:00Z",
                }
            ],
        )
        save_group_history(
            session_id,
            [
                {
                    "message_id": "msg-1",
                    "role": "user",
                    "content": "第一条",
                    "timestamp": "2026-06-24T00:00:00Z",
                },
                {
                    "message_id": "msg-2",
                    "role": "assistant",
                    "agent_id": "agent-demo",
                    "content": "第二条",
                    "timestamp": "2026-06-24T00:01:00Z",
                },
            ],
        )
    finally:
        reset_current_user_identity(token)

    snapshots_resp = client.get(f"/api/sessions/{session_id}/snapshots")
    assert snapshots_resp.status_code == 200
    checkpoints = snapshots_resp.json()["data"]["checkpoints"]
    assert len(checkpoints) >= 2
    counts = [int(item["message_count"]) for item in checkpoints if isinstance(item, dict)]
    assert 1 in counts and 2 in counts
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


def test_rollback_prefers_message_id_over_stale_checkpoint_id(client: TestClient):
    create_resp = client.post("/api/sessions", json={"title": "回溯优先级"})
    assert create_resp.status_code == 200
    session_id = create_resp.json()["data"]["id"]

    token = _set_user()
    try:
        save_group_history(
            session_id,
            [
                {
                    "message_id": "msg-1",
                    "role": "user",
                    "content": "第一条",
                    "timestamp": "2026-06-24T00:00:00Z",
                }
            ],
        )
        save_group_history(
            session_id,
            [
                {
                    "message_id": "msg-1",
                    "role": "user",
                    "content": "第一条",
                    "timestamp": "2026-06-24T00:00:00Z",
                },
                {
                    "message_id": "msg-2",
                    "role": "assistant",
                    "agent_id": "agent-demo",
                    "content": "第二条",
                    "timestamp": "2026-06-24T00:01:00Z",
                },
            ],
        )
    finally:
        reset_current_user_identity(token)

    snapshots = client.get(f"/api/sessions/{session_id}/snapshots").json()["data"]["checkpoints"]
    latest_checkpoint_id = snapshots[-1]["id"]

    rollback_resp = client.post(
        f"/api/sessions/{session_id}/rollback",
        json={"message_id": "msg-1", "checkpoint_id": latest_checkpoint_id},
    )
    assert rollback_resp.status_code == 200

    detail_resp = client.get(f"/api/sessions/{session_id}")
    messages = detail_resp.json()["data"]["messages"]
    assert len(messages) == 1
    assert messages[0]["message_id"] == "msg-1"


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
            [
                {
                    "message_id": "msg-1",
                    "role": "user",
                    "content": "第一版",
                    "timestamp": "2026-06-24T00:00:00Z",
                }
            ],
        )
    finally:
        reset_current_user_identity(token)

    cp1 = client.post(f"/api/sessions/{session_id}/snapshot").json()["data"]["commit_id"]

    client.put(
        f"/api/workspaces/{session_id}/files/content",
        params={"path": "draft.txt"},
        json={"content": "version-2"},
    )

    token = _set_user()
    try:
        save_group_history(
            session_id,
            [
                {
                    "message_id": "msg-1",
                    "role": "user",
                    "content": "第一版",
                    "timestamp": "2026-06-24T00:00:00Z",
                },
                {
                    "message_id": "msg-2",
                    "role": "assistant",
                    "agent_id": "agent-demo",
                    "content": "第二版回复",
                    "timestamp": "2026-06-24T00:01:00Z",
                },
            ],
        )
    finally:
        reset_current_user_identity(token)

    cp2 = client.post(f"/api/sessions/{session_id}/snapshot").json()["data"]["commit_id"]
    assert cp2 != cp1

    rollback_resp = client.post(
        f"/api/sessions/{session_id}/rollback",
        json={"checkpoint_id": cp1},
    )
    assert rollback_resp.status_code == 200

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
    assert messages[0]["content"] == "第一版"

    snapshots_resp = client.get(f"/api/sessions/{session_id}/snapshots")
    checkpoints = snapshots_resp.json()["data"]["checkpoints"]
    checkpoint_ids = [item["id"] for item in checkpoints if isinstance(item, dict)]
    assert checkpoint_ids[-1] == cp1
    assert cp2 not in checkpoint_ids
