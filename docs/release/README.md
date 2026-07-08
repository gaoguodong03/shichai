# 发布与验收入口

本文是发版、提测、部署和上线验收的阅读入口。

## 阅读顺序

1. 上线前回归：[pre-release-testing.md](../testing/pre-release-testing.md)
2. 自动化回归：[layer1-regression.md](../testing/layer1-regression.md)
3. 全流程业务测试：[full-flow-business-tests.md](../testing/full-flow-business-tests.md)
4. 部署和沙箱约束：[single-user-single-sandbox.md](../operations/single-user-single-sandbox.md)
5. 用户验收手册：[user-guide.md](../user-manual/user-guide.md)

## 变更规则

- 发版流程变化时，同步更新本文和 `docs/testing/pre-release-testing.md`。
- 部署方式变化时，同步更新 `README.md`、`docs/operations/` 和相关测试入口。
- 字段、接口或运行逻辑变化时，先更新 `docs/contracts/`，再更新发布验收说明。
