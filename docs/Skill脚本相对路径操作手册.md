# Skill 脚本相对路径操作手册

本文面向开发者和 Skill 作者，说明 `run_skill_script_<skill_id>` 执行脚本时可以读写哪些相对路径、这些路径在宿主机和 OpenSandbox 中分别对应哪里，以及脚本应该如何设计路径。

## 一句话规则

Skill 脚本的 `script_path` 相对 `scripts/` 目录；脚本进程的当前工作目录相对当前会话工作区。

也就是说：

- 工具参数 `script_path="foo.py"` 表示执行当前 Skill 的 `scripts/foo.py`。
- 脚本里 `open("input.csv")` 默认读的是当前会话工作区中的 `input.csv`。
- 脚本里要读 Skill 自带资源时，不要依赖当前工作目录，应使用 `SKILL_HOME` 或 `SKILL_SCRIPT_ROOT`。

## 运行时路径模型

### 宿主机路径

当前用户的所有运行时数据位于：

```text
backend/data/users/<user_id>/
```

测试或部署可通过 `SHUTONG_USER_DATA_ROOT` 改变 `data/users` 根目录。

| 类型 | 宿主机路径 | 用途 |
| --- | --- | --- |
| 用户根目录 | `backend/data/users/<user_id>/` | 当前用户全部运行时数据 |
| 资源中心 | `backend/data/users/<user_id>/resources/` | 可导入、导出、分享的资源 |
| Skill | `backend/data/users/<user_id>/resources/skills/<skill_id>/` | `SKILL.md`、`scripts/`、`assets/`、`config/` 等 |
| 会话数据 | `backend/data/users/<user_id>/sessions/` | 会话历史、运行状态、workspace |
| 工作区根 | `backend/data/users/<user_id>/sessions/workspaces/<session_id>/` | 用户上传文件、脚本输入输出、可下载结果 |
| 沙箱依赖 | `backend/data/users/<user_id>/config/sandbox/requirements.txt` | 当前用户额外 Python 依赖 |
| 沙箱设置 | `backend/data/users/<user_id>/config/sandbox/settings.json` | 当前用户沙箱镜像选择等设置 |

不要在 Skill 脚本里硬编码这些宿主机路径。脚本运行在沙箱内时看到的是下面的沙箱路径。

### 沙箱路径

`run_skill_script_<skill_id>` 进入 OpenSandbox 时，当前用户的工作区和 Skill 资源会被挂载成：

| 类型 | 沙箱路径 | 读写权限 | 用法 |
| --- | --- | --- | --- |
| 用户所有工作区 | `/workspace/` | 可读写 | 其下每个子目录是一个会话 |
| 当前会话工作区 | `/workspace/<session_id>/` | 可读写 | 脚本进程的 `cwd`；真实路径由 `SKILL_WORKSPACE_ROOT` 提供 |
| 用户所有 Skill | `/skills/` | 只读 | 其下每个子目录是一个 Skill |
| 当前 Skill 根目录 | `/skills/<skill_id>/` | 只读 | 真实路径由 `SKILL_HOME` 提供 |
| 当前 Skill 脚本目录 | `/skills/<skill_id>/scripts/` | 只读 | `SKILL_SCRIPT_ROOT` |

脚本执行时会先 `cd /workspace/<session_id>`。因此普通相对路径应默认视为“当前会话工作区相对路径”。

开发者不需要提前知道 `session_id` 或 `skill_id`。这两个 id 由后端在创建工具时绑定，并在脚本运行时通过环境变量注入。脚本不要拼接 `/workspace/<session_id>` 或 `/skills/<skill_id>`，而应读取 `SKILL_WORKSPACE_ROOT`、`SKILL_HOME` 和 `SKILL_SCRIPT_ROOT`。

不建议为脚本额外开放“查询当前 session/Skill id”的接口函数，原因是：

