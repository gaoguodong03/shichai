# 文档规范

## 目标

项目文档应同时服务 4 类读者：用户、开发者、测试/验收人员、部署运维人员。每份文档必须有明确归属目录和维护责任，不再使用零散的顶层中文文件名。

## 文件位置

| 文档类型 | 放置目录 | 命名示例 |
|----------|----------|----------|
| 用户需求、验收追踪 | `docs/requirements/` | `user-requirements.md`、`acceptance-and-tests.md` |
| 字段、接口和运行契约源头 | `docs/contracts/` | `runtime-interface-contract.md`、`data-structure-and-field-logic.md` |
| 正式设计交付物 | `docs/design/` | `detailed-design-spec.md`、`interface-document.md` |
| 架构图、项目结构和资源边界 | `docs/architecture/` | `system-architecture.md`、`project-structure.md`、`scenario-bundle-export.md` |
| 测试用例、回归、上线验收 | `docs/testing/` | `test-case-catalog.md`、`layer1-regression.md`、`pre-release-testing.md` |
| 用户教程、验收手册、截图 | `docs/user-manual/` | `user-guide.md`、`README.md` |
| Skill、MCP、沙箱工具契约 | `docs/skills/` | `skill-standard.md`、`host-skill.md`、`sandbox-tool-interface.md` |
| 代码书写规范和模块拆分边界 | `docs/development/` | `coding-standard.md`、`module-file-boundaries.md` |
| 部署和运维约束 | `docs/operations/` | `single-user-single-sandbox.md` |
| 发布、提测、部署和验收入口 | `docs/release/` | `README.md` |

## 层级含义

- `contracts/` 是字段和运行契约的唯一源头。涉及请求字段、SSE、主持人调度、运行态、资源身份和落盘结构时，先改这里。
- `design/` 是正式详细设计和接口说明交付物。它只能引用或派生 `contracts/` 的字段定义，不能单独新增字段口径。
- `architecture/` 只放结构性说明、架构图、项目结构、资源包和用户资源存储边界，不维护运行字段表。
- `skills/` 只放 Skill、主持人 Skill、脚本和沙箱工具规范。涉及运行态字段时必须对齐 `contracts/`。
- `development/` 放代码书写规范、模块拆分边界和面向 AI 编程代理的工程约束。它只能引用 `contracts/` 和 `design/` 的目标口径，不能单独定义字段契约。
- `testing/` 只放测试策略、回归清单和验收用例，不承担需求或字段源头职责。
- 旧项目管理目录和旧阶段计划目录不再作为正式文档目录使用；历史计划、旧审计和兼容台账不进入当前文档入口。

## 命名规则

- 文件名使用英文小写、数字和短横线，例如 `pre-release-testing.md`。
- 文档标题使用中文，保持业务可读性。
- 图片和附件放到所属目录的 `images/` 或 `assets/` 下。
- 不提交 `.DS_Store`、临时导出包、构建产物和本地运行状态。

## 变更同步规则

| 变更类型 | 必须同步 |
|----------|----------|
| 用户需求新增或删除 | `requirements/user-requirements.md`、`requirements/acceptance-and-tests.md`、`design/detailed-design-spec.md`、`testing/test-case-catalog.md` |
| 验收标准变化 | `requirements/acceptance-and-tests.md`、`testing/test-case-catalog.md`、`testing/layer1-regression.md`、`testing/pre-release-testing.md` |
| API 或模块边界变化 | `contracts/runtime-interface-contract.md`、`design/interface-document.md`、`design/detailed-design-spec.md`、必要时同步 `architecture/project-structure.md` |
| 数据结构或字段变化 | `contracts/data-structure-and-field-logic.md`、必要时同步 `contracts/runtime-interface-contract.md` |
| 代码组织、模块边界或 AI 编程约束变化 | `development/coding-standard.md`、`development/module-file-boundaries.md`、必要时同步 `architecture/project-structure.md` |
| Skill/MCP/沙箱契约变化 | `skills/*.md`、必要时同步 `operations/*.md` |
| 用户操作路径变化 | `user-manual/user-guide.md`、`user-manual/README.md` 和截图脚本 |
| 部署方式变化 | `README.md`、`release/README.md`、`operations/*.md`、`testing/pre-release-testing.md` |

## 文档质量检查

提交前至少执行：

```bash
rtk git diff --check -- docs
```

涉及代码或测试入口变化时，还需执行对应测试命令；上线前最低门槛见 `docs/testing/pre-release-testing.md`。
