# 开发会话记录

本文档按轮次整理对话中已完成的修改与结论，便于后续按文档继续开发。

---

## 本轮（近期）已完成

- **Chat 入口行为**：点击 Chat 时中间栏固定为「历史对话」；取消默认会话，未选会话时右侧空白，使用临时 sessionId 发首条消息；首次发消息后中间栏才切到「当前对话」。
- **历史会话删除**：后端新增 `DELETE /api/sessions/{session_id}`；前端在历史列表每项增加删除按钮（悬停显示），确认后调用删除并刷新列表，若删的是当前选中会话则清空右侧。
- **高德地图 MCP**：Skill 中强调地理编码必传 `city`、补充北邮/天安门示例与标准流程；manager 中对 `maps_geo` 做 `__arg1` 展开（支持字符串或 "地址,城市"）、缺 city 时北京关键词自动补 city；对路线/距离类工具做 `__arg1` 展开为 `origin`/`destination`，避免 INVALID_PARAMS。
- **MCP 工具调用与展示**：结构化 tool_calls 时在 react_step 中附带 `tool_call` 供前端显示参数；前端收到后注入 JSON 块以展示工具名与参数；volces 图标生成支持 `__arg1` 展开与 prompt/input→description 规范化。
- **UI 调整**：最左侧导航去掉每项开头表情；「文件系统」改为「Files」。

---

## 参考

- 架构与流程见 [架构概述](../architecture/overview.md)、[运行流程](../architecture/runtime-flow.md)。
- 后续计划见 [下一步开发计划](./next-plan.md)。
