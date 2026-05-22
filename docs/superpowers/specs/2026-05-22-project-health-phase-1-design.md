# 第一阶段项目健康清理设计

状态：待评审

日期：2026-05-22

分支：`codex/project-health-phase-1`

工作区：`/Users/ggd/project/shichai/.worktrees/project-health-phase-1`

## 目标

第一阶段只处理低耦合、证据明确、容易回滚的问题，把项目从“明显脏”和“明显坏”的状态先收紧一轮。

本阶段的优先级不是大规模重构，而是：

1. 降低 Git 噪音和误提交风险。
2. 修复一个前端真实渲染问题。
3. 移除临时调试日志写入。
4. 删除可证明未引用的旧前端代码。
5. 每类变更独立提交，方便按主题回滚。

## 当前证据

### Git 跟踪了大量应忽略产物

在隔离 worktree 中执行：

```bash
/Users/ggd/.local/bin/rtk git ls-files -ci --exclude-standard
```

发现 600+ 个已匹配 `.gitignore`、但仍被 Git 跟踪的文件。代表性类型包括：

- `backend/.env`
- `backend/.cursor/debug.log`
- `backend/config/auth_users.sqlite`
- `backend/data/users/*/agent-outputs/...`
- `1panel-compose-backup.tar.gz`

这些文件不应继续被版本管理，但第一阶段不删除本地文件，只做 `git rm --cached` 级别的索引清理。

### `WorkspaceContent.css` 中的 `:deep()` 不会被 Vue 转换

初始扫描显示：

```bash
/Users/ggd/.local/bin/rtk rg -n ":deep|group-chat-markdown|markdown-body" frontend/src -S
```

其中 `frontend/src/features/workspace/WorkspaceContent.css` 在 `.group-chat-markdown` 下大量使用 `:deep(...)`。这个文件是普通外部 CSS，不是 SFC `<style scoped>`，Vue 不会转换 `:deep()`，浏览器会把这些选择器当作无效选择器处理。结果是群聊 Markdown 内部元素样式可能没有真正生效。

同一次扫描也看到了 `SkillDetailView.vue`、`FileDetailView.vue` 内的 `:deep()`，但这些在 SFC 样式块内，属于不同场景，第一阶段不动。

### `call_api.py` 有临时 agent debug 日志

`backend/app/tools/call_api.py` 在每次入口、成功、超时、异常路径都会写 `backend/.cursor/debug.log`，并带有 `runId: call_api-debug-1` 这类临时调试标记。这个行为会制造本地日志噪音，也会继续推动被跟踪的 debug log 变脏。

### `volces_icon.py` 有硬编码本机调试路径

`backend/app/mcp/stdio/volces_icon.py` 的 `_agent_log()` 写死了：

```text
/Users/ggd/mycode/DHA/.cursor/debug.log
```

这既是开发机路径泄漏，也会让同一份代码在其他机器上表现不一致。第一阶段只移除或显式开关化这类临时调试写入，不重写 Volces MCP 功能。

### 前端存在可证明未引用的旧组件

初始扫描确认这些文件存在：

- `frontend/src/components/LLMConfig.vue`
- `frontend/src/components/MCPConfig.vue`
- `frontend/src/components/SkillsConfig.vue`

同时：

```bash
/Users/ggd/.local/bin/rtk rg -n "components/(LLMConfig|MCPConfig|SkillsConfig)|LLMConfig.vue|MCPConfig.vue|SkillsConfig.vue|<LLMConfig|<MCPConfig|<SkillsConfig" frontend -S
```

没有找到引用。它们可作为第一阶段删除候选。删除前仍要用 TypeScript/Vite 构建验证，避免漏掉动态引用或路径别名导出。

## 范围

### 包含

1. Git 索引清理
   - 只清理已经被 `.gitignore` 命中的 tracked 文件。
   - 只执行 `git rm --cached`，不删除本地文件内容。
   - 把高风险类别分开看待：环境变量、SQLite、本地日志、agent outputs、压缩包。
   - `1panel-compose-backup.tar.gz` 属于用户当前工作区里的本地修改；第一阶段设计允许从 Git 索引中移除它，但不会删除文件，也不会纳入无关内容修改。

2. Markdown 样式修复
   - 只改 `frontend/src/features/workspace/WorkspaceContent.css` 中 `.group-chat-markdown :deep(...)` 选择器。
   - 将其转换为普通后代选择器，例如 `.group-chat-markdown p`、`.group-chat-markdown pre code`。
   - 不碰 SFC 内合法的 `:deep()` 用法。

3. 临时调试日志清理
   - 移除 `call_api.py` 中写 `.cursor/debug.log` 的 `#region agent log` 块。
   - 移除或显式环境变量开关化 `volces_icon.py` 的 `_agent_log()`，默认不写本机 debug 文件。
   - 保留正常错误返回和现有用户提示，不改变工具对外契约。

