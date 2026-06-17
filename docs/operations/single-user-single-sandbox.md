# 单用户单沙箱规范

本文档描述当前生效的沙箱模型。用于替代旧的按依赖哈希复用方案。

## 核心原则

- 一个用户只绑定一个沙箱实例（`1 user -> 1 sandbox`）。
- 不再计算或使用 `dep_hash`。
- 不再根据依赖哈希选择或复用基础镜像。

## 挂载与目录约定

- 用户 `workspaces` 根目录挂载到沙箱内 `/workspace`（可读写）。
- 当前用户的 `resources/skills` 根目录挂载到沙箱内 `/skills`（只读）。
- 当前 skill 通过 `/skills/<skill_id>` 访问，其中脚本入口位于 `/skills/<skill_id>/scripts`。

## 会话隔离

- 同一用户多个会话共用同一个沙箱实例。
- 每个会话只允许访问自己的子目录：`/workspace/<session_id>`。
- 工具层（读写/重命名/新建目录/列表）必须做路径归一化和越界拦截。

## 脚本执行规则

- 运行入口固定为 `/skills/<skill_id>/scripts/<script_path>`；不再回退到历史 `/skill/scripts/<script_path>`。
- 脚本执行 `cwd` 固定为 `/workspace/<session_id>`。
- 脚本输入输出文件统一在 `/workspace/<session_id>` 下。
- 详细相对路径约定见 `docs/skills/skill-script-paths.md`。
- 对历史技能提示中的 `scripts/config.json` 做兼容映射到会话根 `config.json`。
- 支持脚本后缀：`.py`、`.sh`、`.bash`、`.ps1`、`.cmd`、`.bat`；沙箱内分别使用 `python3/python`、`bash`、`pwsh`、`cmd.exe` 执行。

## 基础依赖

- 默认基础镜像不跟随应用镜像。`ST49_IMAGE` 只用于后端应用容器，Skill 沙箱通过 `SANDBOX_STANDARD_IMAGE` / `SANDBOX_PLAYWRIGHT_IMAGE` 指向独立模板镜像。
- 1Panel 包由 `ST49_SANDBOX_STANDARD_IMAGE` / `ST49_SANDBOX_PLAYWRIGHT_IMAGE` 写入模板镜像 tag；普通 app 发布如 `26.05.22` 不会自动派生 `sandbox:26.05.22-standard`。
- Docker/OpenSandbox 会复用同一镜像 tag 的本地镜像层；已下载的模板镜像不会按用户重复下载。若需要提前下载模板但不新建用户沙箱，可在宿主机先执行 `docker pull <SANDBOX_STANDARD_IMAGE>`。
- 如需独立维护 Skill 沙箱镜像，可使用 `docker/skill-sandbox/Dockerfile` 构建并通过 `SANDBOX_STANDARD_IMAGE` 覆盖。
- 修改镜像内容后需要重建并推送镜像，再重启后端/OpenSandbox 相关服务。
- 每用户额外 Python 包通过 `data/users/<user_id>/config/sandbox/requirements.txt` 管理；内容 hash 变化时会在该用户沙箱内重新安装。

## 审计口径

- `sandbox_session_created` 事件记录 `sandbox_mode=user_single_sandbox`。
- 不再输出 `dep_hash` 相关审计字段。
