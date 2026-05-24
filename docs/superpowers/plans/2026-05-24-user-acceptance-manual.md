# 上线验收操作手册实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [x]`）语法来跟踪进度。

**目标：** 生成面向验收人员的图文版《书童四九上线验收操作手册》，并交付 Markdown 源文档、截图资源和 PDF。

**架构：** 不修改产品代码。通过本地运行系统、浏览器真实操作、截图标注、Markdown 编排和 PDF 导出，形成可维护的仓库文档。敏感信息在截图和正文中不明文展示。

**技术栈：** Vue/Vite 前端、FastAPI 后端、Codex Browser/Playwright 浏览器操作、Markdown、截图标注脚本、PDF 导出工具。

---

## 文件结构

- 创建：`docs/user-manual/README.md`，图文验收操作手册源文档。
- 创建：`docs/user-manual/images/`，存放截图和标注图。
- 创建：`docs/user-manual/书童四九上线验收操作手册.pdf`，验收人员分发版 PDF。
- 创建：`docs/user-manual/assets/`，如需要，存放 PDF 样式或导出辅助资源。
- 创建：`docs/superpowers/plans/2026-05-24-user-acceptance-manual.md`，本实施计划。

## 任务 1：准备文档目录和执行环境

**文件：**
- 创建：`docs/user-manual/README.md`
- 创建：`docs/user-manual/images/`
- 创建：`docs/user-manual/assets/`

- [x] **步骤 1：创建目录**

运行：

```bash
mkdir -p docs/user-manual/images docs/user-manual/assets
```

预期：目录存在。

- [x] **步骤 2：检查本地依赖**

运行：

```bash
command -v npx >/dev/null 2>&1
node --version
npm --version
```

预期：`npx`、`node`、`npm` 可用。

## 任务 2：启动或确认本地服务

**文件：**
- 读取：`backend/README.md`
- 读取：`frontend/README.md`

- [x] **步骤 1：确认后端启动方式**

运行：

```bash
cd backend
conda run --no-capture-output -n st49 python -m app.main
```

预期：后端监听 `http://127.0.0.1:8000`。

- [x] **步骤 2：确认前端启动方式**

运行：

```bash
cd frontend
npm run dev -- --host 127.0.0.1
```

预期：前端监听 `http://127.0.0.1:5173` 或 Vite 输出的备用端口。

- [x] **步骤 3：浏览器打开前端**

访问：

```text
http://127.0.0.1:5173
```

预期：出现登录页或已登录后的主界面。

## 任务 3：准备验收账号和演示数据

**文件：**
- 修改：运行时数据，不提交。

- [x] **步骤 1：登录验收账号**

使用本地验收账号 `ggd@bupt.edu.cn` 登录。密码只在本地输入，不写入文档。

预期：登录成功进入主界面。

- [x] **步骤 2：配置模型**

在资源中心或设置入口创建/确认 `jeniya` 模型配置。API Key 使用本地测试值，截图和正文不展示明文。

预期：模型配置可保存，列表或详情页可见 `jeniya`。

- [x] **步骤 3：创建演示数据**

统一使用以下命名：

```text
验收会话
问答验收场景
问答专家
问答技能
验收工具
```

预期：核心路径有可复用演示数据。

## 任务 4：浏览器截图和标注

**文件：**
- 创建：`docs/user-manual/images/*.png`

- [x] **步骤 1：截取登录与账号入口**

截图：

```text
login-page.png
register-page.png
```

预期：覆盖登录、注册、登出后重登入口。

- [x] **步骤 2：截取工作空间路径**

截图：

```text
workspace-overview.png
workspace-new-session.png
workspace-message-reply.png
workspace-member-file.png
```

预期：覆盖会话、发问、回复、专家邀请和文件引用。

- [x] **步骤 3：截取资源中心路径**

截图：

```text
resources-scenario.png
resources-expert.png
resources-skill.png
resources-tool.png
resources-model.png
resources-files.png
```

预期：覆盖场景、专家、技能、工具、模型、文件。

- [x] **步骤 4：截取设置中心路径**

截图：

```text
settings-host.png
settings-secret.png
settings-sandbox.png
settings-account-theme.png
```

预期：覆盖主持人、密钥、沙箱、账号和配色。

- [x] **步骤 5：截取分享导入路径**

截图：

```text
share-preview.png
share-import-result.png
```

预期：覆盖分享预览、确认导入和导入后检查。

- [x] **步骤 6：标注和打码**

对关键按钮区域加编号；对密码、密钥、真实地址等敏感信息打码。

预期：所有写入手册的图片可直接对外给验收人员查看。

## 任务 5：编写 Markdown 手册

**文件：**
- 创建/修改：`docs/user-manual/README.md`

- [x] **步骤 1：写入手册总说明**

包含适用对象、范围、前置条件、敏感信息说明和通用判定标准。

- [x] **步骤 2：逐章写入核心路径**

每章采用固定结构：

```md
### 验收目标
### 前置条件
### 页面截图
### 按钮和区域说明
### 操作步骤
### 预期结果
### 不通过判定
```

- [x] **步骤 3：写入验收记录表**

表格字段：

```text
编号、验收路径、操作人、验收日期、结果、问题记录
```

## 任务 6：导出 PDF

**文件：**
- 创建：`docs/user-manual/书童四九上线验收操作手册.pdf`

- [x] **步骤 1：选择可用导出工具**

优先使用仓库或本地已有 Markdown/PDF 工具；如果没有，则使用浏览器打印 HTML 或 Python 文档库生成。

- [x] **步骤 2：导出 PDF**

输入：`docs/user-manual/README.md`

输出：`docs/user-manual/书童四九上线验收操作手册.pdf`

预期：PDF 可打开，图片清晰，章节完整。

## 任务 7：验证和提交

**文件：**
- 验证：`docs/user-manual/README.md`
- 验证：`docs/user-manual/images/*.png`
- 验证：`docs/user-manual/书童四九上线验收操作手册.pdf`

- [x] **步骤 1：检查图片引用**

运行：

```bash
rg -o 'images/[^)]+' docs/user-manual/README.md
```

预期：列出的图片文件都存在。

- [x] **步骤 2：检查敏感信息**

运行：

```bash
rg -n '明文密码|API Key 明文|password|密码：|密钥：' docs/user-manual
```

预期：没有命中明文密码或密钥。

- [x] **步骤 3：检查 PDF 文件**

运行：

```bash
ls -lh docs/user-manual/书童四九上线验收操作手册.pdf
```

预期：PDF 文件存在且大小非零。

- [x] **步骤 4：提交**

运行：

```bash
git add docs/superpowers/plans/2026-05-24-user-acceptance-manual.md docs/user-manual
git commit -m "docs: 生成上线验收操作手册"
```
