# 提示词与 Prompt 组装管理契约

版本：v0.1 目标契约
日期：2026-07-09
适用范围：书童四九平台内置提示词模板、LLM 调用 Prompt 组装、运行时输入边界和调试信息隔离。

## 1. 文档目的

本文定义书童四九中所有会进入 LLM 的平台内置提示词模板和运行时 Prompt 组装规则。

本文是目标契约。后续代码、测试和文档应按本文收敛，删除散落在业务代码中的平台内置提示词硬编码、重复 Prompt 拼接和旧兜底逻辑。

本文不管理前端按钮文案、普通 API 错误文案、代码注释和日志文本。它们不属于 LLM Prompt。

## 2. 基本原则

1. 平台内置提示词模板必须集中管理，不允许在业务代码中硬编码大段 LLM 提示词。
2. 业务代码只允许通过 `prompt_id` 引用平台内置提示词模板。
3. 每次 LLM 调用必须明确使用哪一组 Prompt 块，不允许调用点临时拼接一套私有上下文。
4. 所有 Prompt 块统一使用 `xxxx_prompt` 命名，不使用 `xxxx_context` 命名。
5. `debug_*` 信息不能进入 LLM，只能进入日志、测试断言或前端调试展示。
6. Prompt 要求模型输出的字段必须与代码 schema 和字段契约文档一致，不允许提示词写一套字段、代码兜底解析另一套字段。

## 3. 平台内置提示词模板

平台内置提示词模板指平台为了驱动 LLM 行为而提供的固定模板，例如主持人调度、专家选择 Skill、Skill 执行规则、标题生成和展示重写。

目标实现中，平台内置提示词模板应集中存放在一个文件中。代码不直接保存大段模板正文，只保存 `prompt_id`、变量和调用场景。

用户可编辑内容不强制进入平台内置模板文件：

| 内容 | 来源 | 是否进入统一模板文件 |
|------|------|----------------------|
| 平台内置主持人调度模板 | 平台代码仓库 | 是 |
| 平台内置专家选择 Skill 模板 | 平台代码仓库 | 是 |
| 平台内置 Skill 执行约束模板 | 平台代码仓库 | 是 |
| 标题生成模板 | 平台代码仓库 | 是 |
| 展示重写模板 | 平台代码仓库 | 是 |
| 系统提示词 | 设置页，平台级配置 | 否，运行时作为 `system_prompt` 注入 |
| 场景初始化提示材料 | 场景资源 `system_prompt` | 否，不作为会话定义字段；是否进入运行时由创建会话逻辑显式决定 |
| 主持人或专家提示词 | Agent 配置字段 | 否，运行时作为 `agent_prompt` 注入 |
| Skill 正文 | `SKILL.md` | 否，运行时进入对应 Skill 调用 |

## 4. Prompt 块定义

一次 LLM 调用由多个 Prompt 块组装而成。每个块必须有稳定名称、来源和进入规则。

| Prompt 块 | 含义 | 来源 | 进入 LLM 规则 |
|-----------|------|------|----------------|
| `system_prompt` | 整个平台级别的提示词 | 设置页中的书童四九平台提示词 | 需要平台级规则的调用进入 |
| `scenario_prompt` | 场景初始化提示材料 | 场景资源 `system_prompt`；不保存为会话定义字段 | 只有创建逻辑明确带入时进入 |
| `memory_prompt` | 会话记忆、事实和文件索引摘要 | 平台运行时生成 | 只进入摘要或索引，不进入调试信息 |
| `agent_prompt` | 当前主持人或专家的提示词 | 主持人或专家配置字段 | 当前调用者为主持人或专家时进入 |
| `host_select_agent_prompt` | 主持人选择专家的调用模板 | 平台内置模板 | 仅主持人选择专家时进入 |
| `expert_select_skill_prompt` | 专家选择 Skill 的调用模板 | 平台内置模板 | 仅专家选择 Skill 时进入 |
| `skill_execution_prompt` | 专家使用已选 Skill 执行能力的调用模板 | 平台内置模板 + Skill 正文 + 工具说明 | 仅 Skill 执行时进入 |
| `user_prompt` | 用户输入和用户显式提供材料 | 最近输入文本、最近上传文件或显式引用文件 | 所有面向用户任务的 LLM 调用进入 |

