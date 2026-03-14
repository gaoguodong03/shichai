---
description: 将 Markdown 转为适合微信公众号等场景的样式化 HTML。支持主题（default/grace/simple/modern）、主色、代码高亮、可选外链转文末引用。当用户要求「markdown
  转 html」「md 转 html」「微信排版」「外链转底部引用」或需要从 Markdown 生成样式 HTML 时使用。
enabled: true
mcp_server_ids:
  - filesystem
name: Markdown 转 HTML（微信风格）
---
# Markdown 转 HTML（微信风格）

把 Markdown 转为带内联样式的 HTML，便于在公众号、邮件等场景使用。

## 何时使用

- 用户说「md 转 html」「转成微信能用的」「微信排版」「外链转底部引用」
- 需要从 Markdown 得到带主题、颜色的 HTML 文件

## 主题与样式

**主题**（由用户选或按场景推荐）：

| 主题 | 说明 |
|------|------|
| default | 经典：居中标题+底边线，H2 白字色块 |
| grace | 优雅：文字阴影、圆角卡片、引用样式 |
| simple | 极简：留白多、不对称圆角 |
| modern | 现代：大圆角、药丸形标题，可配 red 主色做红金风 |

**主色预设**（可选）：blue、green、vermilion、yellow、purple、sky、rose、olive、black、gray、pink、red、orange；也可用十六进制。

**引用模式**：用户明确要求「微信外链转底部引用」「文末引用」或 `--cite` 时开启。普通外链改为上标编号并在文末集中列出「引用链接」；`https://mp.weixin.qq.com/...` 保持内链；链接文字与 URL 相同的裸链可保持内联。

## 中文内容预处理（建议）

若输入含中文且存在以下情况，可先建议用户或先执行「格式化」再转 HTML：

- 加粗与标点混在一起导致 `**` 解析异常
- 中英文间距不统一

可结合本项目的 **format-markdown** 技能先产出规范 Markdown，再进入转换步骤。

## 工作流程

1. **确定输入**：用户指定的 Markdown 文件路径或内容。
2. **确定主题与选项**：主题（default/grace/simple/modern）、主色、是否开启底部引用、字体大小等（见下）。
3. **转换执行**：
   - 若本技能 `scripts/` 下有可用的 md→html 脚本（如 Python），通过 `run_skill_script` 调用，传入输入路径与选项（主题、颜色、--cite 等）。
   - 若无现成脚本，则按下方「支持的 Markdown 特性」与主题说明，用 LLM 生成一份符合该风格的 HTML 结构说明或简化 HTML 示例，并告知用户：完整效果可配合 [baoyu-skills/baoyu-markdown-to-html](https://github.com/JimLiu/baoyu-skills#baoyu-markdown-to-html) 在本机执行以获得与主题完全一致的输出。
4. **输出**：HTML 文件建议与源 Markdown 同目录，命名为 `{原文件名}.html`；若已存在则先备份再覆盖。向用户报告输出路径及是否已备份。

## 可选参数

| 选项 | 说明 | 默认 |
|------|------|------|
| 主题 | default, grace, simple, modern | default |
| 主色 | 预设名或 hex | 主题默认 |
| 字体 | sans, serif, serif-cjk, mono 或 CSS 值 | 主题默认 |
| 字号 | 14px–18px | 16px |
| 底部引用 | 普通外链转文末引用 | 关 |
| 保留首标题 | 是否保留正文第一个标题 | 否（多数主题会从 frontmatter 取标题） |
| 标题覆盖 | 用 frontmatter 或参数覆盖标题 | — |

## 支持的 Markdown 特性

- 标题 H1–H6、加粗/斜体、行内代码与围栏代码块（可带语言）
- 表格、图片、链接、引用块、有序/无序列表
- 提示块（如 `> [!NOTE]`）、脚注、Ruby 注音
- Mermaid / PlantUML 等可说明「需在渲染时由前端或工具处理」

## Frontmatter

若 Markdown 含 YAML frontmatter，可解析 `title`、`author`、`description` 等用于 HTML 的 meta 与页头；无 title 时可用首级标题或文件名。

## 输出说明

- 输出路径：与输入同目录的 `{原文件名}.html`
- 若存在同名 HTML，先备份为 `{原文件名}.html.bak-YYYYMMDDHHMMSS` 再写入
- 向用户返回：标题、作者、摘要、htmlPath、backupPath（如有）
