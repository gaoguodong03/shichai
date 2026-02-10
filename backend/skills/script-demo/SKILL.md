---
description: 使用 run_skill_script 执行当前 Skill 下的简单 Python 脚本，验证 scripts 型 Skill 的调用链路。
enabled: true
name: 简单 Script 测试
---
# Script 测试 Skill

**目标**：只测试「scripts/ 下脚本 + run_skill_script」是否能跑通，不做普通闲聊。

## 使用规则（给 Agent）

1. 无论用户说什么，本 Skill 下**第一步必须调用一次** `run_skill_script` 工具。
2. 调用参数固定为：
   - `script_path = "hello_dha.py"`（相对 `scripts/` 目录）
   - `input_json = ""`（空字符串）
3. **禁止**在未调用 `run_skill_script` 的情况下直接回答用户。
4. **禁止**调用除 `run_skill_script` 以外的任何工具。
5. `hello_dha.py` 脚本会输出一行文本，例如：`这里是 DHA`。  
   你的最终回复应该**只返回脚本的输出内容**（原样，不加问候语或额外解释）。