- 脚本已经运行在当前用户、当前会话、当前 Skill 的授权上下文中，环境变量就是这层上下文的稳定接口。
- 额外接口会让脚本依赖后端 API、鉴权和网络可达性，降低离线可测性。
- 直接开放查询接口容易诱导脚本跨会话、跨 Skill 拼路径，破坏隔离边界。

## 脚本环境变量

脚本应优先通过环境变量定位运行时路径：

| 变量 | 示例值 | 说明 |
| --- | --- | --- |
| `SKILL_ID` | `sqlite-demo` | 当前 Skill id |
| `SKILL_HOME` | `/skills/sqlite-demo` | 当前 Skill 根目录 |
| `SKILL_SCRIPT_ROOT` | `/skills/sqlite-demo/scripts` | 当前 Skill 的脚本目录 |
| `SKILL_WORKSPACE_ID` | `group-c1202b2661d9` | 当前会话或 workspace id |
| `SKILL_WORKSPACE_ROOT` | `/workspace/group-c1202b2661d9` | 当前会话工作区 |
| `SKILL_WRITE_MODE` | `workspace_all` | 脚本写入权限模式 |
| `SKILL_REQUIREMENTS_B64` | base64 文本 | 当前用户 `requirements.txt` 内容 |
| `SKILL_REQUIREMENTS_HASH` | `5817ace3254dfe26` | 当前用户依赖内容 hash |

最常用的 Python 写法：

```python
from pathlib import Path
import os

WORKSPACE_ROOT = Path(os.environ["SKILL_WORKSPACE_ROOT"]).resolve()
SKILL_HOME = Path(os.environ["SKILL_HOME"]).resolve()
SCRIPT_ROOT = Path(os.environ["SKILL_SCRIPT_ROOT"]).resolve()
```

推荐在每个复杂脚本里放一个很小的路径 helper，统一处理当前工作区相对路径：

```python
from pathlib import Path
import os

WORKSPACE_ROOT = Path(os.environ["SKILL_WORKSPACE_ROOT"]).resolve()
SKILL_HOME = Path(os.environ["SKILL_HOME"]).resolve()
SCRIPT_ROOT = Path(os.environ["SKILL_SCRIPT_ROOT"]).resolve()
SKILL_ID = os.environ.get("SKILL_ID", "")
WORKSPACE_ID = os.environ.get("SKILL_WORKSPACE_ID", "")


def workspace_path(rel_path: str) -> Path:
    raw = str(rel_path or "").strip().replace("\\", "/").lstrip("/")
    if not raw or ".." in raw:
        raise ValueError("path must be relative to the current workspace")
    path = (WORKSPACE_ROOT / raw).resolve()
    if not str(path).startswith(str(WORKSPACE_ROOT)):
        raise ValueError("path escapes the current workspace")
    return path


def workspace_rel(path: Path) -> str:
    return path.resolve().relative_to(WORKSPACE_ROOT).as_posix()


def skill_asset(*parts: str) -> Path:
    return (SKILL_HOME / "assets" / Path(*parts)).resolve()
```

如果脚本只是读写当前会话文件，甚至不需要读取 `SKILL_WORKSPACE_ID`：直接使用相对路径或 `SKILL_WORKSPACE_ROOT` 即可。`SKILL_ID` 和 `SKILL_WORKSPACE_ID` 主要用于日志、输出元数据或生成不会冲突的文件名。

## 读写查工作区文件和文件夹

开发者要先区分三种场景：

| 场景 | 应该使用什么 | 是否需要知道 `session_id` |
| --- | --- | --- |
| 写 `SKILL.md`，让专家在对话中操作工作区 | 内置工作区工具 | 不需要，后端已绑定当前会话 |
| 写 Skill 脚本，在 `run_skill_script` 里读写文件 | Python / shell 文件系统操作 | 不需要，用 `cwd` 或 `SKILL_WORKSPACE_ROOT` |
| 写前端或外部集成代码 | `/api/workspaces/{workspace_id}/files...` REST 接口 | 需要，`workspace_id` 就是当前会话 id |

### 1. `SKILL.md` 中可要求专家调用的工作区工具

