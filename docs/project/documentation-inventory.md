# 文档清单状态表

本文用于说明当前文档体系中每类文档的状态和维护口径。若新增文档，应先更新本表和 `docs/README.md`。

## 当前规范文档

| 文档 | 状态 | 维护口径 |
|------|------|----------|
| `docs/README.md` | 当前有效 | 文档总入口和目录导航 |
| `docs/documentation-standard.md` | 当前有效 | 文档位置、命名、同步规则 |
| `docs/requirements/user-requirements.md` | 当前有效 | 用户需求、UR 编号、优先级和成功指标 |
| `docs/requirements/acceptance-and-tests.md` | 当前有效 | UR 到模块、测试、手工验收的追踪矩阵 |
| `docs/architecture/overview.md` | 当前有效 | 系统架构总览 |
| `docs/architecture/system-architecture.md` | 当前有效 | 架构图和 UR 到架构层映射 |
| `docs/architecture/api-design.md` | 当前有效 | 当前后端 API 总览、认证和主要端点 |
| `docs/architecture/project-structure.md` | 当前有效 | 代码目录、文档目录和模块职责 |
| `docs/architecture/runtime-architecture.md` | 当前有效 | 面向新人理解的一次会话运行链路 |
| `docs/architecture/runtime-flow-overview.md` | 当前有效 | 进程启动、身份、会话流、编排逻辑 |
| `docs/architecture/user-resource-store/README.md` | 当前有效 | 用户资源目录、隔离和迁移约定 |
| `docs/architecture/user-resource-store/storage-standard.md` | 当前有效 | 用户资源存储标准 |
| `docs/architecture/scenario-bundle-export.md` | 当前有效 | 场景资源包导入导出格式 |
| `docs/architecture/images-and-dependencies.md` | 当前有效 | 镜像、依赖和沙箱边界 |
| `docs/architecture/llm-provider-switch.md` | 当前有效 | LLM Provider 切换说明 |
| `docs/architecture/llm-prompt-structure.md` | 当前有效 | LLM 输入消息结构和提示词来源 |
| `docs/testing/layer1-regression.md` | 当前有效 | 第一层回归范围和 UR 覆盖 |
| `docs/testing/pre-release-testing.md` | 当前有效 | 上线前模块化测试和按 UR 验收 |
| `docs/testing/full-flow-business-tests.md` | 当前有效 | 全流程业务测试汇总 |
| `docs/user-manual/user-guide.md` | 当前有效 | 面向最终用户的操作说明 |
| `docs/user-manual/README.md` | 当前有效 | 上线验收操作手册源文档 |
| `docs/skills/skill-standard.md` | 当前有效 | Skill 编写、绑定和会话状态规范 |
| `docs/skills/skill-script-paths.md` | 当前有效 | Skill 脚本路径、工作区和沙箱路径 |
| `docs/skills/sandbox-tool-interface.md` | 当前有效 | 沙箱工具调用接口 |
| `docs/operations/single-user-single-sandbox.md` | 当前有效 | 单用户单沙箱运行约束 |
| `docs/project/worklist.md` | 当前有效 | 项目工作清单 |
| `docs/project/documentation-audit.md` | 当前有效 | 文档整理审计记录 |
| `docs/project/documentation-inventory.md` | 当前有效 | 本清单 |
| `docs/presentations/15-minute-technical-brief.md` | 当前有效 | 介绍讲稿 |

## 历史或辅助文档

| 路径 | 状态 | 说明 |
|------|------|------|
| `docs/superpowers/specs/` | 历史规格 | 保留当时的设计上下文，不保证其中旧路由、测试名仍是当前事实 |
| `docs/superpowers/plans/` | 历史实施计划 | 保留阶段性执行记录，不作为当前 API 或产品承诺 |
| `docs/user-manual/assets/` | 辅助脚本 | 用于截图和 PDF 导出 |
| `docs/user-manual/images/` | 辅助资产 | 用户手册和验收手册截图 |
| `docs/user-manual/书童四九上线验收操作手册.pdf` | 生成物 | 面向验收分发，源文件以 `docs/user-manual/README.md` 为准 |
| `docs/presentations/*.pptx` | 演示材料 | 面向汇报和客户沟通 |

## 完成标准

当前文档体系满足以下条件时，视为规范状态：

- `docs/` 顶层不再保留业务散文档。
- 当前规范文档中的相对 Markdown 链接全部可解析。
- 当前规范文档不再承诺已下线的公开分享链接。
- API、认证、会话、资源导入导出、Skill/MCP/沙箱路径与当前代码一致。
- 第一层回归通过。
