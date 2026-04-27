---
allowed-tools:
  mcp: []
  python: ''
description: 针对实习僧（Shixiseng）平台的高性能实习岗位采集与清洗工具。
entry_point: scripts/main.py
environment: scrapling
name: Shixiseng_Dedicated_Crawler
version: 1.1.0
---
# 实习僧招聘采集技能

专门用于从实习僧官网提取并清洗职位信息的自动化工具。

## 核心能力
- **渲染解析**：利用 StealthySession 模拟真实浏览器，成功绕过实习僧的自定义字体加密（Font-Face Encryption）与 JS 风控。
- **全流程自动化**：支持从列表抓取到详情页提取，再到 AI 数据清洗的全自动闭环。
- **动态过滤**：支持通过城市（City）和类别（Category）参数进行精准检索。

## 使用指南
当用户询问有关实习僧的职位时：
1. **定位**：前往 `./scripts`。
2. **执行**：使用 `scripts/main.py` 提供的 CLI 接口。
3. **验证**：检查当前运行目录下 `scripts/rebuild/` 的 JSON 结果，并确认数据已存入相对路径 `scripts/job_store/`。

### 命令行快捷参考
- **全流程运行**：`python scripts/main.py --mode all --city "[城市]" --category "[类别]"`
- **限制抓取页数**：`python scripts/main.py --mode all --city "[城市]" --category "[类别]" --limit-pages [页数]`
- **配置模式**：`python scripts/main.py --mode all`（直接读取 `assets/task.json` 中的任务清单）
- **仅执行清洗**：`python scripts/main.py --mode clean --limit-clean [N]`

## 关键注意事项
- 实习僧的反爬策略严苛，请确保 `StealthySession(headless=False)` 能够正常运行。
- 默认文件存储位置为相对路径：`scripts/job_store`；默认导出位置为相对路径：`scripts/rebuild`。
