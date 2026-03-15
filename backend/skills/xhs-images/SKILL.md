---
description: 将内容拆成 1～10 张小红书风格的信息图系列。支持风格（cute/fresh/warm/bold/minimal/retro/pop/notion/chalkboard/study-notes/screen-print）与版式（sparse/balanced/dense/list/comparison/flow/mindmap/quadrant），可组合或使用预设（如 knowledge-card、checklist、poster）。当用户提到「小红书图片」「XHS 配图」「小红书种草」「 RedNote 信息图」或需要中文社交平台用图时使用。灵感来自 baoyu-skills/baoyu-xhs-images。
enabled: true
mcp_server_ids:
  - volces-icon
name: 小红书信息图系列
---

# 小红书信息图系列

把一段内容拆成多张适合小红书传播的卡通风格信息图，按**风格 × 版式**统一呈现。

## 何时使用

- 用户说「做小红书图」「XHS 配图」「小红书种草图」「 RedNote 信息图」
- 用户提供文章或要点，希望得到一套可发小红书的图
- 在博客协作流程中，与 cover-image、article-illustrator 并列，由「博客封面与配图专家」在需要小红书风格系列图时选用

## 两个维度

| 维度 | 控制 | 选项 |
|------|------|------|
| **风格 Style** | 视觉：配色、线条、装饰 | cute, fresh, warm, bold, minimal, retro, pop, notion, chalkboard, study-notes, screen-print |
| **版式 Layout** | 信息结构：密度与排布 | sparse, balanced, dense, list, comparison, flow, mindmap, quadrant |

可自由组合，如 `--style notion --layout dense`；也可用预设一次定风格+版式（见下）。

## 风格简表

| 风格 | 说明 |
|------|------|
| cute（默认） | 甜美、少女风、经典小红书感 |
| fresh | 清爽、自然 |
| warm | 温暖、亲切 |
| bold | 高对比、抓眼球 |
| minimal | 极简、偏专业 |
| retro | 复古、怀旧 |
| pop | 鲜艳、活泼 |
| notion | 简约手绘线稿、知识感 |
| chalkboard | 黑板粉笔、教育风 |
| study-notes | 手写笔记感、蓝笔+红批注+黄高亮 |
| screen-print | 海报风、半色调、限色、符号化 |

## 版式简表

| 版式 | 信息量 | 适用 |
|------|--------|------|
| sparse | 1–2 点 | 封面、金句 |
| balanced | 3–4 点 | 常规内容 |
| dense | 5–8 点 | 知识卡、干货 |
| list | 4–7 条 | 清单、排行 |
| comparison | 左右对比 | 前后/利弊 |
| flow | 3–6 步 | 流程、时间线 |
| mindmap | 4–8 分支 | 概念图、脉络 |
| quadrant | 四象限/分块 | SWOT、分类 |

## 预设（风格+版式一键）

**知识/学习**：knowledge-card（notion+dense）、checklist（notion+list）、concept-map（notion+mindmap）、swot（notion+quadrant）、tutorial（chalkboard+flow）、classroom（chalkboard+balanced）、study-guide（study-notes+dense）。

**生活/分享**：cute-share（cute+balanced）、girly（cute+sparse）、cozy-story（warm+balanced）、product-review（fresh+comparison）、nature-flow（fresh+flow）。

**观点/冲击**：warning（bold+list）、versus（bold+comparison）、clean-quote（minimal+sparse）、pro-summary（minimal+balanced）。

**怀旧/趣味**：retro-ranking（retro+list）、throwback（retro+balanced）、pop-facts（pop+list）、hype（pop+sparse）。

**海报/编辑**：poster（screen-print+sparse）、editorial（screen-print+balanced）、cinematic（screen-print+comparison）。

## 内容与版式策略

- **故事驱动**：从痛点→发现→体验→结论，适合测评、个人分享、转变故事。
- **信息密集**：结论先行、信息卡、利弊、推荐，适合教程、对比、清单。
- **视觉优先**：大图、氛围、少字，适合高颜值产品、生活方式、情绪向。

根据用户内容判断用哪种策略，再选风格与版式（或预设）。

## 工作流程

1. **输入**：文章路径或用户粘贴的内容；必要时保存为 `source.md`。
2. **分析**：主题、核心信息点、目标读者（小红书为主）、适合的预设或风格×版式。
3. **确认**：向用户推荐 1 个预设或「风格 + 版式」组合，或让用户自选。
4. **大纲**：将内容拆成 1–10 张图，每张对应一个文件条目标题、要点、版式说明（如「第 1 张：封面 sparse」「第 2–4 张：list 清单」）。保存为 `outline.md`。
5. **Prompt 与出图**：为每张图写结构化 prompt（风格、版式、文案、配色、禁止项），保存到 `prompts/NN-{slug}.md`，再调用本项目图像生成能力依次生成 `01-xxx.png` …，放入统一输出目录（如 `xhs-images/{内容-slug}/`）。推荐 **CLI 方式**：调用 `run_skill_script`，`script_path=generate_image.py`，`input_json` 为 `{"description": "该张图的 prompt 内容", "pic_size": "1024x1024"}`；API Key 与 MCP 相同：环境变量 **VOLCES_IMAGE_API_KEY**（在 `backend/.env` 中配置，格式可为 `Bearer xxx` 或仅 `xxx`）。
6. **收尾**：给用户图列表与路径，并简要说明每张图用途（封面/要点/对比/流程等）。

## 输出目录结构

```
xhs-images/{content-slug}/
├── source-{slug}.md（可选）
├── outline.md
├── prompts/
│   └── NN-{slug}.md
└── 01-xxx.png … 0N-xxx.png
```

## 自动选择参考

- 美妆/时尚/少女/粉色 → cute，sparse/balanced，预设 cute-share、girly
- 健康/自然/清爽/有机 → fresh，balanced/flow，product-review、nature-flow
- 生活/故事/情感/温暖 → warm，balanced，cozy-story
- 警告/重要/必读/关键 → bold，list/comparison，warning、versus
- 专业/商务/简约 → minimal，sparse/balanced，clean-quote、pro-summary
- 知识/概念/效率/SaaS → notion，dense/list，knowledge-card、checklist
- 教育/教程/课堂 → chalkboard，balanced/flow，tutorial、classroom
- 电影/海报/观点/戏剧 → screen-print，sparse/comparison，poster、editorial、cinematic
