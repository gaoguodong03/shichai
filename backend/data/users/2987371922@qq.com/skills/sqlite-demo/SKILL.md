---
name: SQLite Demo 查询
description: 使用 Python 标准库 sqlite3 查询内置示例数据库，用于验证脚本型 Skill 和专家绑定是否正常。
allowed-tools:
  mcp: []
  python: ''
---
# SQLite Demo 查询

## 你要做什么

你负责调用 `scripts/sqlite_demo.py` 查询一个内置的 SQLite 示例数据库。数据库会在脚本运行时自动创建，包含客户、订单和订单明细三张表，适合验证 SQLite 能否在当前账号的 Skill 沙箱中正常工作。

## 推荐调用方式

优先使用预置查询：

```bash
python scripts/sqlite_demo.py --preset overview
```

可用 preset：

- `overview`：汇总表数量、客户数、订单数、总成交额。
- `customers`：列出客户及所在城市。
- `orders`：列出订单明细和金额。
- `top_customer`：按成交额找出最高客户。

当用户明确给出只读 SQL 时，可以使用：

```bash
python scripts/sqlite_demo.py --sql "select name, city from customers order by id"
```

## 约束

- 只允许执行只读查询：`SELECT`、`WITH`、`PRAGMA`。
- 不要执行 `INSERT`、`UPDATE`、`DELETE`、`DROP`、`ALTER` 等写入或结构变更语句。
- 用户没有指定 SQL 时，优先用 `--preset overview`。
- 每轮最多调用一次脚本。拿到 JSON 后，直接用中文给出结果，不输出工具日志。

## 输出要求

- 用 1 句结论 + 必要的短列表说明查询结果。
- 如果脚本返回 `ok: false`，说明错误类型和可修正的输入方式。
- 完成后输出 `[[SKILL_SESSION_END]]`。
