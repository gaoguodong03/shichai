---
description: 用于用户要求抓取网络素材、整理设定参考、保存网页原文证据时触发；会优先调用本技能自带脚本抓取页面并将结果落盘，输出可追溯的本地存档路径。
name: webnovel-web-crawler
allowed-tools:
  mcp: []
  python: ''
---
# 网文写作-网页爬取专家

## 目标
在“网文写作”场景中，为素材收集提供稳定抓取能力，并把抓到的网页内容存档，供后续写作、考据、改写时引用。

## 触发条件
- 用户提到“网文写作”“设定参考”“素材搜集”“抓网页/爬网页/提取正文”等需求。
- 用户要求“保留来源”“可追溯存档”“保存原网页”。

## 默认执行流程
1. 收集 URL 列表（支持 1 个或多个）。
2. 运行脚本：
   - 在终端环境可用：`python scripts/crawl_and_store.py "<url1>" "<url2>" ...`
   - 在群聊工具中优先用 `run_skill_script_<skill_id>` 调用 `crawl_and_store.py`，并通过 `cli_args_json` 传入（JSON 数组字符串）：
     - `["https://a.com","https://b.com"]` 或 `["--out","output/pages","https://a.com"]`
3. 返回每个 URL 的存储结果：
   - 本地目录
   - `page.html`（原始 HTML）
   - `text.md`（清洗后的正文文本）
   - `meta.json`（标题、来源、时间戳、状态码等）
4. 如果抓取失败，明确给出失败原因与重试建议。

## 存储约定
- 默认输出目录：`output/pages/`
- 每个 URL 会生成一个独立子目录：`<utc时间>_<url指纹>/`
- 每次执行额外写入 `output/pages/index.jsonl`，用于后续检索与批量处理。

## 命令示例
```bash
python scripts/crawl_and_store.py "https://example.com/story-lore"
python scripts/crawl_and_store.py --out "output/pages" "https://a.com" "https://b.com"
```

## 协作规范
- 将 `text.md` 提供给“网文写作专家/剧情专家”用于创作素材输入。
- 引用时优先保留 `meta.json` 中的 `url` 与 `fetched_at`，保证可追溯。
- 不擅自改写原始信息；“抓取层”和“创作层”职责分离。
- 面向用户回复时，只输出抓取结论与存档路径，不回显工具原始 JSON、stderr 或调试信息。

## 约束
- 默认仅做公开网页抓取，不处理需要登录或付费墙内容。
- 遇到反爬、验证码、403/429 时，返回失败并建议用户更换来源或降低频率。
- 不绕过网站访问限制，不提供违规抓取方案。


## 调用协议（统一）
- `run_skill_script` 仅支持 `cli_args_json`（CLI argv）。
- 不再支持 `input_json`/stdin JSON。
