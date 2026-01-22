# 多模型配置

## 概述

多模型配置功能允许用户配置和使用多个 LLM 模型，支持在不同场景下使用不同的模型。通过统一的模型接口，可以轻松切换和配置不同的模型提供者。

## 功能特性

### 核心功能

- **多模型配置管理**: 配置多个模型提供者（OpenAI、Anthropic、本地模型等）
- **模型切换**: 在对话中动态切换使用的模型
- **模型参数配置**: 配置 temperature、max_tokens、top_p 等参数
- **模型性能监控**: 监控模型调用的性能和成本

### 高级功能

- **模型自动选择**: 根据任务类型自动选择最合适的模型
- **模型回退**: 当主模型失败时自动切换到备用模型
- **成本优化**: 根据任务复杂度选择成本最优的模型
- **模型对比**: 对比不同模型在相同任务上的表现

## 支持的模型提供者

### OpenAI

- GPT-4、GPT-4 Turbo
- GPT-3.5 Turbo
- 其他 OpenAI 模型

### Anthropic

- Claude 3 Opus、Sonnet、Haiku
- Claude 2.1
- 其他 Anthropic 模型

### 本地模型

- Ollama（支持多种开源模型）
- vLLM（高性能推理服务）
- 其他兼容 OpenAI API 的本地服务

### 其他提供者

- Google Gemini（通过兼容 API）
- 其他兼容 OpenAI API 格式的服务

## 数据模型

### 模型配置

```python
# app/models/model_config.py
from pydantic import BaseModel
from typing import Optional, Dict, Any
from enum import Enum

class ModelProvider(str, Enum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    OLLAMA = "ollama"
    VLLM = "vllm"
    CUSTOM = "custom"

class ModelConfig(BaseModel):
    id: str
    name: str
    provider: ModelProvider
    model_name: str  # 如 "gpt-4", "claude-3-opus-20240229"
    api_key: Optional[str] = None
    base_url: Optional[str] = None  # 自定义 API 端点
    default_params: Dict[str, Any] = {
        "temperature": 0.7,
        "max_tokens": 2000,
        "top_p": 1.0
    }
    enabled: bool = True
    metadata: Dict[str, Any] = {}  # 额外配置信息
    
    class Config:
        json_schema_extra = {
            "example": {
                "id": "model-1",
                "name": "GPT-4",
                "provider": "openai",
                "model_name": "gpt-4",
                "api_key": "sk-...",
                "default_params": {
                    "temperature": 0.7,
                    "max_tokens": 2000
                },
                "enabled": True
            }
        }
```

## 实现要点

### 模型抽象层

```python
# app/agent/llm_client.py
from abc import ABC, abstractmethod
from typing import List, Dict, Any, AsyncIterator
from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from app.models.model_config import ModelConfig, ModelProvider

class LLMClientFactory:
    """LLM 客户端工厂"""
    
    @staticmethod
    def create_client(config: ModelConfig) -> BaseChatModel:
        """根据配置创建 LLM 客户端"""
        if config.provider == ModelProvider.OPENAI:
            return ChatOpenAI(
                model_name=config.model_name,
                api_key=config.api_key,
                base_url=config.base_url,
                temperature=config.default_params.get("temperature", 0.7),
                max_tokens=config.default_params.get("max_tokens", 2000)
            )
        elif config.provider == ModelProvider.ANTHROPIC:
            return ChatAnthropic(
                model=config.model_name,
                api_key=config.api_key,
                temperature=config.default_params.get("temperature", 0.7),
                max_tokens=config.default_params.get("max_tokens", 2000)
            )
        elif config.provider == ModelProvider.OLLAMA:
            # 使用兼容 OpenAI API 的客户端
            return ChatOpenAI(
                model_name=config.model_name,
                base_url=config.base_url or "http://localhost:11434/v1",
                api_key="ollama"  # Ollama 不需要真实的 API key
            )
        else:
            raise ValueError(f"Unsupported provider: {config.provider}")
```

### 模型管理器

