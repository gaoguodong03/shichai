# 验证「按会话隔离的本地文件能力」

本文档提供**一个可执行的验证场景**，用于确认 [local-file-operations.md](./local-file-operations.md) 中 P0 已实现的行为。

---

## 前置条件

- 后端已启动：`cd backend && uvicorn app.main:app --reload`（或 `python -m app.main`）
- 前端已启动：`cd frontend && npm run dev`
- 已配置至少一个可用的 DHA（默认使用「内容生成专家」）

---

## 一键准备场景

在**项目根目录**或 **backend 目录**执行：

```bash
# 若在项目根目录（需能访问 backend）
python backend/scripts/seed_verify_workspace.py

# 若已在 backend 目录
python scripts/seed_verify_workspace.py
```

脚本会：

1. 调用 `POST /api/group-sessions` 创建一个标题为「验证文件能力」的会话  
2. 在该会话的 workspace 下创建文件 `验证用-说明.md`  
3. 在终端打印**会话 ID** 和**详细验证步骤**

确保后端已启动，否则脚本会提示无法连接。

---

## 验证步骤（与脚本输出一致）

### 1. 打开会话

- 打开 http://localhost:5173
- 左侧「Chat」下找到「验证文件能力」，点击进入

### 2. 验证「读文件」

- 在输入框旁点击「引用文件」/「📎」，在列表中选择 **验证用-说明.md**
- 或直接输入：
  ```text
  请读取【文件引用：workspaces/<会话ID>/验证用-说明.md】并总结要点
  ```
  （若用文件选择器插入，路径会自动带 `workspaces/<会话ID>/`）
- 发送后，DHA 应能读取该文件并回答

### 3. 验证「写文件」

- 输入：
  ```text
  请把上面要点的总结写入工作区文件 summary.md
  ```
- 发送后，DHA 应调用 `write_workspace_file` 并提示已写入

### 4. 验证「Files 按会话隔离」

- 左侧切换到 **Files**
- 若未选会话，应看到提示「请先在 Chat 中选择一个会话」
- 在 Chat 中保持当前会话选中，再切到 Files，应看到**该会话工作区**下的文件：`验证用-说明.md`、`summary.md`（若步骤 3 成功）
- 点击文件可预览/下载，确认只能看到本会话内容

### 5. 验证「导出到工作区」

- 回到该会话对话，发送：**请导出当前对话为 markdown**（或使用导出技能）
- 导出成功后，下载链接应为：`/api/workspaces/<会话ID>/files/download?path=session-xxx.md`
- 在 **Files** 中刷新，应看到新出现的导出文件

### 6. 验证「无全局 /api/files」（可选）

- 浏览器控制台执行：`fetch('/api/files').then(r => console.log(r.status))`，应得到 **404**
- 或：`curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/api/files` → **404**

---

## 预期结果汇总

| 项           | 预期 |
|--------------|------|
| 读本会话工作区文件 | 能通过【文件引用】或文件选择器读取并回答 |
| 写本会话工作区文件 | 能通过 `write_workspace_file` 写入并提示路径 |
| Files 标签     | 仅展示当前选中会话的 workspace，无会话时提示先选会话 |
| 导出会话       | 文件落在本会话 workspace，下载走 workspace 接口 |
| 全局 /api/files | 已下线，返回 404 |

若以上均符合，则 P0「按会话隔离的 workspace + 无全局 /api/files」验证通过。
