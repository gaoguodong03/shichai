# 用户资源存储 Phase A 实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 先建立以 `user_id` 为目录主键的新用户资源根、原子 JSON 写入工具和资源路径 facade，为后续迁移场景、专家、Skill、工具、模型和会话存储打基础。

**架构：** Phase A 只做基础设施和注册登录路径，不批量搬迁业务资源。HTTP 响应继续保留 `username`，新增 `user_id`；后端磁盘主路径切到 `backend/data/users/<user_id>/`，不在主路径查找旧邮箱目录。后续 Phase B/C 再把现有 `config/session_presets.json`、`config/dha_instances.json`、`skills/`、`config/mcp_servers.json` 和模型/密钥配置逐类迁到 `resources/` 与 `vault/`。

**技术栈：** FastAPI、标准库 `sqlite3`、`pathlib`、JSON 文件存储、pytest。

---

## 总体风险拆分

Phase A：身份和路径基础。改动集中在认证、用户上下文、路径 helper 和测试，不改资源中心 API 主行为。

Phase B：场景与专家资源目录化。让 `/settings/session-presets` 和 `/dha` 的兼容响应来自 `resources/scenarios`、`resources/agents`。

Phase C：Skill 目录迁移。把 loader、Skill CRUD、bundle 导入导出和沙箱 `/skills` 挂载切到 `resources/skills`。

Phase D：工具、模型、密钥分层。把 MCP、模型 provider、API key 分别迁到 `resources/tools`、`resources/models`、`vault/secrets.enc.json`，导出链路只带 `secret_ref`。

Phase E：会话目录标准化。把群聊历史、事件、runtime_state、workspace 收敛进 `sessions/<session_id>/`，保留资源快照引用。

Phase F：一次性迁移脚本。读取旧邮箱目录，生成 `user_id` 目录和迁移报告；主请求路径不做旧目录兼容。

## Phase A 文件结构

- 修改：`backend/app/core/auth_db.py`
  - 职责：SQLite 用户表增加稳定 `user_id`，并提供按登录名解析用户记录的 API。
- 修改：`backend/app/core/security.py`
  - 职责：token 解析后把 `username` 和 `user_id` 都放入请求上下文，兼容旧响应。
- 修改：`backend/app/core/user_context.py`
  - 职责：`UserContext.base_dir` 改为 `users/<user_id>`，暴露 `resources_dir`、`vault_dir`、`sessions_dir` 等标准路径。
- 修改：`backend/app/core/user_settings_paths.py`
  - 职责：新增标准资源路径 helper；旧 helper 暂保留给 Phase B/C 过渡。
- 新建：`backend/app/core/atomic_json.py`
  - 职责：提供 `atomic_write_text`、`atomic_write_json`、`read_json_or_default`，资源写入统一复用。
- 修改：`backend/app/api/auth.py`
  - 职责：注册新建新目录结构，登录返回 `user_id`，改账号只更新登录名，不重命名 `user_id` 目录。
- 修改：`backend/tests/test_auth_sqlite.py`
  - 职责：覆盖 `user_id` 目录、登录兼容、改账号不搬资源目录。
- 新建：`backend/tests/test_user_resource_paths.py`
  - 职责：覆盖标准路径 helper、原子 JSON 写入、旧邮箱目录不进入主路径。

## 任务 1：认证库增加 user_id

**文件：**
- 修改：`backend/app/core/auth_db.py`
- 测试：`backend/tests/test_auth_sqlite.py`

- [x] **步骤 1：编写失败的测试**

在 `backend/tests/test_auth_sqlite.py` 中新增：

```python
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
```

- [x] **步骤 2：运行测试验证失败**

运行：

```bash
/Users/ggd/.local/bin/rtk conda run -n st49 bash -lc 'cd backend && python -m pytest -q tests/test_auth_sqlite.py::test_register_creates_stable_user_id_and_returns_it'
```

预期：FAIL，响应 `data` 中没有 `user_id`，或 SQLite `users` 表没有 `user_id` 字段。

- [x] **步骤 3：编写最少实现代码**

在 `backend/app/core/auth_db.py` 中增加记录类型和 schema 迁移：

```python
@dataclass(frozen=True)
class AuthUserRecord:
    user_id: str
    username: str
    created_at: str
```

