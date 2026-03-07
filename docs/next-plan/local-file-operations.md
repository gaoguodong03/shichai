# 让 DHA 具备操作本地文件的能力 — 方案与考虑

本文档对应 next-plan 中的「提供软硬一体化的解决方案，重点考虑如何让 DHA 具备操作本地文件的功能」与「既然已经有了 file，能不能把 file 放进某个 chat 中，里面的 dha 可以读取或者操作该 file」。

---

## 一、现状小结

### 1.1 已有能力

| 层级 | 能力 | 说明 |
|------|------|------|
| **API** | 文件 CRUD + Workspace | `backend/app/api/files.py`：全局目录 `AGENT_OUTPUTS_DIR`（默认 `./data/agent-outputs`）；Workspace 为 `workspaces/{workspace_id}` 子目录。支持列表、下载、上传、创建/更新/删除/重命名（含 workspace 维度）。 |
| **单聊 (Chat)** | 读文件 + 导出 | 内置工具 `read_file`：按「相对 AGENT_OUTPUTS_DIR 的 path」读文件；用户可在输入中写【文件引用：path】。前端文件选择器用**全局** `/api/files`，无「本会话工作区」概念。导出会话为 .md 到 agent-outputs。 |
| **群聊 (Group)** | 工作区 + 读/写 | `workspace_id = group_session_id`；有 `/api/workspaces/{id}/files` 列表/上传/下载等；输入可插入【文件引用：workspaces/{groupSessionId}/path】。内置 `read_file` + `write_workspace_file`；部分 DHA 带 Filesystem MCP。 |
| **MCP** | Filesystem MCP | 根目录固定为 `./data/agent-outputs`，可读写、列目录、搜索等；所有配置了该 MCP 的 DHA 共享同一根目录，无按会话/workspace 的隔离。 |

### 1.2 能力缺口

- **单聊没有「本会话工作区」**：文件选择器是全局 agent-outputs，无法「把 file 放进某个 chat」并仅在该 chat 内可见/可操作。
- **单聊没有写回能力**：只有 `read_file`，不能像群聊那样把生成内容写入「本会话」下的文件。
- **文件与会话的绑定关系未建模**：没有「会话附件」或「会话关联文件列表」的存储与展示，仅靠用户手动在输入里写【文件引用：path】。
- **MCP 文件范围固定**：若未来要支持「用户本机任意目录」或「按会话隔离」，当前单根目录、单实例的配置不够灵活。

---

## 二、目标与原则

- **目标**：DHA 在对话中能可靠地「读取/操作」与当前会话相关的本地文件，并支持「文件放进某个 chat」的语义。
- **统一模型**：**单聊可逐步被取代、消失**——单聊视为「只有一个人的群聊」。所有会话（无论单人还是多人）统一为：一个会话 = 一个 workspace，文件系统的**根目录按会话隔离**，即每会话仅能访问 `workspaces/{session_id}/` 下的文件。
- **原则**：
  - 安全：操作范围限定在**当前会话的 workspace** 内，禁止路径穿越与跨会话访问。
  - 与现有 Files API、Workspace、read_file/write_workspace_file 对齐，尽量复用；MCP 调用也做会话边界校验。

---

## 三、方案建议

### 3.1 统一为「按会话隔离」的 Workspace（采用）

- **概念**：所有会话（原单聊 + 群聊）统一为「一个 session_id = 一个 workspace」；文件根目录按会话隔离，即 `workspaces/{session_id}/` 为该会话可见/可写的唯一根。
- **后端**：
  - `read_file` / `write_workspace_file` 及所有文件类 MCP 调用：**仅允许** path 落在 `workspaces/{session_id}/` 下（或在传入 path 时做前缀校验与规范化）。
  - 单聊侧：为 `session_id` 提供与群聊相同的 workspace 能力（`write_workspace_file(workspace_id=session_id)`、`/api/workspaces/{session_id}/files` 等）；待单聊被统一入口取代后，逻辑已一致，无需再区分。
- **前端**：
  - 原单聊文件选择器改为「本会话工作区」`/api/workspaces/{session_id}/files`，插入引用为 `workspaces/{session_id}/path`；与群聊一致。后续若单聊入口消失，仅保留「会话（可 1 人可多人）+ 本会话工作区」一套交互即可。
- **效果**：文件系统根目录按会话隔离；「把 file 放进某个 chat」= 放入该会话的 workspace；单聊 = 一人群聊，可逐步被同一套会话模型取代。

### 3.2 会话级「关联文件」与上下文（可选增强）

- **需求**：用户希望「当前对话默认就带着这几个文件」，而不必每次输入都写【文件引用】。
- **做法**：
  - **存储**：在会话元数据（如 `_SESSION_META[session_id]` 或持久化 meta）中增加可选字段，如 `attached_file_paths: List[str]`（相对 AGENT_OUTPUTS_DIR 的路径）。
  - **使用**：在构建发给 LLM 的「当前用户输入」时，若存在 `attached_file_paths`，可在系统提示或首条消息中注入「本会话关联文件：path1, path2, …」并建议先调用 `read_file`；或在前端展示「本会话已关联文件」，方便用户点击插入引用。
  - **前端**：在 Chat 界面提供「关联到本会话」操作（从工作区或全局选择文件加入 `attached_file_paths`），并展示/管理该列表。
