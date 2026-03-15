# 专家（DHA）与技能（Skill）分类整理与重组方案

> 设计原则：每位专家只负责自己的专项区域（如各部门），拥有该部分所需的若干 skill；每个 skill 专精一事。博客生成类任务拆分为：内容核实、网页爬取、思维延伸、文字创作、图片生成、格式转换等专家，各司其职。**北邮学生三位专家及其 skill 不改动**。

---

## 一、当前专家（DHA）清单

| 序号 | dha_id | 名称 | 职责摘要 | 当前 skill_ids | 当前 mcp_server_ids | 备注 |
|------|--------|------|----------|----------------|---------------------|------|
| 1 | dha-df1f712a | 天气感知专家 | 城市天气查询与出行建议 | weather-service | [] | 保留 |
| 2 | dha-c9b8ae32 | 导航专家 | 地理编码、路线、POI | amap-maps | [] | 保留 |
| 3 | dha-440b26f8 | 图片生成专家 | 应用图标、Logo | app-icon-generator | [] | 拟改为「只用一个图片生成 skill」 |
| 4 | dha-blog-cover | 博客封面与配图专家 | 封面、文内配图、小红书图 | cover-image, article-illustrator, xhs-images | [volces-icon] | 拟拆入「图片生成专家」+ 可能删除本 DHA |
| 5 | dha-url-to-blog | 博客从链接到成文 | URL→抓取→成文→封面→配图→一条推文 | url-to-blog, blog-write, cover-image, article-illustrator | [exa, zhipu-web-search, file-reader] | 拟拆分为多专家协作，本 DHA 可删或改为「博客流程协调」 |
| 6 | dha-195b8c3a | 内容生成专家 | 博客、公众号、新闻摘要、格式化、翻译、转 HTML | blog-write, news-summary, wechat-article-writer, format-markdown, humanizer-zh, article-translate, markdown-to-html | [] | 拟拆为「文字创作专家」+「格式转换专家」等 |
| 7 | dha-c1bf68ba | 内容核查专家 | 事实核查与可信度评估 | content-checker | [] | 保留，对应「内容核实专家」 |
| 8 | dha-browser-ops | 浏览器操作助手 | Playwright 浏览器自动化 | browser-playwright | [] | 保留 |
| 9 | dha-file-workspace | 本地文档助手 | 工作区文档查找/读取/总结、合著、技术文档 | file-workspace, doc-coauthoring, docs-write | [filesystem] | 保留 |
| 10 | dha-seminar-host | 学伴研讨主持人 | 主持研讨流程 | seminar-companion | [] | **不动（北邮学伴）** |
| 11 | dha-seminar-teacher | 研讨教师 | 给主题、点评 | [] | [] | **不动（北邮学伴）** |
| 12 | dha-seminar-companion-qiang | 日常滑水的小强 | 学伴讨论 | [] | [] | **不动（北邮学伴）** |
| 13 | dha-seminar-companion-hong | 积极上进的小红 | 学伴讨论 | [] | [] | **不动（北邮学伴）** |
| 14 | dha-seminar-ta | 研讨助教 | 回答问题 | [] | [] | **不动（北邮学伴）** |
| 15 | dha-b6dba178 | 格式与数据规范检查专家 | 日期/空格/标点/JSON 等格式检查 | skill-format-validator | [] | 保留，对应「格式转换专家」一侧或独立 |
| 16 | dha-2be73edd | 文字校对与错别字检查专家 | 错别字、病句、去 AI 痕 | text-proofreader, humanizer-zh | [] | 保留 |
| 17 | dha-66bafc4e | 果冻 | 河南、计算机、Agent 的北邮研究生 | cs-expert-ggd, henan-knowledge, agent-engineering-module | [] | **不动（北邮学生）** |
| 18 | dha-9f6a2b8d | 万辙 | 四川、工程/系统、Switch 的北邮研究生 | agent-engineering-module, sichuan-knowledge, nintendo-switch-games, cs-expert-ggd, ai-infra-module | [] | **不动（北邮学生）** |
| 19 | dha-ae100f7a | 若雨 | 山东、记忆系统、扑克牌的北邮学生 | shandong-knowledge, poker-card-games, agent-engineering-module, cs-expert-ggd | [] | **不动（北邮学生）** |
| 20 | dha-cf4de333 | 测试使用 | 测试 | script-demo | [] | 保留或删除 |
| 21 | dha-deepresearch-exp | 深度研究专家 | 核查→研究→报告 | deep-research, content-checker | [exa, fetch, zhipu-web-search, file-reader] | 可保留；「思维延伸」可由此或单独专家承担 |