```python
def _ensure_user_id_column(conn: sqlite3.Connection) -> None:
    cols = {str(row["name"]) for row in conn.execute("PRAGMA table_info(users)").fetchall()}
    if "user_id" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN user_id TEXT")
    rows = conn.execute("SELECT username, user_id FROM users").fetchall()
    for row in rows:
        if not str(row["user_id"] or "").strip():
            conn.execute(
                "UPDATE users SET user_id = ? WHERE username = ?",
                (f"user-{uuid.uuid4().hex}", str(row["username"])),
            )
        )
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_user_id ON users(user_id)")
```

在 `create_user` 中生成 `user_id` 并插入；在 `get_user_by_username(username: str) -> Optional[AuthUserRecord]` 中按登录名返回记录。

- [x] **步骤 4：运行测试验证通过**

运行：

```bash
/Users/ggd/.local/bin/rtk conda run -n st49 bash -lc 'cd backend && python -m pytest -q tests/test_auth_sqlite.py::test_register_creates_stable_user_id_and_returns_it'
```

预期：PASS。

- [x] **步骤 5：Commit**

```bash
/Users/ggd/.local/bin/rtk git add backend/app/core/auth_db.py backend/tests/test_auth_sqlite.py
/Users/ggd/.local/bin/rtk git commit -m "refactor(auth): 为账号引入稳定 user_id"
```

## 任务 2：用户上下文切到 user_id 目录

**文件：**
- 修改：`backend/app/core/user_context.py`
- 修改：`backend/app/core/security.py`
- 修改：`backend/app/api/auth.py`
- 测试：`backend/tests/test_auth_sqlite.py`
- 测试：`backend/tests/test_user_resource_paths.py`

- [x] **步骤 1：编写失败的测试**

新建 `backend/tests/test_user_resource_paths.py`：

```python
import json


def test_user_context_uses_user_id_not_email(monkeypatch, tmp_path):
    from app.core.user_context import build_user_context

    monkeypatch.setenv("SHUTONG_USER_DATA_ROOT", str(tmp_path / "users"))

    ctx = build_user_context(user_id="user-abc123", username="alice@example.com")

    assert ctx.user_id == "user-abc123"
    assert ctx.username == "alice@example.com"
    assert ctx.base_dir == (tmp_path / "users" / "user-abc123").resolve()
    assert ctx.resources_dir == ctx.base_dir / "resources"
    assert ctx.sessions_dir == ctx.base_dir / "sessions"
    assert ctx.vault_dir == ctx.base_dir / "vault"
    assert not (tmp_path / "users" / "alice@example.com").exists()
```

在 `backend/tests/test_auth_sqlite.py` 中新增：

```python
def test_register_initializes_user_id_directory_layout(env_and_client):
    client, db_path = env_and_client

    username = "layout@example.com"
    data = _auth_register(client, username=username, password="pw-layout-123")
    user_root = db_path.parent / "users" / data["user_id"]

    assert user_root.exists()
    assert (user_root / "profile.json").exists()
    assert (user_root / "resources" / "scenarios").is_dir()
    assert (user_root / "resources" / "agents").is_dir()
    assert (user_root / "resources" / "skills").is_dir()
    assert (user_root / "resources" / "tools").is_dir()
    assert (user_root / "resources" / "models").is_dir()
    assert (user_root / "sessions").is_dir()
    assert (user_root / "vault").is_dir()
    assert not (db_path.parent / "users" / username).exists()

    profile = json.loads((user_root / "profile.json").read_text(encoding="utf-8"))
    assert profile["user_id"] == data["user_id"]
    assert profile["username"] == username
```

- [x] **步骤 2：运行测试验证失败**

运行：

```bash
/Users/ggd/.local/bin/rtk conda run -n st49 bash -lc 'cd backend && python -m pytest -q tests/test_user_resource_paths.py tests/test_auth_sqlite.py::test_register_initializes_user_id_directory_layout'
```

预期：FAIL，`build_user_context` 不存在或目录仍使用邮箱名。

- [x] **步骤 3：编写最少实现代码**

把 `UserContext` 扩展为：

```python
@dataclass
class UserContext:
    user_id: str
    username: str
    base_dir: Path
    profile_path: Path
    resources_dir: Path
    scenarios_dir: Path
    agents_dir: Path
    skills_dir: Path
    tools_dir: Path
    models_dir: Path
    vault_dir: Path
    sessions_dir: Path
    agent_outputs_dir: Path
    config_dir: Path
```

