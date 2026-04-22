---
description: 从 OpenGithubs/github-weekly-rank 获取每周飙升榜与 README 榜单正文，落盘供后续分析与简报使用。
enabled: true
mcp_server_ids:
- file-reader
name: GitHub 开源周榜情报
source: local
write_mode: workspace_all
---
# GitHub 开源周榜情报

## 权威数据源

- 仓库主页：<https://github.com/OpenGithubs/github-weekly-rank>
- 优先抓取 **默认分支根目录 `README.md`** 的完整内容（含当周日期区间、Top20 表格、项目简介）。
- 若需按年查阅历史文件，可进入仓库内 `2024/`、`2025/`、`2026/` 等目录下对应周的 Markdown（以仓库实际结构为准）。，如https://github.com/OpenGithubs/github-weekly-rank/blob/main/2026/04/20260406.md

## 执行步骤

1. 使用 **fetch / 网页抓取** 工具，参数名 **`url`**，抓取上述 README 或用户指定的周榜文件 URL。
2. 将**原始榜单正文**（或结构化摘录：排名、仓库名、Star、周增长、一句话描述）写入当前会话**工作区根目录**固定文件名：`github-weekly-snapshot.md`（便于主持与其他专家引用）。
3. 若抓取失败：如实说明错误；可建议用户粘贴 README 片段或换用 raw 链接（若环境允许）。
4. **禁止**凭记忆编造排名与数字；榜单中未出现的条目不得写成「当周数据」。

## 与「今日大事」的关系

用户若同时要求「今日大事」，仍以本技能完成 **周榜事实层**；更广泛的当日资讯由「技术简报专家」结合新闻摘要类技能处理，并在文中区分「周榜数据」与「当日要闻」。
