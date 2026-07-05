# 用户资源存储架构

本文档定义书童四九多用户资源存储的新标准。目标是把用户身份、资源中心、会话历史、密钥和沙箱执行边界拆清楚，避免用户目录重建后资源丢失、沙箱误读完整用户数据、密钥被资源包带出等问题。

## 设计结论

采用方案 A：继续以本地 JSON 文件和资源目录为主，不引入数据库化资源存储。

核心边界：

- 身份层只负责登录账号、密码哈希和 `user_id`。
- `resources/` 存用户可管理、可导入导出、可迁移的资源。
- `sessions/` 存真实会话历史、运行状态和工作区产物。
- `settings/` 存账号级应用设置、密钥库和沙箱依赖。
- 沙箱只拿执行视图，不直接获得完整用户身份、密钥或账号密码。

## 当前数据结构

```text
data/users/{user_id}/
  profile.json

  resources/
    scenarios/
      {scenario_id}/
        scenario.json

    agents/
      {agent_name}/
        agent.json

    skills/
      {directory_name}/
        SKILL.md
        scripts/
        assets/
        references/
        templates/
        other/

    tools/
      {tool_id}/
        tool.json

    models/
      {model_provider_id}/
        model.json

  settings/
    app.json
    secrets.enc.json
    sandbox/
      requirements.txt
      settings.json

  sessions/
    index.json

    {session_id}/
      session.json
      history.json
      runtime.json
      chat.md

      workspace/

      checkpoints/
        HEAD.json
        chain.json
        commits/
          {commit_id}.json

        objects/
          blobs/
            {sha256}
          trees/
            {sha256}.json
```

## 术语

- 场景：一次群聊或任务的编排模板，描述参与专家、主持人配置、运行策略和目标示例。
- 专家：可被场景引用的角色配置，描述提示词、模型偏好、Skill 和工具权限。
- Skill：可执行能力包，包含 `SKILL.md`、脚本、资产、模板和其他文件。
- 工具：MCP 或外部工具配置，可能引用密钥，但不能保存明文密钥。
- 模型：模型提供商和模型参数配置，可能引用密钥，但不能保存明文密钥。
- 会话：一次真实聊天或群聊运行后的历史记录、事件和工作区产物。

## 顶层原则

1. `user_id` 是用户资源目录主键，邮箱和用户名只是登录字段。
2. 不在主路径兼容旧邮箱目录；旧数据迁移用一次性迁移脚本处理。
3. `resources/` 内的每类资源都目录化，避免巨型 JSON 成为唯一真相。
4. `index.json` 只服务列表页和排序，真实内容以资源目录中的主体文件为准。
5. 资源之间只保存引用，不复制完整内容。
6. 密钥只保存在 `settings/secrets.enc.json`，资源文件只能保存 `secret_ref`。
7. 沙箱可以物理挂载当前用户全部 Skill，但逻辑上只暴露本轮允许的 Skill 和工具。
8. 所有资源写入必须原子化，并保留可恢复版本或备份。

## 相关文档

- [存储标准](storage-standard.md)
- [新窗口开发提示词](new-window-prompt.md)