新增：

```python
def build_user_context(*, user_id: str, username: str = "") -> UserContext:
    uid = (user_id or "").strip()
    if not uid:
        raise ValueError("user_id is required")
    data_root = users_data_root() / uid
    resources = data_root / "resources"
    return UserContext(
        user_id=uid,
        username=(username or "").strip(),
        base_dir=data_root,
        profile_path=data_root / "profile.json",
        resources_dir=resources,
        scenarios_dir=resources / "scenarios",
        agents_dir=resources / "agents",
        skills_dir=resources / "skills",
        tools_dir=resources / "tools",
        models_dir=resources / "models",
        vault_dir=data_root / "vault",
        sessions_dir=data_root / "sessions",
        agent_outputs_dir=data_root / "sessions",
        config_dir=data_root / "config",
    )
```

在请求依赖中通过 `auth_db.get_user_by_username()` 解析 `user_id`，再设置当前 `user_id` 上下文。`config_dir` 暂保留给过渡期配置，后续 Phase B-D 逐步消除主业务依赖。

- [x] **步骤 4：运行测试验证通过**

运行：

```bash
/Users/ggd/.local/bin/rtk conda run -n st49 bash -lc 'cd backend && python -m pytest -q tests/test_user_resource_paths.py tests/test_auth_sqlite.py::test_register_initializes_user_id_directory_layout'
```

预期：PASS。

- [x] **步骤 5：Commit**

```bash
/Users/ggd/.local/bin/rtk git add backend/app/core/user_context.py backend/app/core/security.py backend/app/api/auth.py backend/tests/test_user_resource_paths.py backend/tests/test_auth_sqlite.py
/Users/ggd/.local/bin/rtk git commit -m "refactor(user-store): 使用 user_id 初始化用户资源目录"
```

## 任务 3：原子 JSON 写入工具

**文件：**
- 新建：`backend/app/core/atomic_json.py`
- 测试：`backend/tests/test_user_resource_paths.py`

- [x] **步骤 1：编写失败的测试**

在 `backend/tests/test_user_resource_paths.py` 中新增：

```python
def test_atomic_write_json_preserves_existing_file_on_serializer_error(tmp_path):
    from app.core.atomic_json import atomic_write_json, read_json_or_default

    target = tmp_path / "resource.json"
    atomic_write_json(target, {"version": 1, "name": "old"})

    class NotJson:
        pass

    try:
        atomic_write_json(target, {"bad": NotJson()})
    except TypeError:
        pass

    assert read_json_or_default(target, {}) == {"version": 1, "name": "old"}
    assert not list(tmp_path.glob("resource.json.*.tmp"))
```

- [x] **步骤 2：运行测试验证失败**

运行：

```bash
/Users/ggd/.local/bin/rtk conda run -n st49 bash -lc 'cd backend && python -m pytest -q tests/test_user_resource_paths.py::test_atomic_write_json_preserves_existing_file_on_serializer_error'
```

预期：FAIL，`app.core.atomic_json` 不存在。

- [x] **步骤 3：编写最少实现代码**

新建 `backend/app/core/atomic_json.py`：

```python
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, TypeVar

T = TypeVar("T")


def atomic_write_text(path: Path, content: str) -> None:
    target = Path(path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f"{target.name}.", suffix=".tmp", dir=str(target.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, target)
    except Exception:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass
        raise


def atomic_write_json(path: Path, payload: Any) -> None:
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def read_json_or_default(path: Path, default: T) -> T:
    target = Path(path)
    if not target.exists():
        return default
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except Exception:
        return default
```

- [x] **步骤 4：运行测试验证通过**

运行：

```bash
/Users/ggd/.local/bin/rtk conda run -n st49 bash -lc 'cd backend && python -m pytest -q tests/test_user_resource_paths.py::test_atomic_write_json_preserves_existing_file_on_serializer_error'
```

预期：PASS。

- [x] **步骤 5：Commit**

```bash
/Users/ggd/.local/bin/rtk git add backend/app/core/atomic_json.py backend/tests/test_user_resource_paths.py
/Users/ggd/.local/bin/rtk git commit -m "feat(storage): 增加原子 JSON 写入工具"
```

## 任务 4：标准资源路径 helper

**文件：**
- 修改：`backend/app/core/user_settings_paths.py`
- 测试：`backend/tests/test_user_resource_paths.py`

- [x] **步骤 1：编写失败的测试**