```python
# app/storage/model_manager.py
from typing import List, Optional, Dict
from app.models.model_config import ModelConfig
from app.agent.llm_client import LLMClientFactory
from langchain_core.language_models import BaseChatModel

class ModelManager:
    """模型管理器"""
    
    def __init__(self):
        self.configs: Dict[str, ModelConfig] = {}
        self.clients: Dict[str, BaseChatModel] = {}
        self.default_model_id: Optional[str] = None
    
    async def load_configs(self):
        """从存储加载模型配置"""
        # 从数据库或配置文件加载
        pass
    
    def register_model(self, config: ModelConfig):
        """注册模型"""
        self.configs[config.id] = config
        if config.enabled:
            self.clients[config.id] = LLMClientFactory.create_client(config)
    
    def get_client(self, model_id: Optional[str] = None) -> BaseChatModel:
        """获取模型客户端"""
        model_id = model_id or self.default_model_id
        if not model_id:
            raise ValueError("No model configured")
        
        if model_id not in self.clients:
            config = self.configs.get(model_id)
            if not config:
                raise ValueError(f"Model {model_id} not found")
            self.clients[model_id] = LLMClientFactory.create_client(config)
        
        return self.clients[model_id]
    
    def list_models(self, enabled_only: bool = False) -> List[ModelConfig]:
        """列出所有模型"""
        models = list(self.configs.values())
        if enabled_only:
            models = [m for m in models if m.enabled]
        return models
    
    def set_default_model(self, model_id: str):
        """设置默认模型"""
        if model_id not in self.configs:
            raise ValueError(f"Model {model_id} not found")
        self.default_model_id = model_id
```

### 统一的模型调用接口

```python
# app/agent/llm_service.py
from typing import List, Dict, Any, AsyncIterator
from app.storage.model_manager import ModelManager
from langchain_core.messages import BaseMessage

class LLMService:
    """统一的 LLM 服务接口"""
    
    def __init__(self, model_manager: ModelManager):
        self.model_manager = model_manager
    
    async def generate(
        self,
        messages: List[BaseMessage],
        model_id: Optional[str] = None,
        **kwargs
    ) -> str:
        """生成文本"""
        client = self.model_manager.get_client(model_id)
        response = await client.ainvoke(messages, **kwargs)
        return response.content
    
    async def stream(
        self,
        messages: List[BaseMessage],
        model_id: Optional[str] = None,
        **kwargs
    ) -> AsyncIterator[str]:
        """流式生成文本"""
        client = self.model_manager.get_client(model_id)
        async for chunk in client.astream(messages, **kwargs):
            if hasattr(chunk, 'content'):
                yield chunk.content
            else:
                yield str(chunk)
```

### 模型自动选择

```python
# app/agent/model_selector.py
from typing import Optional
from app.models.model_config import ModelConfig

class ModelSelector:
    """模型选择器"""
    
    def __init__(self, model_manager: ModelManager):
        self.model_manager = model_manager
    
    def select_model(
        self,
        task_type: Optional[str] = None,
        complexity: str = "medium"
    ) -> str:
        """根据任务类型和复杂度选择模型"""
        models = self.model_manager.list_models(enabled_only=True)
        
        # 简单任务使用成本较低的模型
        if complexity == "simple":
            for model in models:
                if "gpt-3.5" in model.model_name or "haiku" in model.model_name:
                    return model.id
        
        # 复杂任务使用能力强的模型
        if complexity == "complex":
            for model in models:
                if "gpt-4" in model.model_name or "opus" in model.model_name:
                    return model.id
        
        # 默认返回默认模型
        return self.model_manager.default_model_id
```

## API 设计

### RESTful API 端点

- `GET /api/settings/models`: 获取所有模型配置
- `POST /api/settings/models`: 添加新模型配置
- `PUT /api/settings/models/{id}`: 更新模型配置
- `DELETE /api/settings/models/{id}`: 删除模型配置
- `POST /api/settings/models/{id}/enable`: 启用模型
- `POST /api/settings/models/{id}/disable`: 禁用模型
- `POST /api/settings/models/{id}/set-default`: 设置默认模型
- `POST /api/settings/models/{id}/test`: 测试模型连接

### 请求/响应示例

**添加模型配置**:
```json
POST /api/settings/models

Request:
{
  "name": "GPT-4",
  "provider": "openai",
  "model_name": "gpt-4",
  "api_key": "sk-...",
  "default_params": {
    "temperature": 0.7,
    "max_tokens": 2000
  }
}

Response:
{
  "id": "model-1",
  "name": "GPT-4",
  "provider": "openai",
  "model_name": "gpt-4",
  "enabled": true,
  "status": "connected"
}
```

**设置默认模型**:
```json
POST /api/settings/models/model-1/set-default

Response:
{
  "message": "Default model set to GPT-4"
}
```

## 最佳实践

1. **API Key 安全**: 使用环境变量或加密存储 API Key
2. **模型缓存**: 缓存模型客户端，避免重复创建
3. **错误处理**: 实现模型调用失败时的重试和回退机制
4. **成本监控**: 记录模型调用次数和成本，设置使用限制
5. **性能优化**: 根据任务选择合适的模型，平衡性能和成本

## 参考资源

- [LangChain LLM 文档](https://python.langchain.com/docs/modules/model_io/)
- [OpenAI API 文档](https://platform.openai.com/docs/api-reference)
- [Anthropic API 文档](https://docs.anthropic.com/claude/reference)