---

## 二、当前技能（Skill）清单（按功能分类）

### 2.1 图片类（拟合并为 1 个）

| skill_id | 名称 | 说明 | 建议 |
|----------|------|------|------|
| app-icon-generator | 图标生成 | 应用图标/Logo，run_skill_script 或 volces-icon | **保留并扩展为唯一「图片生成」**：技能内约定可生成张数、每张提示词（封面/配图/图标/小红书等均由同一 skill 通过参数区分） |
| cover-image | 文章封面图生成器 | 封面图五维定制 | **合并进「图片生成」** |
| article-illustrator | 文章配图 | 按段落生成配图方案与插图 | **合并进「图片生成」** |
| xhs-images | 小红书信息图系列 | 1～10 张风格统一的信息图 | **合并进「图片生成」** |

### 2.2 博客/内容创作类

| skill_id | 名称 | 说明 | 建议 |
|----------|------|------|------|
| blog-write | 博客写作 | 选题、素材、撰写博客 | 保留，归「文字创作专家」 |
| wechat-article-writer | 微信公众号文章创作 | 公众号推文、搜索丰富内容 | 保留，归「文字创作专家」 |
| url-to-blog | 从链接到博客 | URL→抓取→问观点→成文→封面→配图 | 可拆为「网页抓取」+ 文字创作 + 图片生成 的协作说明，或保留为流程 skill 给协调者 |
| news-summary | 新闻搜索摘要 | 新闻搜索与摘要 | 保留，归「文字创作专家」或内容核实 |
| article-translate | 文章翻译 | 多语言翻译 | 保留，归「文字创作专家」或格式转换 |
| article-review | 文章评价 | 深度解读/读后感 | 保留，归「文字创作专家」 |

### 2.3 格式/排版/转换类

| skill_id | 名称 | 说明 | 建议 |
|----------|------|------|------|
| format-markdown | Markdown 格式化 | 排版、frontmatter、层级 | 保留，归「格式转换专家」 |
| markdown-to-html | Markdown 转 HTML（微信风格） | 转公众号用 HTML | 保留，归「格式转换专家」 |
| humanizer-zh | 去除 AI 生成痕迹 | 润色更自然 | 保留，可归文字校对或文字创作 |

### 2.4 核查/研究类

| skill_id | 名称 | 说明 | 建议 |
|----------|------|------|------|
| content-checker | 内容核查 | 事实核查、可信度评估 | 保留，归「内容核实专家」 |
| deep-research | 深度研究 | 多阶段研究、子问题、报告 | 保留，归「思维延伸专家」或深度研究专家 |

### 2.5 搜索/抓取（能力多由 MCP 提供）

| skill_id | 名称 | 说明 | 建议 |
|----------|------|------|------|
| zhipu-web-search | 智谱网页搜索 | 实时网页搜索 | 保留，供需要搜索的专家（核实、研究、创作） |
| （无独立 skill） | 网页抓取 | 当前多为 blog-write / url-to-blog 内用 fetch | **可选**：新增「网页抓取」skill，只描述「抓取 URL 得到正文/要点」，供「网页爬取专家」专用 |

### 2.6 地图/天气/浏览器

| skill_id | 名称 | 说明 | 建议 |
|----------|------|------|------|
| amap-maps | 高德地图 | 地理编码、路线、POI、天气 | 保留 |
| weather-service | 简单天气查询 | call_api 城市天气 | 保留 |
| browser-playwright | 浏览器自动化 | Playwright MCP | 保留 |