在 `backend/tests/test_user_resource_paths.py` 中新增：

```python
def test_resource_path_helpers_point_to_resources(monkeypatch, tmp_path):
    from app.core.user_context import set_current_user_identity, reset_current_user_identity
    from app.core.user_settings_paths import (
        agents_resources_dir,
        models_resources_dir,
        scenarios_resources_dir,
        skills_dir_path,
        tools_resources_dir,
        vault_secrets_path,
    )

    monkeypatch.setenv("SHUTONG_USER_DATA_ROOT", str(tmp_path / "users"))
    token = set_current_user_identity(user_id="user-paths", username="paths@example.com")
    try:
        root = (tmp_path / "users" / "user-paths").resolve()
        assert scenarios_resources_dir() == root / "resources" / "scenarios"
        assert agents_resources_dir() == root / "resources" / "agents"
        assert skills_dir_path() == root / "resources" / "skills"
        assert tools_resources_dir() == root / "resources" / "tools"
        assert models_resources_dir() == root / "resources" / "models"
        assert vault_secrets_path() == root / "vault" / "secrets.enc.json"
    finally:
        reset_current_user_identity(token)
```

- [x] **步骤 2：运行测试验证失败**

运行：

```bash
/Users/ggd/.local/bin/rtk conda run -n st49 bash -lc 'cd backend && python -m pytest -q tests/test_user_resource_paths.py::test_resource_path_helpers_point_to_resources'
```

预期：FAIL，新的 helper 或 `set_current_user_identity` 不存在，或 `skills_dir_path()` 仍指向旧 `skills/`。

- [x] **步骤 3：编写最少实现代码**

在 `backend/app/core/user_settings_paths.py` 增加：

```python
def scenarios_resources_dir() -> Path:
    return require_user_context().scenarios_dir.resolve()


def agents_resources_dir() -> Path:
    return require_user_context().agents_dir.resolve()


def tools_resources_dir() -> Path:
    return require_user_context().tools_dir.resolve()


def models_resources_dir() -> Path:
    return require_user_context().models_dir.resolve()


def vault_secrets_path() -> Path:
    return (require_user_context().vault_dir / "secrets.enc.json").resolve()
```

把 `skills_dir_path()` 调整为 `require_user_context().skills_dir.resolve()`，其中 `skills_dir` 已由任务 2 指向 `resources/skills`。

- [x] **步骤 4：运行测试验证通过**

运行：

```bash
/Users/ggd/.local/bin/rtk conda run -n st49 bash -lc 'cd backend && python -m pytest -q tests/test_user_resource_paths.py::test_resource_path_helpers_point_to_resources'
```

预期：PASS。

- [x] **步骤 5：Commit**

```bash
/Users/ggd/.local/bin/rtk git add backend/app/core/user_settings_paths.py backend/tests/test_user_resource_paths.py
/Users/ggd/.local/bin/rtk git commit -m "refactor(storage): 暴露标准资源路径 helper"
```

## 任务 5：改账号不迁移 user_id 资源目录

**文件：**
- 修改：`backend/app/api/auth.py`
- 修改：`backend/app/core/users_store.py`
- 测试：`backend/tests/test_auth_sqlite.py`

- [x] **步骤 1：编写失败的测试**

在 `backend/tests/test_auth_sqlite.py` 中新增：

```python
def test_change_account_keeps_user_id_resource_directory(env_and_client):
    client, db_path = env_and_client

    old_username = "old-account@example.com"
    new_username = "new-account@example.com"
    registered = _auth_register(client, username=old_username, password="pw-account-123")
    token = registered["access_token"]
    user_id = registered["user_id"]
    old_user_root = db_path.parent / "users" / user_id
    marker = old_user_root / "resources" / "skills" / "marker" / "SKILL.md"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("---\nname: Marker\n---\nbody\n", encoding="utf-8")

    r = client.put(
        "/api/auth/account",
        headers={"Authorization": f"Bearer {token}"},
        json={"new_username": new_username, "current_password": "pw-account-123"},
    )

    assert r.status_code == 200
    data = r.json()["data"]
    assert data["username"] == new_username
    assert data["user_id"] == user_id
    assert marker.exists()
    assert old_user_root.exists()
    assert not (db_path.parent / "users" / new_username).exists()
```

- [x] **步骤 2：运行测试验证失败**

运行：

