# 书童四九文档中心

本文是项目文档的唯一入口。新增文档前先判断归属目录，避免继续在 `docs/` 顶层堆文件。

## 目录规范

| 目录 | 用途 | 代表文档 |
|------|------|----------|
| `requirements/` | 用户需求、验收口径、需求追踪矩阵 | [user-requirements.md](requirements/user-requirements.md)、[acceptance-and-tests.md](requirements/acceptance-and-tests.md) |
| `contracts/` | 字段、接口、运行、环境变量和 Prompt 组装契约源头 | [runtime-interface-contract.md](contracts/runtime-interface-contract.md)、[data-structure-and-field-logic.md](contracts/data-structure-and-field-logic.md)、[user-env-vars-contract.md](contracts/user-env-vars-contract.md)、[prompt-assembly-contract.md](contracts/prompt-assembly-contract.md) |
| `design/` | 正式详细设计和接口说明 | [detailed-design-spec.md](design/detailed-design-spec.md)、[interface-document.md](design/interface-document.md)、[collaborative-prompt-template-design.md](design/collaborative-prompt-template-design.md) |
| `architecture/` | 架构图、项目结构、资源包和运行边界说明 | [system-architecture.md](architecture/system-architecture.md)、[project-structure.md](architecture/project-structure.md)、[scenario-bundle-export.md](architecture/scenario-bundle-export.md)、[images-and-dependencies.md](architecture/images-and-dependencies.md) |
| `testing/` | 测试用例、契约实施追踪、回归测试、上线前测试、全流程业务测试 | [test-case-catalog.md](testing/test-case-catalog.md)、[contract-traceability-matrix.md](testing/contract-traceability-matrix.md)、[layer1-regression.md](testing/layer1-regression.md)、[pre-release-testing.md](testing/pre-release-testing.md)、[full-flow-business-tests.md](testing/full-flow-business-tests.md) |
| `user-manual/` | 面向用户和验收人员的操作手册、截图、PDF | [user-guide.md](user-manual/user-guide.md)、[README.md](user-manual/README.md) |
| `skills/` | Skill 规范、主持人 Skill、脚本路径、沙箱工具接口 | [skill-standard.md](skills/skill-standard.md)、[host-skill.md](skills/host-skill.md)、[skill-script-paths.md](skills/skill-script-paths.md)、[sandbox-tool-interface.md](skills/sandbox-tool-interface.md) |
| `development/` | 面向开发者和 AI 编程代理的代码书写规范、模块拆分边界 | [coding-standard.md](development/coding-standard.md)、[module-file-boundaries.md](development/module-file-boundaries.md) |
| `operations/` | 部署、运行、沙箱和运维约束 | [single-user-single-sandbox.md](operations/single-user-single-sandbox.md) |
| `release/` | 发版、提测、部署和验收的统一入口 | [README.md](release/README.md) |

## 推荐阅读顺序

1. 产品和验收：先读 [requirements/user-requirements.md](requirements/user-requirements.md)，再读 [requirements/acceptance-and-tests.md](requirements/acceptance-and-tests.md)。
2. 字段、运行、环境变量和 Prompt 契约：读 [contracts/runtime-interface-contract.md](contracts/runtime-interface-contract.md)、[contracts/data-structure-and-field-logic.md](contracts/data-structure-and-field-logic.md)、[contracts/user-env-vars-contract.md](contracts/user-env-vars-contract.md) 和 [contracts/prompt-assembly-contract.md](contracts/prompt-assembly-contract.md)。
3. 设计和接口：读 [design/detailed-design-spec.md](design/detailed-design-spec.md) 和 [design/interface-document.md](design/interface-document.md)。
4. 架构和代码入口：读 [architecture/system-architecture.md](architecture/system-architecture.md) 和 [architecture/project-structure.md](architecture/project-structure.md)。
5. 开发验证：读 [testing/test-case-catalog.md](testing/test-case-catalog.md)、[testing/contract-traceability-matrix.md](testing/contract-traceability-matrix.md)、[testing/layer1-regression.md](testing/layer1-regression.md) 和 [testing/pre-release-testing.md](testing/pre-release-testing.md)。
6. 代码书写和拆分：读 [development/coding-standard.md](development/coding-standard.md) 和 [development/module-file-boundaries.md](development/module-file-boundaries.md)。
7. Skill 和工具扩展：读 [skills/skill-standard.md](skills/skill-standard.md)、[skills/host-skill.md](skills/host-skill.md)、[skills/skill-script-paths.md](skills/skill-script-paths.md)。
8. 发布和上线验收：先读 [release/README.md](release/README.md)，再按范围进入 [testing/pre-release-testing.md](testing/pre-release-testing.md)、[operations/single-user-single-sandbox.md](operations/single-user-single-sandbox.md) 和 [user-manual/README.md](user-manual/README.md)。
9. 用户操作：读 [user-manual/user-guide.md](user-manual/user-guide.md)。

## 维护规则

- `docs/` 顶层只保留本入口，不再新增业务说明文档。
- 文件名使用英文小写短横线，标题可继续使用中文。
- 需求变更先更新 `requirements/user-requirements.md`，再同步 `requirements/acceptance-and-tests.md`、`design/detailed-design-spec.md`、`testing/test-case-catalog.md` 和必要的用户手册。
- 字段、接口、运行逻辑、平台内用户级环境变量或平台内置 Prompt 组装变更先更新 `contracts/`，再同步 `design/`、测试和用户手册。
- 架构变更必须同步 `architecture/project-structure.md` 或对应架构专题文档。
- 新增测试或调整回归范围必须同步 `testing/contract-traceability-matrix.md`、`testing/layer1-regression.md` 和 `testing/pre-release-testing.md`。
- 代码组织、模块边界、AI 编程约束或重写策略变化，必须同步 `development/`。
- 发版、提测、部署或验收路径变化，必须同步 `release/README.md`。
