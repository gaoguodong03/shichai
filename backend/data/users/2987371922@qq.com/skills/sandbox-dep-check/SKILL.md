---
name: 沙箱依赖安装验证
description: 验证沙箱是否会按当前账号的 requirements.txt 自动安装 Python 依赖；通过运行脚本打印指定包的版本号。
allowed-tools:
  mcp: []
  python: ''
---
## 目的
验证「沙箱环境」里是否已经安装了某个你在 `settings/sandbox/requirements` 里配置的 Python 包。

## 使用方式
1. 在前端的 **Sandbox Settings → requirements.txt** 里加入你要测试的包（建议写死版本，避免歧义），例如：
   - `pendulum==3.0.0`
2. 在对话中让专家运行脚本（或你直接调用工具）：
   - 脚本：`check_pkg_version.py`
   - 参数：`--package pendulum`

## 预期输出
- 若安装成功：stdout 会包含 `{"ok": true, "package": "...", "version": "..."}`。
- 若未安装：脚本会以非 0 退出码结束，stderr 会提示 `package_not_installed`。

## 结束标记
完成验证后输出 `[[SKILL_SESSION_END]]`。