这些工具由 `build_tools_for_group_chat(...)` 注入到专家可用工具列表中，参数里的路径一律是当前工作区相对路径。

| 动作 | 工具名 | 参数 | 示例 |
| --- | --- | --- | --- |
| 列目录 | `list_workspace_directory` | `path`，空字符串表示根目录 | `{"path": ""}` 或 `{"path": "outputs"}` |
| 读文本文件 | `read_file` | `path` | `{"path": "notes/report.md"}` |
| 写入/覆盖文本文件 | `write_workspace_file` | `path`, `content` | `{"path": "outputs/result.md", "content": "..."}` |
| 增量编辑文本文件 | `edit_workspace_file` | `path`, `old_text`, `new_text` | `{"path": "notes/report.md", "old_text": "旧", "new_text": "新"}` |
| 创建目录 | `mkdir_workspace` | `path` | `{"path": "outputs/images"}` |
| 重命名或移动 | `rename_workspace_file` | `path`, `new_name` | `{"path": "draft.md", "new_name": "archive/draft.md"}` |

推荐在 `SKILL.md` 中这样写：

```text
如果需要查看当前工作区文件，先调用 list_workspace_directory，path 为空字符串。
如果需要读取用户上传的文本文件，调用 read_file，path 使用工作区相对路径。
如果需要保存结果，调用 write_workspace_file，path 使用 outputs/<文件名>。
不要要求用户提供 /workspace/<session_id> 或宿主机绝对路径。
```

注意：

- `read_file` 只适合文本文件；二进制文件应交给脚本通过文件系统读取。
- `write_workspace_file` 会覆盖目标文本文件。
- `edit_workspace_file` 要求 `old_text` 能在原文中精确匹配。
- `rename_workspace_file` 可移动文件；如果 `new_name` 含 `/`，表示目标相对路径。
- 这些工具不暴露 `session_id`，专家和 Skill 作者都不需要知道当前会话 id。

### 2. Skill 脚本内的文件系统命令

`run_skill_script` 启动脚本前会把 `cwd` 切到当前工作区，所以脚本里可以直接用相对路径：

```bash
pwd                         # /workspace/<session_id>
ls -la                      # 查看当前工作区根目录
find . -maxdepth 3 -type f  # 查文件
mkdir -p outputs            # 创建目录
cat notes/report.md         # 读文本文件
cp input.csv outputs/copy.csv
mv outputs/tmp.json outputs/result.json
```

删除文件或目录要谨慎，只删除脚本自己生成的相对路径：

```bash
rm outputs/tmp.json
```

Python 脚本推荐这样读写：

```python
from pathlib import Path

# 当前 cwd 已经是当前工作区。
text = Path("notes/report.md").read_text(encoding="utf-8")

out = Path("outputs/result.md")
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text("处理结果", encoding="utf-8")
```

如果参数来自用户或模型，必须走 `workspace_path()` 校验：

```python
input_path = workspace_path(args.input)
output_path = workspace_path(args.output)
```

脚本返回给用户的路径应是工作区相对路径：

```python
print(json.dumps({
    "ok": True,
    "outputs": [workspace_rel(output_path)],
}, ensure_ascii=False))
```

### 3. 前端或外部集成可用的 REST 接口

这些接口用于前端、调试页面或外部集成。它们需要知道 `workspace_id`，也就是当前会话 id。Skill 脚本一般不要调用这些接口。

