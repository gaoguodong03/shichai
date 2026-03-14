---
description: 文章与文档的多语言翻译。支持三种模式：quick（直接翻译）、normal（先分析再翻译）、refined（分析→翻译→审校→润色）。可配合术语表与受众/风格设定。当用户说「翻译」「精翻」「快翻」「翻译成中文/英文」「改成中文」或提供文件/URL 并带翻译意图时使用。灵感来自 baoyu-skills/baoyu-translate。
enabled: true
mcp_server_ids:
  - fetch
  - file-reader
name: 文章翻译
---

# 文章翻译

三模式翻译：**quick** 直接翻译；**normal** 先分析再翻译；**refined** 分析→翻译→审校→润色，适合出版级。

## 何时使用

- 用户明确要求翻译文件、URL 或粘贴内容
- 用户说「翻译一下」「精翻」「快翻」「改成中文/英文」「本地化」
- 用户提供链接或文件并带有翻译意图

## 模式选择

| 模式 | 步骤 | 适用场景 |
|------|------|----------|
| **quick** | 直接翻译 | 短文、非正式、赶时间 |
| **normal**（默认） | 分析 → 翻译 | 文章、博客、一般内容 |
| **refined** | 分析 → 翻译 → 审校 → 润色 | 出版级、重要文档 |

**推断**：「快翻」「直接翻译」→ quick；「精翻」「出版质量」「润色」→ refined；其余 → normal。normal 完成后可提示：「若要继续审校润色，请回复『继续润色』或 refine。」

## 输出目录与文件

- 将源材料统一到一个可用的 Markdown 文件（本地路径或从 URL 抓取后保存）。
- 输出目录：`{源所在目录}/{源 basename}-{目标语言}/`。
- 文件约定：
  - `translation.md`：最终译文（始终此名）
  - `01-analysis.md`：normal/refined 的内容分析
  - `02-prompt.md`：翻译指令与上下文（含风格、术语、理解难点）
  - refined 模式还可有：`03-draft.md`、`04-critique.md`、`05-revision.md`
  - 长文分块时可用 `chunks/` 存放分块与分块译文

## 翻译原则（所有模式通用）

- **准确第一**：事实、数据、逻辑与原文一致
- **达意优先**：按作者意图翻译，可调整句式以符合目标语习惯；比喻、习语按含义译，不必字面直译
- **情感一致**：保留用词的情绪色彩（如「alarming」「haunting」需在目标语中产生相近感受）
- **术语统一**：使用约定译法；首次出现可「译文（原文）」；根据受众调整注释量（技术读者少注，大众读者多注）
- **保留格式**：标题、加粗、列表、图片、链接、代码块等 Markdown 保持
- **Frontmatter**：若有 YAML frontmatter，源相关字段可加 source 前缀（如 url→sourceUrl），正文相关字段翻译后写入；其他字段按需翻译
- **译者注**：对目标读者可能不懂的术语、文化点、专业概念，在词后括号内简短解释（格式如：`译文（English term，通俗解释）`），按受众控制密度

## 可选参数（可来自用户一句话或后续确认）

- **目标语言** `--to`：默认 zh-CN，可为 en、ja 等
- **源语言** `--from`：不指定则自动检测
- **受众** `--audience`：general（默认）、technical、academic、business，或自定义描述
- **风格** `--style`：storytelling（默认）、formal、technical、literal、academic、business、humorous、conversational、elegant，或自定义
- **术语表**：用户可提供词条或文件，在分析/翻译时统一使用

## 受众预设

| 值 | 说明 |
|----|------|
| general | 普通读者，术语可多注 |
| technical | 开发者/工程师，常见技术词少注 |
| academic | 学者，正式、术语精确 |
| business | 商务场景，简洁、结果导向 |

## 风格预设

| 值 | 说明 |
|----|------|
| storytelling | 叙述流畅、易读（默认） |
| formal | 正式、结构清晰 |
| technical | 简洁、偏文档风 |
| literal | 尽量贴近原文结构 |
| academic | 学术、严谨 |
| business | 简洁、行动导向 |
| humorous | 保留并适配幽默 |
| conversational | 口语化、友好 |
| elegant | 文笔考究 |

## 工作流程概要

### Quick 模式

直接翻译整篇 → 保存为输出目录下的 `translation.md`。仍遵守上述翻译原则（达意、情感、句式自然）。

### Normal 模式

1. **分析** → 写出 `01-analysis.md`（领域、语气、受众、术语、理解难点、比喻与隐喻映射）
2. **组 prompt** → 写出 `02-prompt.md`（翻译指令 + 风格 + 术语 + 难点）
3. **翻译** → 按 02-prompt 生成 `translation.md`
4. 完成后提示用户可回复「继续润色」进入审校润色（与 refined 的后续步骤一致）

### Refined 模式

1. 分析 → `01-analysis.md`
2. 组 prompt → `02-prompt.md`
3. 初稿 → `03-draft.md`
4. 审校 → `04-critique.md`（只诊断：准确度、欧化、策略执行、表达问题）
5. 修订 → `05-revision.md`（按审校修改）
6. 润色定稿 → `translation.md`

### 长文处理（normal/refined）

当篇幅超过约 4000 词时：

1. 先通篇提取专有名词、术语、重复短语，形成会话内术语表
2. 按 Markdown 块边界分块（尽量不破坏标题、列表、代码块）
3. 每块翻译时共用同一套 `02-prompt.md`（风格、术语、难点），保证术语一致
4. 合并各块为 `03-draft.md`（refined）或直接 `translation.md`（normal），再做后续审校/润色（若有）

## 完成输出

- 最终译文路径：`{输出目录}/translation.md`
- 若有文内引用的图片且可能含源语言文字，在文末简短列出「可能需要本地化的图片」清单，不自动改图除非用户要求
- 向用户汇报：模式、源→目标语言、输出目录、术语条数等
