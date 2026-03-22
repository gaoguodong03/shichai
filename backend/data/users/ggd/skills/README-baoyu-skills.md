# 写作相关 Skills（来自 baoyu-skills 接入）

本目录中下列技能参考了 [JimLiu/baoyu-skills](https://github.com/JimLiu/baoyu-skills) 的写作类 skill，按本项目 SKILL.md 格式与工作流改写，供 DHA Agent 使用。

## 已接入技能一览

| 目录名 | 名称 | 对应 baoyu-skills | 说明 |
|--------|------|-------------------|------|
| `format-markdown` | Markdown 格式化 | baoyu-format-markdown | 分析→frontmatter/标题/摘要→排版→输出 -formatted.md，typography 可结合脚本或建议用户本地跑 baoyu |
| `article-translate` | 文章翻译 | baoyu-translate | 三模式（quick/normal/refined）、受众/风格/术语表、长文分块 |
| `markdown-to-html` | Markdown 转 HTML（微信风格） | baoyu-markdown-to-html | 主题/颜色/引用模式说明；实际转换可调用脚本或建议用户使用 baoyu |
| `article-illustrator` | 文章配图 | baoyu-article-illustrator | 类型×风格、配图大纲、prompt 模板、与现有图像生成能力配合 |
| `cover-image` | 文章封面图 | baoyu-cover-image | 五维（类型/色板/渲染/文字/情绪）、比例、构图原则 |
| `xhs-images` | 小红书信息图系列 | baoyu-xhs-images | 风格×版式、预设、多张图拆分与生成 |

## 使用说明

- 各技能的 **触发条件** 见各自 `SKILL.md` 的 frontmatter `description`，Agent 会根据描述做技能选择与路由。
- 需要**跑脚本**时（如 typography、md2html），若本技能下存在 `scripts/` 且符合 `run_skill_script` 规范，会优先调用；否则技能内会说明可建议用户在本机使用 baoyu-skills 或其它工具完成对应步骤。
- **图像生成**（封面、配图、小红书图）依赖项目已配置的 MCP 图像工具或 `run_skill_script` 可调用的生图脚本；若尚未配置，技能会完成 prompt 与大纲，用户可自行用其它方式出图。

## 与 baoyu-skills 的差异

- 不依赖 bun/npx 或 baoyu 的 TypeScript 脚本；工作流以「Agent 按 SKILL 说明执行」为主。
- 可选配置（如 EXTEND.md）改为在技能正文中说明「可选偏好」或「与用户确认」即可，无需固定路径。
- 输出目录、文件命名与 baoyu 保持一致或接近，便于用户对照 [baoyu-skills 文档](https://github.com/JimLiu/baoyu-skills) 或后续把产出交给 baoyu 脚本做后续处理。