### 2.7 文档/文件

| skill_id | 名称 | 说明 | 建议 |
|----------|------|------|------|
| file-workspace | 本地文档助手 | 工作区查找/读取/总结 | 保留 |
| doc-coauthoring | 文档合著 | 提案、规范、决策文档流程 | 保留 |
| docs-write | 技术文档 | Metabase 风格文档 | 保留 |

### 2.8 校对/格式检查

| skill_id | 名称 | 说明 | 建议 |
|----------|------|------|------|
| text-proofreader | 文字校对与错别字检查 | 错别字、病句、敏感词 | 保留 |
| skill-format-validator | 格式与数据规范检查 | 日期、空格、标点、JSON/XML | 保留 |

### 2.9 北邮学生/学伴相关（全部不动）

| skill_id | 名称 | 说明 |
|----------|------|------|
| seminar-companion | 学伴研讨主持人 | 主持流程 |
| cs-expert-ggd | 计算机系统知识模块 | 计算机网络、OS、数据库等 |
| henan-knowledge | 河南文化知识模块 | 果冻用 |
| sichuan-knowledge | 四川文化知识模块 | 万辙用 |
| shandong-knowledge | 山东文化知识模块 | 若雨用 |
| agent-engineering-module | Agent 工程与框架实践模块 | 三人共用 |
| ai-infra-module | AI 基础设施与工程实践模块 | 万辙用 |
| nintendo-switch-games | 任天堂 Switch 游戏知识模块 | 万辙用 |
| poker-card-games | 扑克牌与够级知识模块 | 若雨用 |
| memory-research-module | 智能体记忆研究模块 | 若雨可选 |

### 2.10 其他

| skill_id | 名称 | 说明 | 建议 |
|----------|------|------|------|
| session-export | 导出对话 | 导出为 .md | 保留 |
| script-demo | 简单 Script 测试 | 测试 scripts 调用 | 保留或删除 |
| default | 默认助手 | 无法匹配时使用 | 保留 |
| data-report | 数据收集与报告 | 搜索/抓取/API→报告 | 保留，可归思维延伸或独立 |
| prompt-engineering-patterns | 提示词工程 | 提示词技巧 | 保留 |
| xlsx | XLSX 表格处理 | Excel/表格 | 保留 |

---

## 三、博客生成流水线：拟设专家与技能归属

| 专家名称 | 职责 | 拟用 skill（重组后） | 对应 MCP |
|----------|------|----------------------|----------|
| **内容核实专家** | 事实核查、可信度评估 | content-checker | exa / zhipu-web-search / fetch（按需） |
| **网页爬取专家** | 抓取 URL/网页，输出正文或要点 | 新建「网页抓取」或沿用 url-to-blog 中抓取部分说明 | fetch, file-reader |
| **思维延伸专家** | 深度研究、扩展思路、子问题与报告 | deep-research, data-report（可选） | exa, fetch, zhipu-web-search, file-reader |
| **文字创作专家** | 博客、公众号、新闻摘要、翻译 | blog-write, wechat-article-writer, news-summary, article-translate, article-review | exa, zhipu-web-search, fetch, file-reader |
| **图片生成专家** | 封面/配图/图标/小红书图，张数与提示词由技能决定 | **唯一「图片生成」skill**（由原 app-icon-generator 扩展或新建统一 skill） | volces-icon（或现有生图 MCP） |
| **格式转换专家** | Markdown 格式化、转 HTML、日期/标点等格式规范 | format-markdown, markdown-to-html, skill-format-validator（可选） | 无或 filesystem |

说明：

- 北邮学生三位（果冻、万辙、若雨）及学伴研讨相关 DHA/skill **不改动**。
- 现有「内容核查专家」「深度研究专家」可直接对应内容核实、思维延伸；现有「文字校对」「格式与数据规范检查」专家保留，可与格式转换专家并列或合并职责描述。
- 「博客从链接到成文」「博客封面与配图专家」两个 DHA 在拆分后可以删除或改为仅做协调/转发，由上述六类专家协作完成博客生成。