4. 明确未引用前端代码删除
   - 删除 `frontend/src/components/LLMConfig.vue`、`MCPConfig.vue`、`SkillsConfig.vue`，前提是最终引用扫描和构建均通过。
   - 继续审计 `frontend/src/api/index.ts`、`frontend/src/api/files.ts`、`frontend/src/api/settings.ts` 这类旧 API facade；只有在确认没有导入且构建无影响时才删除。

### 不包含

- 不做大规模后端架构重构。
- 不调整 OpenSandbox、Skill runtime、group chat 调度等高风险主链路逻辑。
- 不改业务数据模型。
- 不删除用户本地实际文件，只调整 Git 跟踪状态。
- 不推送远端分支，除非用户后续明确要求。

## 设计决策

### Git 交付策略

第一阶段继续保持主题化提交，预期提交形态：

1. `chore: 清理已忽略的运行产物索引`
2. `fix: 修复群聊 Markdown 样式选择器`
3. `chore: 移除临时调试日志写入`
4. `chore: 删除未引用的前端旧组件`

每个提交后做：

```bash
/Users/ggd/.local/bin/rtk git show --stat --name-only HEAD
/Users/ggd/.local/bin/rtk git status --short
```

确保提交边界清楚，回滚时可以只 revert 单个主题提交。

### Git 索引清理方式

索引清理不做 `rm`，只做：

```bash
/Users/ggd/.local/bin/rtk git rm --cached <path>
```

大批量路径需要先生成待清理清单，并人工按类别审阅。尤其是 `backend/.env`、SQLite、用户 `agent-outputs`、压缩包这几类，必须在提交说明中写明“仅取消跟踪，不删除本地文件”。

### CSS 修复方式

`WorkspaceContent.css` 是全局 CSS 文件，不能依赖 Vue SFC scoped transform。转换规则：

- `.group-chat-markdown :deep(p)` -> `.group-chat-markdown p`
- `.group-chat-markdown :deep(> *)` -> `.group-chat-markdown > *`
- `.group-chat-markdown :deep(.group-chat-tool-call[open] .group-chat-tool-call-summary)` -> `.group-chat-markdown .group-chat-tool-call[open] .group-chat-tool-call-summary`

这个修改应该是纯 CSS 选择器等价修复，不改变类名和 DOM 结构。

### 调试日志修复方式

`call_api.py` 的调试写文件是临时代码，应直接删除。已有测试 `backend/tests/test_call_api_tool.py` 覆盖 call_api 的 SSRF、URL 自动补 scheme、超时、HTML 回退、JSON 入参等行为，适合作为回归验证。

`volces_icon.py` 如果仍需要本地诊断，应改为默认关闭的环境变量开关，并使用仓库相对路径或标准 logger；不能保留 `/Users/ggd/...` 绝对路径。

### 前端旧代码删除方式

删除前做三层验证：

1. `rg` 文件名、组件名、标签名、导入路径。
2. `npm run build`。
3. 如项目脚本可用，补跑 `vue-tsc` 或现有类型检查脚本。

如果发现某个 API facade 虽无直接导入但作为聚合出口被外部约定使用，则本阶段不删除，只记录为后续审计项。

## 验证计划

最低验证集：

```bash
/Users/ggd/.local/bin/rtk conda run -n st49 python -m pytest backend/tests/test_call_api_tool.py -q
/Users/ggd/.local/bin/rtk npm --prefix frontend run build
/Users/ggd/.local/bin/rtk git ls-files -ci --exclude-standard
/Users/ggd/.local/bin/rtk git status --short
```

如果前端删除范围扩大，再补：

```bash
/Users/ggd/.local/bin/rtk npm --prefix frontend run build
```

当前 `frontend/package.json` 的 `build` 脚本已经包含 `vue-tsc && vite build`，所以单独类型检查可以复用这个脚本，不临时引入新工具链。

## 回滚策略

回滚粒度按主题提交控制：

- Git 索引清理出问题：revert `chore: 清理已忽略的运行产物索引`，文件会重新进入版本控制，但本地内容不会因为第一阶段被删除。
- CSS 修复出问题：revert `fix: 修复群聊 Markdown 样式选择器`。
- 调试日志清理出问题：revert `chore: 移除临时调试日志写入`。
- 前端旧代码删除出问题：revert `chore: 删除未引用的前端旧组件`。

此外，本阶段所有实现工作都在 `codex/project-health-phase-1` 分支和 `.worktrees/project-health-phase-1` worktree 中进行。主工作区当前的 `1panel-compose-backup.tar.gz` 本地修改不会被带入实现提交。

## 待确认

1. 是否同意第一阶段按上述四个主题提交推进。
2. `1panel-compose-backup.tar.gz` 是否允许在“Git 索引清理”提交中取消跟踪；这不会删除当前工作区里的文件，但会使它后续作为本地产物存在。
3. 如果 `frontend/src/api/*` 里出现“未引用但可能是预留公共出口”的文件，第一阶段默认保守跳过，只删除确定无引用的组件。
