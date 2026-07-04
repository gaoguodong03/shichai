# LLM 提供者切换设计

本文档说明如何更换大模型提供者（如接入 jeniya、其他 OpenAI 兼容 API），以及后续可做的配置化改进。

---

## 一、快速切换：通过 .env（当前即可用）

当前 `QwenLLM` 已通过 `ChatOpenAI` 使用 **OpenAI 兼容 API**，只需修改环境变量即可指向任意兼容服务。

### 1.1 接入 jeniya 等 OpenAI 兼容 API

**步骤**：在 `backend/.env` 中修改或新增：

```env
# 覆盖默认 Qwen 配置，指向 jeniya 或其他 OpenAI 兼容 API
QWEN_API_KEY=你的API_KEY
QWEN_BASE_URL=https://你的API基础地址/v1
QWEN_MODEL=gpt-4o
```

**注意**：

- **API Key**：请勿提交到 Git，通过 `.env` 或环境变量配置。
- **Base URL**：文档页 URL 不是 API 地址。jeniya 对话 API 的 base URL 见下节。
- **模型名**：按提供方支持填写，如 `gpt-4o`、`gpt-4` 等。

### 1.2 jeniya 接入示例

根据 [jeniya GPTs 对话 API 文档](https://api-jeniya-top.apifox.cn/api-381392203) 的 OpenAPI 规范：

- **Base URL**：`https://jeniya.top/v1`（`servers.url` 为 `https://jeniya.top`，接口路径为 `/v1/chat/completions`）
- **模型**：支持 `gpt-4o` 等标准模型；GPTs 格式为 `gpt-4-gizmo-g-{id}`

在 `backend/.env` 中设置（请将 `你的API_KEY` 替换为实际 Key，勿提交到 Git）：

```env
QWEN_API_KEY=你的API_KEY
QWEN_BASE_URL=https://jeniya.top/v1
QWEN_MODEL=gpt-4o
```

### 1.3 环境变量说明

| 变量 | 说明 | 默认 |
|------|------|------|
| `QWEN_API_KEY` | API Key | 必填 |
| `QWEN_BASE_URL` | API 基础地址（含 `/v1`） | 阿里云 DashScope |
| `QWEN_MODEL` | 模型名称 | `qwen3-max` |
| `QWEN_REQUEST_TIMEOUT` | 请求超时（秒） | 180 |
| `QWEN_MAX_RETRIES` | 重试次数 | 2 |

---

## 二、可优化点：配置化 LLM 选择

当前 `app_settings` 中有 `default_llm`，但 `chat.py` 仍固定使用 `QwenLLM()`，未从配置读取。

### 2.1 目标

- 支持从 `app_settings` 或独立配置文件选择 LLM 提供者
- 用户可在 UI 中切换模型，无需改 `.env`

### 2.2 配置结构建议

**当前实现：`settings/app.json` + `resources/models`**

```json
{
  "default_llm": "jeniya",
  "system_prompt": ""
}
```

- `settings/app.json` 保存 `default_llm`、系统提示词、主持人配置等账号级设置。
- `resources/models/<model_provider_id>/model.json` 保存每个 provider 的 `base_url`、`model`、密钥引用或环境变量名。
- `api_key_env`：从环境变量读取 API Key，不落库
- 新增提供者时只改配置，不改代码

### 2.3 代码改动点

1. **`llm_client.py`**
   - 新增 `get_llm_from_config(provider_id: str) -> QwenLLM`（或通用接口）
   - 根据 `provider_id` 从配置读取 `base_url`、`model`，从 `api_key_env` 对应环境变量取 Key

2. **`chat.py`**
   - `app_settings = load_app_settings()`
   - `provider_id = app_settings.get("default_llm", "qwen")`
   - `llm = get_llm_from_config(provider_id)`

3. **`settings_skills.py`**
   - `GET/PUT /settings/app` 支持读写 `default_llm`、`llm_providers`

---

## 三、实施顺序建议

1. **短期**：先用 `.env` 切换（本节一），立即可用
2. **中期**：实现方案 A，从 `app_settings` 读取 `default_llm` 和 provider 配置
3. **长期**：若需多模型、前端选择，再引入 `llm_providers.json` 与相应 API

---

## 五、实现状态

| 项目 | 状态 | 说明 |
|------|------|------|
| .env 快速切换 | ✅ 已可用 | 修改 QWEN_* 即可 |
| 配置化模型选择 | ✅ 已实现 | `settings/app.json` 含 `default_llm`；provider 落在 `resources/models` |
| `get_llm_from_config` | ✅ | `llm_client.py`，按 provider_id 从配置新建 LLM |
| `chat.py` 读取配置 | ✅ | 每次请求从 `load_app_settings()` 取 `default_llm` |
| 设置 UI | ✅ | AppSettingsView 支持 LLM 下拉选择（qwen、jeniya 等） |

---

## 四、安全提醒

- **API Key 只放环境变量**，不要写入 JSON 配置文件或代码
- 确保 `backend/.env` 在 `.gitignore` 中
- 使用 `api_key_env` 这类字段引用环境变量名，而不是直接存 Key
