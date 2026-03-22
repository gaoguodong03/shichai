---
name: 网页抓取
description: 抓取指定 URL 的网页内容，得到正文或要点。供博客、研究、核查等流程中的「先抓再写/再分析」使用。
enabled: true
mcp_server_ids:
  - linkup
  - file-reader
---

# 网页抓取

当用户或协作专家需要「把某个链接的内容抓下来」时使用本技能。

## 使用方式

1. **抓取工具**：使用 fetch MCP 的 `fetch_fetch`（或 linkup 的抓取工具），参数为 `url`（必填），传入要抓取的完整 URL。
2. **HTML 解析**：若抓取结果是 HTML 源码，应调用 `run_skill_script_url-fetch`：
   - `script_path="extract_main_content.py"`
   - `input_json={"html":"<抓取到的HTML>","url":"<可选URL>","max_chars":8000}`
   脚本会输出 `MAIN_CONTENT`，可直接用于摘要或交给其他专家继续处理。
3. **输出**：抓取结果多为 Markdown 或纯文本；可写入当前会话工作区（通过 file-reader_write_file）或直接返回给调用方。
4. **与后续协作**：抓取后的正文可交给「文字创作专家」成文、或交给「内容核实专家」核查、或交给「思维延伸专家」做深度研究。

## 注意

- 必须使用参数名 `url` 传链接，不要用 `__arg1`。
- 若抓取失败（超时、403、非 HTML 等），如实返回错误并建议用户检查 URL 或换用其他来源。
- 若返回 HTML，请优先走 `extract_main_content.py` 再总结，不要把“脚本不可用”作为默认回复。
