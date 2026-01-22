# 记忆功能

## 概述

记忆功能负责管理 Agent 的短期和长期记忆，帮助 Agent 在对话中保持上下文和知识。记忆系统采用分层设计，包括 Session 级别的短期记忆和跨 Session 的长期记忆。

## 功能特性

### Session 级别记忆（短期记忆）

Session 级别的记忆用于管理单次对话会话中的上下文信息：

- **对话上下文管理**: 维护对话历史，包括用户消息和 Agent 回复
- **Session 内的信息持久化**: 将对话内容保存到数据库，支持会话恢复
- **上下文窗口管理**: 智能管理上下文长度，避免超出模型限制
- **工具调用记忆**: 记录工具调用历史，帮助 Agent 理解之前的操作

#### 实现方式

```python
from typing import List, Dict, Any
from pydantic import BaseModel
from datetime import datetime

class Message(BaseModel):
    role: str  # "user" 或 "assistant"
    content: str
    timestamp: datetime
    tool_calls: List[Dict[str, Any]] = []

class SessionMemory(BaseModel):
    session_id: str
    messages: List[Message] = []
    created_at: datetime
    updated_at: datetime
    
    def add_message(self, message: Message):
        """添加消息到上下文"""
        self.messages.append(message)
        self.updated_at = datetime.now()
    
    def get_recent_context(self, max_tokens: int = 4000) -> List[Message]:
        """获取最近的上下文，不超过最大 token 数"""
        # 实现智能截断逻辑
        # 优先保留最近的对话和重要的工具调用
        pass
```

### 长期记忆（待定）

长期记忆用于跨 Session 的知识存储和检索：

- **跨 Session 的知识存储**: 存储 Agent 学到的持久化知识
- **知识检索和更新**: 使用向量数据库或传统数据库存储和检索知识
- **知识关联**: 建立知识之间的关联关系

**注意**: 长期记忆功能暂不实现，当前版本专注于 Session 级别的记忆管理。

## 实现要点

### Session 级别的记忆实现

#### 数据模型

```python
# app/models/session.py
from sqlalchemy import Column, String, DateTime, JSON
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()

class SessionModel(Base):
    __tablename__ = "sessions"
    
    id = Column(String, primary_key=True)
    title = Column(String)  # 会话标题（自动生成）
    messages = Column(JSON)  # 消息列表
    created_at = Column(DateTime)
    updated_at = Column(DateTime)
```

#### 记忆管理器

```python
# app/storage/memory.py
from typing import List, Optional
from app.models.session import SessionModel
from app.models.message import Message

class SessionMemoryManager:
    def __init__(self, db_session):
        self.db = db_session
    
    async def get_session_memory(self, session_id: str) -> Optional[SessionModel]:
        """获取 Session 的记忆"""
        return await self.db.get(SessionModel, session_id)
    
    async def add_message(self, session_id: str, message: Message):
        """添加消息到 Session 记忆"""
        session = await self.get_session_memory(session_id)
        if not session:
            session = SessionModel(id=session_id, messages=[])
        
        session.messages.append(message.dict())
        session.updated_at = datetime.now()
        await self.db.commit()
    
    async def get_context(self, session_id: str, max_tokens: int = 4000) -> List[Message]:
        """获取上下文，智能截断"""
        session = await self.get_session_memory(session_id)
        if not session:
            return []
        
        messages = [Message(**msg) for msg in session.messages]
        # 实现智能截断逻辑
        return self._truncate_context(messages, max_tokens)
    
    def _truncate_context(self, messages: List[Message], max_tokens: int) -> List[Message]:
        """智能截断上下文"""
        # 优先保留最近的对话
        # 保留重要的工具调用结果
        # 使用 token 估算器计算 token 数
        pass
```

### 上下文窗口管理

#### Token 估算

```python
# app/utils/token_counter.py
import tiktoken

class TokenCounter:
    def __init__(self, model: str = "gpt-4"):
        self.encoding = tiktoken.encoding_for_model(model)
    
    def count_tokens(self, text: str) -> int:
        """计算文本的 token 数"""
        return len(self.encoding.encode(text))
    
    def estimate_messages_tokens(self, messages: List[Message]) -> int:
        """估算消息列表的 token 数"""
        total = 0
        for msg in messages:
            total += self.count_tokens(msg.content)
            # 加上工具调用的 token
            for tool_call in msg.tool_calls:
                total += self.count_tokens(str(tool_call))
        return total
```

#### 智能截断策略

1. **保留最近的对话**: 优先保留最近的用户消息和 Agent 回复
2. **保留工具调用**: 保留重要的工具调用结果，即使时间较久
3. **摘要压缩**: 对于过长的历史对话，可以生成摘要
4. **关键信息提取**: 提取关键信息（如用户偏好、重要事实）单独存储

### 记忆检索和更新机制

#### 检索接口

```python
class MemoryRetriever:
    async def search_messages(
        self, 
        session_id: str, 
        query: str, 
        limit: int = 10
    ) -> List[Message]:
        """搜索相关消息"""
        # 使用向量搜索或关键词搜索
        pass
    
    async def get_tool_call_history(
        self, 
        session_id: str, 
        tool_name: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """获取工具调用历史"""
        pass
```

## API 设计

### RESTful API 端点

- `GET /api/sessions/{id}/memory`: 获取 Session 的记忆
- `POST /api/sessions/{id}/memory/messages`: 添加消息到记忆
- `GET /api/sessions/{id}/memory/context`: 获取上下文（智能截断）
- `DELETE /api/sessions/{id}/memory`: 清空 Session 记忆

### 请求/响应示例

**获取上下文**:
```json
GET /api/sessions/session-123/memory/context?max_tokens=4000

Response:
{
  "messages": [
    {
      "role": "user",
      "content": "Hello",
      "timestamp": "2024-01-01T00:00:00Z"
    },
    {
      "role": "assistant",
      "content": "Hi! How can I help you?",
      "timestamp": "2024-01-01T00:00:01Z"
    }
  ],
  "token_count": 15,
  "truncated": false
}
```

## 最佳实践

1. **定期清理**: 定期清理过期的 Session 记忆，释放存储空间
2. **压缩存储**: 对于长期不活跃的 Session，可以压缩存储
3. **隐私保护**: 确保用户数据的隐私和安全
4. **性能优化**: 使用缓存减少数据库查询
5. **错误恢复**: 实现记忆恢复机制，防止数据丢失

## 未来扩展

### 长期记忆实现（计划中）

- **向量数据库**: 使用 Pinecone、Weaviate 或 Chroma 存储知识向量
- **知识图谱**: 建立知识之间的关联关系
- **语义搜索**: 支持语义相似度搜索
- **知识更新**: 支持知识的增量更新和版本管理

## 参考资源

- [LangChain Memory 文档](https://python.langchain.com/docs/modules/memory)
- [向量数据库对比](https://www.pinecone.io/learn/vector-database/)