```bash
/Users/ggd/.local/bin/rtk conda run -n st49 bash -lc 'cd backend && python -m pytest -q tests/test_auth_sqlite.py::test_change_account_keeps_user_id_resource_directory'
```

预期：FAIL，当前 `_move_user_data_dir` 按账号名移动目录，或响应没有 `user_id`。

- [x] **步骤 3：编写最少实现代码**

删除改账号主流程中的 `_move_user_data_dir` 调用。`rename_user_profile` 改为按 `user_id` 写入 `profile.json` 的 `username` 字段；SQLite 的 `rename_user` 只更新登录名。

`/auth/account` 返回：

```python
return {
    "status": "ok",
    "data": {
        "user_id": user_record.user_id,
        "username": new_name,
        "display_name": profile.display_name or new_name,
        "access_token": token,
        "token_type": "bearer",
    },
}
```

- [x] **步骤 4：运行测试验证通过**

运行：

```bash
/Users/ggd/.local/bin/rtk conda run -n st49 bash -lc 'cd backend && python -m pytest -q tests/test_auth_sqlite.py::test_change_account_keeps_user_id_resource_directory'
```

预期：PASS。

- [x] **步骤 5：Commit**

```bash
/Users/ggd/.local/bin/rtk git add backend/app/api/auth.py backend/app/core/users_store.py backend/tests/test_auth_sqlite.py
/Users/ggd/.local/bin/rtk git commit -m "fix(auth): 改账号时保持 user_id 资源目录稳定"
```

## 任务 6：Phase A 回归验证

**文件：**
- 修改：前面任务涉及的全部文件

- [x] **步骤 1：运行认证和路径测试**

运行：

```bash
/Users/ggd/.local/bin/rtk conda run -n st49 bash -lc 'cd backend && python -m pytest -q tests/test_auth_sqlite.py tests/test_user_resource_paths.py'
```

预期：PASS。

- [x] **步骤 2：运行受影响沙箱和资源引用测试**

运行：

```bash
/Users/ggd/.local/bin/rtk conda run -n st49 bash -lc 'cd backend && python -m pytest -q tests/test_sandbox_service.py tests/test_skill_mcp_and_script_requirements.py tests/test_missing_reference_snapshots.py tests/test_public_share_api.py'
```

预期：PASS。若失败，优先确认失败是否来自 `skills_dir_path()` 指向 `resources/skills` 后的测试 fixture 路径不一致。

- [x] **步骤 3：编译关键模块**

运行：

```bash
/Users/ggd/.local/bin/rtk conda run -n st49 bash -lc 'cd backend && python -m py_compile app/core/auth_db.py app/core/security.py app/core/user_context.py app/core/user_settings_paths.py app/core/atomic_json.py app/api/auth.py'
```

预期：无输出且退出码为 0。

- [x] **步骤 4：清理 Python 缓存**

运行：

```bash
/Users/ggd/.local/bin/rtk sh -lc 'find backend -type d -name __pycache__ -prune -exec rm -rf {} +; find backend -type f -name "*.pyc" -delete'
```

预期：退出码为 0，`git status --short` 不包含 `__pycache__` 或 `.pyc`。

- [x] **步骤 5：Commit**

```bash
/Users/ggd/.local/bin/rtk git status --short
/Users/ggd/.local/bin/rtk git commit --allow-empty -m "test(storage): 完成用户资源 Phase A 回归验证"
```

## 后续计划入口

Phase A 合并后再新建 Phase B 计划，范围只覆盖 `resources/scenarios` 和 `resources/agents`。Phase B 的第一个红灯测试应验证 `/api/settings/session-presets` 仍返回旧字段结构，但磁盘主体文件已写入 `resources/scenarios/<scenario_id>/scenario.json`；第二个红灯测试应验证 `/api/dha` 仍返回 `agent_id`/`expert_id` 兼容字段，但磁盘主体文件已写入 `resources/agents/<agent_id>/agent.json`。

## 自检

- 规格覆盖度：覆盖了身份目录主键、标准目录、原子 JSON 写入、注册初始化、改账号稳定目录；尚未实现资源迁移，已拆到 Phase B-F。
- 占位符扫描：本文没有使用未完成占位符；每个任务都有具体文件、测试、命令和预期结果。
- 类型一致性：`user_id`、`username`、`UserContext`、`resources_dir`、`vault_dir` 命名在任务 1-5 中一致。
