# Shixiseng Crawler CLI 使用指南

本项目采用模块化、配置驱动的架构，支持通过命令行参数（CLI）直接控制爬取和清洗逻辑。

## 🚀 优先级原则
**命令行参数 (CLI)** > **配置文件 (task.json)** > **内置默认值**

---

## 🛠 基础命令格式
```bash
python scripts/main.py [模式参数] [筛选参数] [控制参数]
```

## 1. 模式参数 (`--mode`)
决定程序运行哪个环节：
- `--mode crawl`: 仅执行爬取，写入文件存储并导出原始数据。
- `--mode clean`: 仅执行 AI 数据清洗（处理文件存储中未清洗的数据）。
- `--mode all` (默认): 先爬取，后清洗，一键完成。

## 2. 筛选参数 (Override)
这些参数会覆盖 `assets/task.json` 中的 `default_filters` 设置。

| 参数名 | 说明 | 可选值示例 |
| :--- | :--- | :--- |
| `--category` | 职位分类 | "互联网IT", "金融", "设计/传媒" |
| `--city` | 城市名称 | "北京", "上海", "深圳", "全国" |
| `--degree` | 学历要求 | "不限", "大专", "本科", "硕士", "博士" |
| `--official` | 转正机会 | "不限", "提供转正", "不提供转正", "面议" |
| `--enterprise` | 企业筛选 | "不限", "知名企业", "互联网300强" |
| `--months` | 实习月数 | "不限", "一月", "两月", "三月", "三月以上" |
| `--days` | 每周天数 | "不限", "一天", "两天", "三天", "四天", "五天", "六天及以上" |

## 3. 控制参数
| 参数名 | 说明 | 默认值 |
| :--- | :--- | :--- |
| `--limit-pages` | 每个分类抓取的最大页数 | 取自 `task.json` 或 5 |
| `--limit-clean` | 本次 AI 清洗的职位数量 | 10 |
| `--storage-dir` | 文件存储目录，相对当前运行目录解析 | `scripts/job_store` |
| `--export-dir` | 结果导出目录 | 取自 `task.json` |
| `--db` | 兼容旧参数；建议改用 `--storage-dir`，传入 `.db` 会映射到同名 `_store` 目录 | `None` |

---

## 💡 使用示例

### A. 全流程自动测试 (推荐)
爬取“北京”的“互联网IT”分类，抓取前 2 页，并清洗 5 条数据：
```bash
python scripts/main.py --mode all --city "北京" --category "互联网IT" --limit-pages 2 --limit-clean 5
```

### B. 精准复刻图片筛选 (高级筛选)
北京 + 互联网IT + 实习3个月 + 每周3天 + 提供转正：
```bash
python scripts/main.py --mode all --city "北京" --category "互联网IT" --months "三月" --days "三天" --official "提供转正"
```

### C. 存量数据补洗
不对网站发起请求，只把文件存储里还没处理完的 20 条数据用 AI 跑一遍：
```bash
python scripts/main.py --mode clean --limit-clean 20
```

---

## 📂 产出说明
运行结束后，系统会在当前运行目录下的 `scripts/rebuild/` 中生成一个**带时间戳**的文件夹（或写入你通过 `--export-dir` 指定的相对目录），包含：
1. `ex_with_raw.json`: 完整版（含 AI 原始输出 `ai_raw_data`）。
2. `ex_summary.json`: 干净版（仅含结构化字段）。
3. `shixiseng_results.json`: 备份版。
4. `jobs_with_raw.jsonl`: 逐行 JSONL，便于流式处理。
5. `jobs_summary.jsonl`: 去除 `ai_raw_data` 的逐行 JSONL。
6. `jobs_summary.csv`: 扁平化 CSV，便于表格平台接入。
7. `session.json`: 本次运行涉及到的 `job_id` 与存储目录。

此外，文件存储目录下会按 `job_id` 生成独立子目录；`--storage-dir` 也是相对当前运行目录解析：
- `raw.json`: 抓取原始结构化结果，原字段原样保留。
- `cleaned.json`: AI 清洗后的结构化结果。
- `ai_raw.json`: 模型原始输出。
- `meta.json`: 标题、来源、更新时间、清洗状态等索引信息。
- `index.jsonl`: 全局检索索引。
