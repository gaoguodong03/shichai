# 发布入口

本文是发版、提测、部署和验收的统一入口。需要对外分发、上线前自测或迁移到新机器时，从这里开始。

## 谁该读什么

| 角色 | 首读文档 | 目的 |
| --- | --- | --- |
| 开发者 | [第一层回归说明](../testing/layer1-regression.md) | 确认改动后最低自动化门禁 |
| 测试/验收人员 | [上线前模块化测试操作手册](../testing/pre-release-testing.md) | 按模块和用户需求编号验收 |
| 产品/项目负责人 | [全流程业务测试汇总](../testing/full-flow-business-tests.md) | 看用户可见主流程是否覆盖 |
| 运维/部署人员 | [单用户单沙箱规范](../operations/single-user-single-sandbox.md) | 理解沙箱、镜像、依赖和运行边界 |
| Skill 作者 | [Skill 编写规范](../skills/skill-standard.md) | 确认 Skill、脚本和依赖写法 |
| 架构维护者 | [兼容层与回退路径寿命台账](../project/compatibility-lifecycle.md) | 发版前确认旧协议边界没有扩散 |

## 标准发布路径

1. **确认变更范围**
   - 读本次 diff，判断是否影响会话、资源中心、Skill/MCP、沙箱、LLM、账号、部署或文档。
   - 若涉及兼容层、旧字段、旧资源包或 fallback，先更新 [兼容层与回退路径寿命台账](../project/compatibility-lifecycle.md)。

2. **运行最低门禁**

```bash
rtk ./scripts/test-layer1.sh
```

通过标准：脚本汇总中后端和前端均为 `PASS`。

3. **按范围补专项验证**

| 改动范围 | 推荐补充命令或文档 |
| --- | --- |
| 后端 API、会话、编排、文件、资源导入导出 | `rtk ./scripts/test-full-flow.sh` |
| 前端页面、路由、可点击交互 | `rtk ./scripts/test-ui-flow.sh` |
| Skill 脚本、沙箱、依赖安装 | [上线前模块化测试操作手册](../testing/pre-release-testing.md) 第 3.6 节和 UR-05/UR-07 验收 |
| MCP、外部 HTTP、模型密钥 | `tests/test_file_ref_and_gateway.py`、`tests/test_skill_agent_tool_resolution.py`、`tests/test_llm_config.py`，再做真实 Key/服务冒烟 |
| 文档或验收口径 | `rtk git diff --check -- README.md docs backend/README.md frontend/README.md`，并检查相对链接 |

4. **部署冒烟**
   - 使用 `docker-compose.1panel.yml` 或目标部署方式启动。
   - 按 [上线前模块化测试操作手册](../testing/pre-release-testing.md) 的部署冒烟步骤检查健康接口、登录、基础对话和 Skill 沙箱。

5. **交付记录**
   - 记录实际执行过的命令、结果和未覆盖项。
   - 若有跳过项，写明原因和后续补测责任人。

## 最低发布清单

- [ ] 工作区没有意外运行产物进入提交范围。
- [ ] `rtk ./scripts/test-layer1.sh` 已执行并通过，或明确记录未跑原因。
- [ ] 受影响模块的专项测试已执行。
- [ ] `docs/README.md`、本发布入口和相关专题文档没有互相冲突。
- [ ] 兼容层台账中相关条目的状态、退出条件和验证入口已同步。
- [ ] 部署包或上线环境的 `.env`、镜像 tag、数据卷和沙箱镜像配置已确认。

## 不覆盖事项

本入口不替代具体的测试说明、架构设计或用户手册。它只负责回答“发布前从哪里开始、按什么顺序检查、哪些文档必须同步”。
