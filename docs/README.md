# 书童四九文档中心

本文是项目文档的唯一入口。新增文档前先判断归属目录，避免继续在 `docs/` 顶层堆文件。

## 目录规范

| 目录 | 用途 | 代表文档 |
|------|------|----------|
| `requirements/` | 用户需求、验收口径、需求追踪矩阵 | [user-requirements.md](requirements/user-requirements.md)、[acceptance-and-tests.md](requirements/acceptance-and-tests.md) |
| `architecture/` | 系统架构、详细设计、运行链路、数据结构、接口和模块边界 | [interface-map.md](architecture/interface-map.md)、[data-structure-and-field-logic.md](architecture/data-structure-and-field-logic.md)、[system-architecture.md](architecture/system-architecture.md)、[detailed-design.md](architecture/detailed-design.md)、[runtime-architecture.md](architecture/runtime-architecture.md)、[project-structure.md](architecture/project-structure.md) |
| `testing/` | 测试用例、回归测试、上线前测试、全流程业务测试 | [test-case-catalog.md](testing/test-case-catalog.md)、[layer1-regression.md](testing/layer1-regression.md)、[pre-release-testing.md](testing/pre-release-testing.md)、[full-flow-business-tests.md](testing/full-flow-business-tests.md) |
| `user-manual/` | 面向用户和验收人员的操作手册、截图、PDF | [user-guide.md](user-manual/user-guide.md)、[README.md](user-manual/README.md) |
| `skills/` | Skill 规范、主持人 Skill、脚本路径、沙箱工具接口 | [skill-standard.md](skills/skill-standard.md)、[host-skill.md](skills/host-skill.md)、[skill-script-paths.md](skills/skill-script-paths.md)、[sandbox-tool-interface.md](skills/sandbox-tool-interface.md) |
| `operations/` | 部署、运行、沙箱和运维约束 | [single-user-single-sandbox.md](operations/single-user-single-sandbox.md) |
| `release/` | 发版、提测、部署和验收的统一入口 | [README.md](release/README.md) |
| `project/` | 项目工作清单、工程任务拆分、兼容台账、P0 完成审计、里程碑、文档审计和管理性材料 | [worklist.md](project/worklist.md)、[implementation-task-breakdown.md](project/implementation-task-breakdown.md)、[compatibility-lifecycle.md](project/compatibility-lifecycle.md)、[p0-completion-audit.md](project/p0-completion-audit.md)、[documentation-audit.md](project/documentation-audit.md)、[documentation-inventory.md](project/documentation-inventory.md) |
| `presentations/` | 对外介绍、讲稿、PPT 和演示素材 | [agent-development-and-effects.md](presentations/agent-development-and-effects.md) |
| `superpowers/` | Superpowers 规格、实施计划和阶段性工程计划 | `superpowers/specs/`、`superpowers/plans/` |

## 推荐阅读顺序

1. 产品和验收：先读 [requirements/user-requirements.md](requirements/user-requirements.md)，再读 [requirements/acceptance-and-tests.md](requirements/acceptance-and-tests.md)。
2. 设计和任务：读 [architecture/detailed-design.md](architecture/detailed-design.md) 和 [project/implementation-task-breakdown.md](project/implementation-task-breakdown.md)。
3. 架构和代码入口：先读 [architecture/interface-map.md](architecture/interface-map.md)，再读 [architecture/data-structure-and-field-logic.md](architecture/data-structure-and-field-logic.md)、[architecture/system-architecture.md](architecture/system-architecture.md)、[architecture/runtime-architecture.md](architecture/runtime-architecture.md)、[architecture/project-structure.md](architecture/project-structure.md)。
4. 开发验证：读 [testing/test-case-catalog.md](testing/test-case-catalog.md)、[testing/layer1-regression.md](testing/layer1-regression.md) 和 [testing/pre-release-testing.md](testing/pre-release-testing.md)。
5. Skill 和工具扩展：读 [skills/skill-standard.md](skills/skill-standard.md)、[skills/host-skill.md](skills/host-skill.md)、[skills/skill-script-paths.md](skills/skill-script-paths.md)。
6. 发布和上线验收：先读 [release/README.md](release/README.md)，再按范围进入 [testing/pre-release-testing.md](testing/pre-release-testing.md)、[operations/single-user-single-sandbox.md](operations/single-user-single-sandbox.md) 和 [user-manual/README.md](user-manual/README.md)。
7. 用户操作：读 [user-manual/user-guide.md](user-manual/user-guide.md)。

## 维护规则

- `docs/` 顶层只保留本入口，不再新增业务说明文档。
- 文件名使用英文小写短横线，标题可继续使用中文。
- 需求变更先更新 `requirements/user-requirements.md`，再同步 `requirements/acceptance-and-tests.md`、`architecture/detailed-design.md`、`project/implementation-task-breakdown.md`、`testing/test-case-catalog.md` 和必要的用户手册。
- 架构变更必须同步 `architecture/project-structure.md` 或对应架构专题文档。
- 新增测试或调整回归范围必须同步 `testing/layer1-regression.md` 和 `testing/pre-release-testing.md`。
- 新增、删除或延长兼容层/回退路径，必须同步 `project/compatibility-lifecycle.md`。
- 发版、提测、部署或验收路径变化，必须同步 `release/README.md`。
- 历史阶段计划保留在 `superpowers/`，不要混入当前规范文档目录；其中可能保留当时已下线的路由或测试名，当前事实以 `requirements/`、`architecture/`、`testing/` 和源码为准。
