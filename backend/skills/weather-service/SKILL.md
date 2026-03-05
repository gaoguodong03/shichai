---
description: 用 call_api 调用聚合数据简单天气接口，查询指定城市当前天气，验证 service/API 调用链路。
enabled: true
mcp_server_ids: []
name: 简单 service 测试- 城市天气查询（API）
---
# 城市天气查询 Skill

**目标**：给出城市名 → 实际调一次天气 API。

## 使用说明（给 Agent 看）

- 只用一个工具：`call_api`。
- 始终按下面方式调用（不要自己猜结果，也不要解释 HTTP 协议细节）：

```text
url = "https://apis.juhe.cn/simpleWeather/query?city={city_encoded}&key={key}"
method = "GET"
headers_json = ""
body = ""
```

- 参数约定：
  - `{city_encoded}`：把用户给的城市名做 UTF-8 URL 编码（如「郑州」「上海」）。
  - `{key}`：若用户没给，就用默认 `a902df9be5269ded95457ebe801af6aa`。

## 返回给用户怎么说

1. 从 `call_api` 的返回中，提取当前城市、天气现象、温度、湿度等关键信息。
2. 如果接口返回错误（例如 key 无效、超限等），直接复述接口里的 `reason` / 错误信息，**不要编造「缺少 http/https」这类原因**，也不要胡猜天气数据。
