import json
import sqlite3
import tempfile

import pytest  # type: ignore[import-not-found]
from fastapi.testclient import TestClient


@pytest.fixture
def env_and_client(monkeypatch, tmp_path):
    # 1) SQLite auth db 放在临时目录
    db_path = tmp_path / "auth_users.sqlite"
    monkeypatch.setenv("AUTH_DB_PATH", str(db_path))

    # 2) 用户 profile users.json 放在临时目录，避免污染仓库
    from app.core import users_store as _users_store

    monkeypatch.setattr(_users_store, "_USERS_FILE", tmp_path / "users.json")

    # 3) 用户数据根放在临时目录，验证多用户物理隔离
    monkeypatch.setenv("SHUTONG_USER_DATA_ROOT", str(tmp_path / "users"))

    # 重要：在 env 生效后再导入 app，避免模块初始化时读取旧 env
    from app.main import app

    client = TestClient(app)
    return client, db_path


def _auth_register(client: TestClient, username: str, password: str):
    r = client.post("/api/auth/register", json={"username": username, "password": password})
    assert r.status_code == 200
    j = r.json()
    assert j["status"] == "ok"
    return j["data"]


def _auth_login(client: TestClient, username: str, password: str):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200
    j = r.json()
    assert j["status"] == "ok"
    return j["data"]


def test_sqlite_register_login_and_password_not_plaintext(env_and_client):
    client, db_path = env_and_client

    username = "alice_sqlite"
    password = "pw-alice-123"

    _auth_register(client, username=username, password=password)
    data = _auth_login(client, username=username, password=password)
    assert data["username"] == username
    assert data["token_type"] == "bearer"
    assert isinstance(data["access_token"], str) and data["access_token"]

    # 验证 sqlite 中保存的是 hash，而非明文
    assert db_path.exists()
    conn = sqlite3.connect(str(db_path))
    cur = conn.execute("SELECT username, salt_b64, password_hash FROM users WHERE username = ?", (username,))
    row = cur.fetchone()
    conn.close()

    assert row is not None
    assert row[0] == username
    # 任意形式，至少不应等于明文密码
    assert row[2] != password


def test_multiuser_isolation_by_token_headers(env_and_client):
    client, _ = env_and_client

    ws_id = "ws-shared"

    alice = "alice_user"
    bob = "bob_user"
    pw_a = "pw-a"
    pw_b = "pw-b"

    _auth_register(client, username=alice, password=pw_a)
    token_a = _auth_login(client, username=alice, password=pw_a)["access_token"]

    _auth_register(client, username=bob, password=pw_b)
    token_b = _auth_login(client, username=bob, password=pw_b)["access_token"]

    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # Alice 在同一个 workspace_id 写入文件
    r = client.post(
        f"/api/workspaces/{ws_id}/files",
        headers=headers_a,
        json={"filename": "a.txt", "content": "content-from-alice"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "ok"

    # Bob 列出同一 workspace_id：应为空（物理隔离）
    r = client.get(f"/api/workspaces/{ws_id}/files", headers=headers_b)
    assert r.status_code == 200
    entries_b = r.json()["data"]["entries"]
    assert entries_b == []

    # Bob 再写入文件
    r = client.post(
        f"/api/workspaces/{ws_id}/files",
        headers=headers_b,
        json={"filename": "b.txt", "content": "content-from-bob"},
    )
    assert r.status_code == 200

    # Alice 再次列出：不应看到 Bob 的文件
    r = client.get(f"/api/workspaces/{ws_id}/files", headers=headers_a)
    assert r.status_code == 200
    entries_a = r.json()["data"]["entries"]
    names_a = sorted([e["name"] for e in entries_a])
    assert names_a == ["a.txt"]