| 动作 | 方法与路径 | 参数/Body |
| --- | --- | --- |
| 列目录 | `GET /api/workspaces/{workspace_id}/files?path=<dir>` | `path` 为空表示根目录 |
| 下载文件 | `GET /api/workspaces/{workspace_id}/files/download?path=<file>` | `path` 为工作区相对路径 |
| 读取文本 | `GET /api/workspaces/{workspace_id}/files/content?path=<file>` | UTF-8 文本文件 |
| 写入/覆盖文本 | `PUT /api/workspaces/{workspace_id}/files/content?path=<file>` | JSON body: `{"content": "..."}` |
| 删除文件或空目录 | `DELETE /api/workspaces/{workspace_id}/files/content?path=<path>` | 目录必须为空 |
| 创建文件 | `POST /api/workspaces/{workspace_id}/files?path=<dir>` | JSON body: `{"filename": "a.md", "content": "..."}` |
| 创建目录 | `POST /api/workspaces/{workspace_id}/files/mkdir?path=<parent>` | JSON body: `{"dirname": "outputs"}` |
| 上传文件 | `POST /api/workspaces/{workspace_id}/files/upload?path=<dir>` | multipart form: `file=@...` |
| 重命名/移动文件 | `PUT /api/workspaces/{workspace_id}/files/rename?path=<old>` | JSON body: `{"new_name": "new/or/name.md"}` |

REST 示例：

```bash
curl -H "Authorization: Bearer <token>" \
  "http://localhost:8000/api/workspaces/<workspace_id>/files?path=outputs"

curl -X PUT -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"content":"hello"}' \
  "http://localhost:8000/api/workspaces/<workspace_id>/files/content?path=outputs/hello.txt"
```

如果你是在写 Skill 或专家提示，优先使用前两类方式，不要绕到 REST 接口。

## 相对路径约定

### 1. `script_path` 相对 `scripts/`

工具调用：

```json
{
  "script_path": "sqlite_demo.py",
  "cli_args_json": "[\"--preset\", \"overview\"]"
}
```

实际执行：

```text
/skills/<skill_id>/scripts/sqlite_demo.py
```

如果脚本放在子目录：

```json
{
  "script_path": "tools/query.py"
}
```

实际执行：

```text
/skills/<skill_id>/scripts/tools/query.py
```

`script_path` 不能是绝对路径，不能包含 `..`。历史提示中写成 `scripts/foo.py` 时，后端会归一化成 `foo.py`，但新 Skill 不应依赖这个兼容行为。

### 2. CLI 参数中的文件路径相对当前会话工作区

如果用户选择了工作区文件，前端和工具提示中的路径应是工作区相对路径，例如：

```text
uploads/report.xlsx
notes/query.sql
```

脚本应把这些路径解析到 `SKILL_WORKSPACE_ROOT` 下：

```python
from pathlib import Path
import os

WORKSPACE_ROOT = Path(os.environ["SKILL_WORKSPACE_ROOT"]).resolve()

def workspace_path(rel_path: str) -> Path:
    raw = (rel_path or "").strip().replace("\\", "/").lstrip("/")
    if not raw or ".." in raw:
        raise ValueError("path must be a workspace-relative path")
    path = (WORKSPACE_ROOT / raw).resolve()
    if not str(path).startswith(str(WORKSPACE_ROOT)):
        raise ValueError("path escapes workspace")
    return path
```

脚本输出给用户或前端的文件路径也应返回工作区相对路径，不要返回 `/workspace/<session_id>/...` 或宿主机绝对路径。

### 3. 脚本中直接打开相对路径就是工作区相对路径

因为 `cwd` 是当前会话工作区：

```python
Path("output/result.json").write_text("{}", encoding="utf-8")
```

等价于写入：

```text
/workspace/<session_id>/output/result.json
```

这种写法适合生成用户可见结果。目录不存在时脚本要自行创建：

```python
out_dir = Path("output")
out_dir.mkdir(parents=True, exist_ok=True)
```

### 4. Skill 自带资源相对 `SKILL_HOME`

Skill 自带数据库、模板、示例文件、提示词片段等，应放在 Skill 根目录下的 `assets/` 或 `config/`，脚本通过 `SKILL_HOME` 读取：

```python
db_path = SKILL_HOME / "assets" / "demo.sqlite"
template_path = SKILL_HOME / "assets" / "template.docx"
```

当前 Skill 在沙箱内是只读挂载。脚本不要尝试写入 `/skills/<skill_id>/...`。如果需要生成缓存或结果，写到当前工作区，例如 `cache/`、`output/` 或 `tmp/`。