- **效果**：文件与 chat 的绑定关系显式化，DHA 在每轮都能感知「本会话可用的文件」，减少用户重复输入引用。

### 3.3 MCP 文件系统与「按会话隔离」

- **物理根目录**：Filesystem MCP 仍使用单一根目录 `./data/agent-outputs`（即 `AGENT_OUTPUTS_DIR`），不按会话起多实例。
- **逻辑按会话隔离**：在**应用层**约束——任何调用 MCP 文件工具时，传入的 path 必须落在当前会话的 workspace 内，即 `workspaces/{session_id}/...`。在调用 MCP 前做路径校验与规范化（若用户/模型传了相对 path，则规范为 `workspaces/{session_id}/xxx`），这样同一 MCP 进程下，不同会话只能读写各自目录。
- **若需「用户本机任意目录」**（软硬一体化、本机执行）：安全风险大，需单独设计（如允许的根目录列表、临时授权与审计）；建议作为后续阶段与「本机执行」一起规划。

### 3.4 安全与权限

- **路径**：所有 path 解析必须限定在配置根目录内，禁止 `..` 与绝对路径越界（当前 `files.py` 与 `read_file` 已做）。
- **写操作**：`write_workspace_file` 仅允许写入当前会话的 workspace 目录；若通过 MCP 写文件，在调用前同样校验 path 属于当前会话 workspace。
- **可见性**：Workspace 按 `workspace_id`（= session_id）隔离；多用户下**仅本人能访问**本人参与的会话的 workspace，API 层统一校验。

---

## 四、实施优先级建议

1. **P0**：统一「按会话隔离」的 workspace（3.1）  
   - 后端：单聊请求为 `session_id` 提供 `write_workspace_file(session_id)`；`read_file` 与 MCP 文件工具均限制 path 在 `workspaces/{session_id}/` 下（应用层校验）。  
   - 前端：单聊文件选择器改为 `/api/workspaces/{session_id}/files`，插入引用为 `workspaces/{session_id}/path`；与群聊一致。

2. **P1**：会话级关联文件（3.2）  
   - 会话 meta 增加 `attached_file_paths`，构建 prompt 时注入；前端支持「关联到本会话」与列表展示。

3. **P2（按需）**：「用户本机目录」与软硬一体化的调研与设计。

---

## 五、与 next-plan 其他条目的关系

- **「用 Group 代替 Chat，但称之为 Chat」**：单聊视为仅一人的群聊并可逐步消失；本方案的文件「按会话隔离」与该统一模型一致，无需再区分单聊/群聊两种文件能力。
- **「MCP 作为隶属于 Skills 的资源」**：文件操作仍由具备 Filesystem MCP 或 file-workspace 类 Skill 的 DHA 暴露；本方案仅在调用 MCP 时增加会话边界校验。

---

## 六、还有哪些问题

在「单聊可被取代、文件根目录按会话隔离」的前提下，实施时还需考虑：

1. **现有单聊会话的迁移与兼容**  
   - 现有单聊使用 `session_id` 与 `_CHAT_HISTORY` / `_SESSION_META`，与「会话 = workspace」一致（workspace_id = session_id）。无需数据迁移；只需在单聊 API 中为同一 `session_id` 挂上 workspace 能力（读写限制在 `workspaces/{session_id}/`）。若日后下线单聊入口，原单聊会话可在统一「会话」列表中按「仅 1 个参与者」展示即可。

2. **MCP 调用的会话上下文**  
   - 当前 MCP 工具由 LangChain/LangGraph 调用，可能未显式传入 `session_id`。需要在工具调用链中注入「当前会话 id」，以便在调用 Filesystem MCP 前对 path 做「仅限 workspaces/{session_id}/」的校验与前缀补全。若 path 已带 `workspaces/xxx/` 前缀，则校验 `xxx == session_id`；若为相对 path，则规范为 `workspaces/{session_id}/xxx`。需确认 chat 与 group_chat 两处调用 MCP 时都能拿到当前 session_id / group_session_id。

3. **全局 /api/files：不保留**  
   - 约定：不保留全局 `/api/files`。所有文件列表、上传、下载、读写均通过「按会话隔离」的 `/api/workspaces/{workspace_id}/files` 进行；导出会话为 .md 等产出也落入该会话的 workspace 内。实施时需下线或迁移依赖全局 `/api/files` 的前端/导出逻辑，统一改为 workspace 接口。

4. **前端与产品：单聊入口的收尾**  
   - 单聊「逐步消失」意味着：要么将现有 Chat 入口改为「创建会话（可选多人）」的统一入口，要么保留两个入口但后端与数据模型已统一（单聊 = 参与人数为 1 的会话）。需产品上明确是「先统一能力、再合并入口」还是「先合并入口、再下线单聊」，以便接口与路由的演进顺序一致。

5. **多用户：仅本人能访问**  
   - 约定：多用户场景下，用户仅能访问本人参与的会话所对应的 workspace（列表、下载、上传、读写均需校验「当前用户 ↔ 该会话」的参与关系）。实施多用户时在 API 层统一做此校验；单机/单用户阶段可暂不实现，但会话与参与人模型需预留「会话 ↔ 用户」关系。

---

以上为「让 DHA 具备操作本地文件功能」的设计与剩余问题清单；确认后即可按 P0→P1 拆成具体任务与接口变更。
