# OpenSandbox 灰度切换方案

## 阶段 0：兼容发布
- 默认保留本地 fallback（`OPEN_SANDBOX_ENABLED` 关闭时）。
- 新链路上线：`UnifiedToolGateway -> SandboxService -> OpenSandboxAdapter`。
- 验证指标：沙箱创建成功率、执行超时率、审计事件完整率。

## 阶段 1：开发环境灰度
- 在开发环境开启 `OPEN_SANDBOX_ENABLED=1`。
- 重点验证挂载：
  - `/workspace`（读写）
  - `/skill/scripts`（只读）
  - `/skill/config`（只读）
- 验证相同 `dep_hash` 下 `base_image_ref` 命中复用。

## 阶段 2：小流量生产灰度
- 选择 5%-10% 会话开启 OpenSandbox。
- 重点检查：
  - `1 session = 1 sandbox` 是否严格生效。
  - 审计事件 `sandbox_*` 是否全链路可检索。
  - 失败回退是否自动降级到本地 adapter（仅应急）。

## 阶段 3：全量切换
- 全量启用 OpenSandbox。
- 禁止运行时临时安装依赖，统一走依赖镜像模板。
- 开启定期回收：按会话 TTL 清理空闲 sandbox。

## 回滚策略
- 一键回滚：关闭 `OPEN_SANDBOX_ENABLED`。
- 保留审计：即使回滚，`sandbox_*` 审计事件仍写入，便于复盘。
