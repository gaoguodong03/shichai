---
description: 为文章生成封面图。支持五维定制：类型（hero/conceptual/typography/metaphor/scene/minimal）、色板（warm/elegant/cool/dark/earth/vivid/pastel/mono/retro）、渲染（flat-vector/hand-drawn/painterly/digital/pixel/chalk）、文字（无/仅标题/标题+副标题/多文字）、情绪（subtle/balanced/bold）。支持
  16:9、2.35:1、1:1 等比例。当用户说「生成封面」「做文章封面」「封面图」时使用。灵感来自 baoyu-skills/baoyu-cover-image。
enabled: true
mcp_server_ids: []
name: 文章封面图生成器
---
# 文章封面图

根据文章内容或用户描述，生成适合的封面图，支持多维度组合。

## 何时使用

- 用户说「生成封面」「做文章封面」「封面图」「给这篇文章做个封面」
- 用户提供文章路径或粘贴内容，并希望得到一张封面图

## 五个维度

| 维度 | 选项 | 默认 |
|------|------|------|
| **类型 Type** | hero, conceptual, typography, metaphor, scene, minimal | 按内容自动 |
| **色板 Palette** | warm, elegant, cool, dark, earth, vivid, pastel, mono, retro, duotone | 按内容自动 |
| **渲染 Rendering** | flat-vector, hand-drawn, painterly, digital, pixel, chalk, screen-print | 按内容自动 |
| **文字 Text** | none, title-only, title-subtitle, text-rich | title-only |
| **情绪 Mood** | subtle, balanced, bold | balanced |

可选**字体**：clean（无衬线）、handwritten、serif、display。**比例**：16:9（默认）、2.35:1、4:3、3:2、1:1、3:4。

**快捷**：用户可指定 `--quick` 跳过确认，由你根据内容自动选维度；或指定 `--style blueprint` 等预设（即固定 palette + rendering 组合）。

## 工作流程

### 1. 分析内容与参考图

- 若用户提供参考图，在工作区输出目录下建 `refs/` 保存（或仅记录路径），并在写 prompt 时引用（风格/构图/色调等）。
- 若用户粘贴内容，在工作区保存为 `source.md`。
- 分析：主题、语气、关键词、可用的视觉隐喻；检测标题语言（中/英/日等）。

**重要**：所有产出（prompt 文件、生成的图片）**只写入用户工作区**（当前项目目录或用户指定目录），**不要写入 skill 目录**。

### 2. 确认选项（非 quick 时）

与用户确认：类型、色板、渲染、文字量、情绪、字体、比例。若用户已全部指定或使用 `--quick`，可跳过确认。

### 3. 写封面 prompt（写入工作区）

- **输出目录**：在用户工作区内，例如 `cover-image/{主题-slug}/` 或用户指定的子目录；slug 建议 2–4 词 kebab-case。若工作区写入不可用，则把 prompt 内容直接呈现在对话中供用户保存。
- 在该目录下创建 `prompts/cover.md`（或等价路径），内容包含：
  - 类型、色板、渲染、文字（是否含标题/副标题）、情绪、比例
  - 从文章提取的**准确标题**（若 text 非 none），不得杜撰
  - 构图要点：留白 40–60%、主视觉居中或偏左、人物用简笔剪影勿写实
  - 若有参考图，在 frontmatter 或正文中写明如何用（direct 传图 / style 提取描述）

### 4. 生成图片（CLI，唯一方式）

- **本技能要求使用 run_skill_script 调用 `scripts/generate_image.py` 生成封面图**；脚本在自带环境中执行并内部调用 ChatAnywhere 图像 API，**不要使用 call_api 工具**做图片生成。
- **调用方式**：`run_skill_script`，`script_path=generate_image.py`，`input_json` 为 JSON 字符串：`{"description": "从 cover.md 提炼的提示词", "pic_size": "1024x1024"}`（比例 16:9 用 `1024x576` 等）。脚本读取环境变量 **CHATANYWHERE_IMAGE_API_KEY**（在 `backend/.env` 中配置，格式 `Bearer sk-xxx` 或仅 `sk-xxx`）。工具返回的 stdout 为图片 URL 或错误信息。
- 若已有 `cover.png` 且为重新生成，先备份再覆盖。失败时重试一次。
- 生成的图片保存到工作区同一输出目录下的 `cover.png`。

### 5. 完成报告

向用户汇报：主题、类型/色板/渲染/文字/情绪/字体/比例、标题或「纯视觉」、输出路径、涉及参考图数量。

## 构图原则

- 留白充足（约 40–60%）
- 主元素作为视觉锚点（居中或偏左）
- 人物用简化剪影，避免写实人脸
- 标题必须与用户/文章一致，不得编造

## 输出目录结构（均在用户工作区内）

```
<工作区>/cover-image/{topic-slug}/
├── source-{slug}.md（若有粘贴内容）
├── refs/（若有参考图）
├── prompts/cover.md
└── cover.png
```

若无法写入工作区，则至少把 `prompts/cover.md` 的完整内容输出到对话，并说明「请将上述 prompt 保存后，使用 run_skill_script（generate_image.py）或图片生成 MCP 生成 cover.png」。

## 修改与重做

- **改某一维**：在工作区中更新 `prompts/cover.md` 后，再次调用 run_skill_script（generate_image.py）或图片生成 MCP 生成，并备份原 `cover.png`。
- **换参考图**：更新 refs 与 prompt 中的引用说明后，再调用 MCP 生成。