不允许使用 `debug_context`、`debug_prompt` 或类似块进入 LLM。调试信息统一称为 `debug_payload`、`debug_trace` 或 `debug_info`，只用于观察和排障。

## 5. 核心 LLM 调用场景

### 5.1 主持人选择专家

主持人选择专家时，只组装主持人调度需要的 Prompt 块：

```text
system_prompt
scenario_prompt
memory_prompt
agent_prompt
host_select_agent_prompt
user_prompt
```

其中 `agent_prompt` 是当前主持人的提示词，`host_select_agent_prompt` 包含可选专家列表、调度规则和主持人输出字段要求。

### 5.2 专家选择 Skill

专家选择 Skill 时，只组装专家选择 Skill 需要的 Prompt 块：

```text
system_prompt
scenario_prompt
memory_prompt
agent_prompt
expert_select_skill_prompt
user_prompt
```

其中 `agent_prompt` 是当前专家的提示词，`expert_select_skill_prompt` 包含可选 Skill 列表和选择结果字段要求。

### 5.3 专家通过 Skill 执行能力

专家已经选定 Skill 后，真正执行能力时组装：

```text
system_prompt
scenario_prompt
memory_prompt
agent_prompt
skill_execution_prompt
user_prompt
```

其中 `skill_execution_prompt` 包含 Skill 正文、当前可用工具列表、工具使用规则和输出约束。

### 5.4 简单 LLM 调用

标题生成、短文本总结等简单调用不需要完整 Prompt 组装链路。

例如自动生成标题只使用：

```text
title_generation_prompt
recent_user_text
```

这类调用也必须使用平台内置模板文件中的 `prompt_id`，但不强制注入 `system_prompt`、`scenario_prompt`、`memory_prompt` 或 `agent_prompt`。

## 6. Prompt 组装顺序

完整任务型 LLM 调用使用以下顺序：

1. `system_prompt`
2. `scenario_prompt`
3. `memory_prompt`
4. `agent_prompt`
5. 当前调用专属 Prompt：`host_select_agent_prompt`、`expert_select_skill_prompt` 或 `skill_execution_prompt`
6. `user_prompt`

同一次 LLM 调用中，`host_select_agent_prompt`、`expert_select_skill_prompt`、`skill_execution_prompt` 三者只能出现一个。

## 7. 用户输入与文件边界

`user_prompt` 可以包含：

- 最近输入文本。
- 用户最近上传文件的文件名、类型和必要摘要。
- 用户显式引用文件的必要摘录。

`user_prompt` 不能无条件塞入完整工作区文件、内部运行日志、工具 stdout/stderr、环境变量真实值、绝对路径或其他用户不可见系统数据。

## 8. 调试信息边界

以下内容不得进入 LLM：

- `debug_payload`
- `debug_trace`
- `route_debug`
- `tool_debug`
- token 统计
- prompt 日志
- API Key、环境变量真实值和环境变量引用解析结果
- 内部绝对路径
- 沙箱运行日志
- 测试 fixture 专用字段

这些内容只能用于日志、测试断言、开发者调试面板或问题定位。

## 9. 变更规则

新增或修改平台内置 LLM 调用时，必须同步确认：

1. 是否需要新增 `prompt_id`。
2. Prompt 模板是否进入统一平台内置模板文件。
3. 调用场景使用哪组 Prompt 块。
4. Prompt 输出字段是否与代码 schema 一致。
5. 是否误把 `debug_*` 信息注入 LLM。
6. 是否需要更新运行契约、详细设计、测试和用户手册。

字段或输出协议变更还必须同步 [运行逻辑与接口契约](runtime-interface-contract.md)。