---

## 四、变更操作汇总（待你同意后执行）

### 4.1 技能（Skill）

| 操作 | 项 | 说明 |
|------|-----|------|
| **保留不动** | 北邮/学伴相关全部 skill | seminar-companion, cs-expert-ggd, henan-knowledge, sichuan-knowledge, shandong-knowledge, agent-engineering-module, ai-infra-module, nintendo-switch-games, poker-card-games, memory-research-module |
| **合并** | cover-image, article-illustrator, xhs-images → 并入「图片生成」 | 新建或扩展为一门 skill：如 `image-generator`，描述「按任务生成 1～N 张图，每张由类型（封面/配图/图标/小红书）+ 提示词决定」；原 cover/article-illustrator/xhs 的脚本或 MCP 调用方式可保留在 scripts 或文档中，由该 skill 统一指引 |
| **保留** | app-icon-generator | 可选：改名为通用「图片生成」并扩展描述；或保留 id 仅改描述为「通用图片生成，支持图标/封面/配图/小红书」 |
| **可选新增** | 网页抓取（如 url-fetch） | 仅描述「抓取 URL 得到正文或要点」，供网页爬取专家专用；若不用独立 skill，可由文字创作专家直接带 fetch MCP |
| **保留** | 其余 blog/格式/核查/研究/文档/校对等 | 见上表，仅做归属调整，不删不改 id |

### 4.2 专家（DHA）

| 操作 | 项 | 说明 |
|------|-----|------|
| **不动** | 果冻、万辙、若雨 | dha-66bafc4e, dha-9f6a2b8d, dha-ae100f7a，skill_ids 与 mcp 均不改 |
| **不动** | 学伴研讨主持人、研讨教师、小强、小红、研讨助教 | 5 个 DHA 全部不改 |
| **保留** | 天气感知、导航、浏览器操作、本地文档助手、文字校对、格式与数据规范检查、内容核查、深度研究、测试使用 | 仅必要时微调 skill_ids/mcp_server_ids |
| **新增** | 内容核实专家 | 若与现有「内容核查专家」重复则复用 dha-c1bf68ba，否则新建 |
| **新增** | 网页爬取专家 | 新建，skill：网页抓取（或仅 MCP fetch）；mcp：fetch, file-reader |
| **新增** | 思维延伸专家 | 可复用「深度研究专家」或新建，skill：deep-research, data-report |
| **调整** | 文字创作专家 | 可复用「内容生成专家」dha-195b8c3a，skill 仅保留：blog-write, wechat-article-writer, news-summary, article-translate, article-review；去掉 format-markdown, markdown-to-html（归格式转换） |
| **调整** | 图片生成专家 | 复用 dha-440b26f8，skill 改为唯一「图片生成」skill（见上）；mcp 保留 volces-icon |
| **新增** | 格式转换专家 | 新建，skill：format-markdown, markdown-to-html, skill-format-validator（可选） |
| **删除或弃用** | 博客封面与配图专家（dha-blog-cover） | 职责由「图片生成专家」承担 |
| **删除或弃用** | 博客从链接到成文（dha-url-to-blog） | 职责由「网页爬取 + 文字创作 + 图片生成 + 格式转换」等专家协作完成 |

---

## 五、请你确认

请确认以下三项后我再按此方案改配置与文件：

1. **专家列表**：是否同意上述「保留 / 新增 / 调整 / 删除」的 DHA 列表？有无要增删或改名的专家？
2. **技能合并**：是否同意「只保留一个图片生成 skill」（由 app-icon-generator 扩展或新建 image-generator），cover-image、article-illustrator、xhs-images 合并进该 skill？是否需要单独「网页抓取」skill？
3. **北邮/学伴**：是否确认果冻、万辙、若雨三位 + 学伴研讨 5 个 DHA + 相关 skill 全部不改？

你回复「同意」或给出修改意见后，我再执行：修改 `dha_instances.json`、合并或新增 skill 目录与 SKILL.md、更新 `_SKILL_MCP_SERVERS_FALLBACK` 等。
