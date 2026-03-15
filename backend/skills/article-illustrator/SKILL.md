---
description: 分析文章结构，识别需要配图的位置，按「类型×风格」生成配图方案并产出插图。类型含 infographic、scene、flowchart、comparison、framework、timeline；风格含 notion、elegant、warm、minimal、blueprint、watercolor、editorial、scientific。当用户说「给文章配图」「为文章加图」「生成配图」时使用。灵感来自 baoyu-skills/baoyu-article-illustrator。
enabled: true
mcp_server_ids: []
name: 文章配图
---

# 文章配图

分析文章，确定适合插图的位置，按**类型 × 风格**统一生成配图方案与插图。

## 何时使用

- 用户说「给这篇文章配图」「为文章加插图」「生成配图」
- 用户提供文章路径或内容，希望增加信息图、场景图、流程图等

## 两个维度

| 维度 | 控制 | 示例 |
|------|------|------|
| **类型 Type** | 信息结构 | infographic, scene, flowchart, comparison, framework, timeline |
| **风格 Style** | 视觉风格 | notion, elegant, warm, minimal, blueprint, watercolor, editorial, scientific |

可自由组合，如：`类型=infographic` + `风格=blueprint`。

## 类型（何时用哪种）

| 类型 | 适用 |
|------|------|
| infographic | 数据、指标、技术说明 |
| scene | 叙事、情绪、氛围 |
| flowchart | 流程、步骤、工作流 |
| comparison | 对比、前后、选项 |
| framework | 模型、架构、概念关系 |
| timeline | 时间线、演变、历程 |

## 风格（视觉）

| 风格 | 说明 | 适用 |
|------|------|------|
| notion（默认） | 简约手绘线稿 | 知识分享、SaaS、效率 |
| elegant | 精致、偏商务 | 商业、观点 |
| warm | 亲和、易读 | 成长、生活 |
| minimal | 极简 | 哲学、极简主题 |
| blueprint | 技术示意图 | 架构、系统 |
| watercolor | 水彩感 | 生活、旅行、创意 |
| editorial | 杂志信息图风 | 科技解读、报道 |
| scientific | 学术图表风 | 生物、化学、技术 |

## 工作流程

### 1. 预检与偏好

- 若项目或用户有配图偏好（类型/风格/密度），先读取或询问。

### 2. 分析内容

- **内容类型**：技术文 / 教程 / 方法论 / 叙事
- **目的**：信息传达 / 数据可视化 / 情境想象
- **核心论点**：2–5 个主点
- **配图位置**：哪些段落或小节需要图、每张图要解决什么问题

**重要**：隐喻要画「概念本身」，不要画字面场景（例如「知识金字塔」画层级结构，不画 literal 金字塔）。

### 3. 确认设置

与用户确认（可一次问完）：

- **类型**：推荐一个主类型，或 mixed（多类型）；可选 infographic / scene / flowchart / comparison / framework / timeline / mixed
- **密度**：minimal（1–2 张）、balanced（3–5 张）、per-section（每节一张，推荐）、rich（6+）
- **风格**：从上面风格表选一，或由你推荐
- **语言**：图内文字与文章语言一致

### 4. 生成配图大纲

在输出目录下写 `outline.md`，包含 frontmatter（type, density, style, image_count）及每条配图：

```yaml
## Illustration 1
**Position**: [段落/小节]
**Purpose**: [为何需要这张图]
**Visual Content**: [画什么]
**Filename**: 01-infographic-概念名.png
```

按顺序列出所有计划生成的图。

### 5. 生成图像

- **先写 prompt**：为每张图写结构化 prompt（含 ZONES/LABELS/COLORS/STYLE/比例等），LABELS 必须用文章里的真实数据、术语、指标，不要泛泛而谈。
- **再出图**：使用本项目的图片生成能力，按 prompt 依次生成，保存为 `NN-{type}-{slug}.png`。**必须**使用以下方式：
    **CLI（推荐）**：调用工具 `run_skill_script`，`script_path=generate_image.py`，`input_json` 为 `{"description": "该张图的 prompt 内容", "pic_size": "1024x1024"}`。
- **禁止使用 call_api 生图**：不要用 `call_api` 请求 example.com、任意 URL 或“假设的接口”来生成图片；生图只能通过上述 run_skill_script 或 MCP 图像工具。
- 若用户启用水印等设置，在生成后按规则添加。

**禁止**：在未保存 prompt 文件前就用临时随口写的 prompt 直接生图；必须用类型化、结构化的 prompt 模板。

### 6. 收尾

- 在文章对应位置插入 `![描述](path/NN-{type}-{slug}.png)`。
- 向用户汇报：文章路径、类型、密度、风格、成功张数（如 5/6）。


## 修改与增删

- **改某张图**：改对应 prompt → 重新生成 → 更新文章中的引用。
- **新增图**：在 outline 中增加条目 → 写 prompt → 生成 → 更新 outline 与正文。
- **删除图**：删文件、从 outline 和正文中去掉引用。