## 数据库文件怎么设计

### 临时数据库

只用于本次脚本运行的 SQLite 数据库，优先使用内存数据库：

```python
import sqlite3

conn = sqlite3.connect(":memory:")
```

适合 demo、临时聚合、格式转换过程中的中间表。

### 用户可见或可复用数据库

如果数据库是本次会话的产物，或者用户后续需要下载、继续查询，应写到当前工作区：

```python
db_path = WORKSPACE_ROOT / "data" / "jobs.sqlite"
db_path.parent.mkdir(parents=True, exist_ok=True)
conn = sqlite3.connect(db_path)
```

返回给用户时使用工作区相对路径：

```json
{
  "ok": true,
  "database": "data/jobs.sqlite"
}
```

### Skill 内置只读数据库

如果数据库随 Skill 一起发布，例如示例库、标准表、地区编码库，应放在：

```text
resources/skills/<skill_id>/assets/<name>.sqlite
```

脚本中只读打开：

```python
db_path = SKILL_HOME / "assets" / "demo.sqlite"
conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
```

不要把会变动的业务数据放进 Skill 内置数据库。Skill 目录是资源包，不是运行时写入区。

### 平台内部数据库

平台登录库等内部文件，例如 `backend/config/auth_users.sqlite`，不属于 Skill 可访问资源。Skill 脚本不要读取、修改或假设这些内部数据库存在。

## 推荐 Skill 目录结构

```text
resources/skills/<skill_id>/
  SKILL.md
  scripts/
    manifest.json
    main.py
    lib/
      helpers.py
  assets/
    demo.sqlite
    template.xlsx
  config/
    defaults.json
```

设计原则：

- `scripts/` 放可执行入口和脚本私有库。
- `assets/` 放随 Skill 分发的只读资源。
- `config/` 放随 Skill 分发的只读默认配置。
- 会变化的用户数据、结果、缓存、导出文件放工作区。
- Python 依赖写在 `SKILL.md` 的 `auto-tools` / `allowed-tools.python` 元数据中，由设置-沙箱依赖合并到用户 `requirements.txt`。

## 输入输出约定

脚本型 Skill 统一使用 CLI 参数：

```json
{
  "script_path": "main.py",
  "cli_args_json": "[\"--input\", \"uploads/a.xlsx\", \"--output\", \"output/result.json\"]"
}
```

不要再设计依赖 `input_json` 或 stdin JSON 的脚本协议。

脚本 stdout 推荐输出 JSON，至少包含：

```json
{
  "ok": true,
  "code": "done",
  "message": "处理完成",
  "outputs": ["output/result.json"],
  "skill_session_over": true
}
```

其中：

- `outputs` 使用工作区相对路径。
- `skill_session_over: true` 表示当前 Skill 流程已经结束。
- 如果还需要用户补充参数或确认，使用 `skill_session_over: false`。

## 安全边界

脚本必须遵守这些边界：

- 不接受绝对路径作为用户输入。
- 不接受包含 `..` 的路径。
- 不向用户暴露宿主机路径。
- 不写 `/skills/<skill_id>/...`。
- 不读取其他会话的 `/workspace/<other_session_id>/...`。
- 不把平台内部配置、密钥或认证数据库当作 Skill 数据源。

## 开发检查清单

交付一个脚本型 Skill 前，至少检查：

- `script_path` 能通过 `__list__` 查到。
- `scripts/manifest.json` 中的脚本名和实际文件名一致。
- CLI 参数中的文件路径全部按工作区相对路径解析。
- 输出文件写到当前工作区，并返回工作区相对路径。
- Skill 自带资源通过 `SKILL_HOME` 或 `SKILL_SCRIPT_ROOT` 读取。
- 数据库写入位置符合用途：临时用 `:memory:`，会话产物写 workspace，内置数据放 `assets/` 只读。
- 本地测试至少覆盖一次 `run_skill_script_<skill_id>`，不要只在宿主机直接 `python scripts/foo.py`。
