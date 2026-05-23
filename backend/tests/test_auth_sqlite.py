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

    username = "alice_sqlite@example.com"
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


def test_register_creates_stable_user_id_and_returns_it(env_and_client):
    client, db_path = env_and_client

    username = "stable-id@example.com"
    data = _auth_register(client, username=username, password="pw-stable-123")

    assert data["username"] == username
    assert isinstance(data["user_id"], str)
    assert data["user_id"]
    assert "@" not in data["user_id"]

    conn = sqlite3.connect(str(db_path))
    row = conn.execute(
        "SELECT user_id, username FROM users WHERE username = ?",
        (username,),
    ).fetchone()
    conn.close()

    assert row == (data["user_id"], username)


def test_register_preserves_existing_local_session_presets(env_and_client):
    client, db_path = env_and_client

    username = "existing_local@example.com"
    user_root = db_path.parent / "users" / username
    preset_path = user_root / "config" / "session_presets.json"
    preset_path.parent.mkdir(parents=True, exist_ok=True)
    existing_presets = [{"id": "saved-scene", "name": "已保存场景"}]
    preset_path.write_text(json.dumps(existing_presets, ensure_ascii=False), encoding="utf-8")

    _auth_register(client, username=username, password="pw-existing-123")

    assert json.loads(preset_path.read_text(encoding="utf-8")) == existing_presets


def test_multiuser_isolation_by_token_headers(env_and_client):
    client, _ = env_and_client

    ws_id = "ws-shared"

    alice = "alice_user@example.com"
    bob = "bob_user@example.com"
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
    # 当前工作区会自动包含 memory 目录；只断言业务文件隔离正确
    assert "a.txt" in names_a
    assert "b.txt" not in names_a


def test_change_account_and_password(env_and_client):
    client, _ = env_and_client

    old_username = "18812345678"
    old_password = "old-pass-123"
    new_username = "new-user@example.com"
    new_password = "new-pass-456"

    _auth_register(client, username=old_username, password=old_password)
    login_data = _auth_login(client, username=old_username, password=old_password)
    token = login_data["access_token"]

    # 先写入一份用户数据，后续验证改账号后目录迁移生效
    ws_id = "ws-account-change"
    headers = {"Authorization": f"Bearer {token}"}
    r = client.post(
        f"/api/workspaces/{ws_id}/files",
        headers=headers,
        json={"filename": "keep.txt", "content": "before-rename"},
    )
    assert r.status_code == 200

    # 修改账号
    r = client.put(
        "/api/auth/account",
        headers=headers,
        json={"new_username": new_username, "current_password": old_password},
    )
    assert r.status_code == 200
    j = r.json()
    assert j["status"] == "ok"
    assert j["data"]["username"] == new_username
    token2 = j["data"]["access_token"]
    headers2 = {"Authorization": f"Bearer {token2}"}

    # 旧账号应不可登录，新账号可登录
    r = client.post("/api/auth/login", json={"username": old_username, "password": old_password})
    assert r.status_code == 401
    r = client.post("/api/auth/login", json={"username": new_username, "password": old_password})
    assert r.status_code == 200

    # 改账号后仍可访问之前工作区文件（说明用户目录已迁移）
    r = client.get(f"/api/workspaces/{ws_id}/files", headers=headers2)
    assert r.status_code == 200
    entries = r.json()["data"]["entries"]
    names = sorted([e["name"] for e in entries])
    # 当前工作区会自动包含 memory 目录；关注迁移后的业务文件仍可见
    assert "keep.txt" in names

    # 修改密码
    r = client.put(
        "/api/auth/password",
        headers=headers2,
        json={"current_password": old_password, "new_password": new_password},
    )
    assert r.status_code == 200
    j = r.json()
    assert j["status"] == "ok"

    # 旧密码失效，新密码可登录
    r = client.post("/api/auth/login", json={"username": new_username, "password": old_password})
    assert r.status_code == 401
    r = client.post("/api/auth/login", json={"username": new_username, "password": new_password})
    assert r.status_code == 200


def test_reject_invalid_account_format(env_and_client):
    client, _ = env_and_client
    invalid_username = "invalid_username"

    r = client.post("/api/auth/register", json={"username": invalid_username, "password": "pw-123456"})
    assert r.status_code == 400
    assert r.json()["detail"] == "账号格式不正确，请输入手机号或电子邮箱"

    r = client.post("/api/auth/login", json={"username": invalid_username, "password": "pw-123456"})
    assert r.status_code == 400
    assert r.json()["detail"] == "账号格式不正确，请输入手机号或电子邮箱"
