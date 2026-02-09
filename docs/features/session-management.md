# Session 管理

## 概述

Session 管理功能负责管理用户的**轮对话**，包括创建、切换、删除和历史记录管理。每个 Session 代表**一轮**独立的对话会话，拥有自己的上下文记忆和状态。

> **术语**：Session = 轮对话。新建对话、历史会话列表、切换会话都在这一层。每轮内的每一次「用户消息 + 助手回复」称为一次 **Turn**（轮内对话）。详见 [会话、轮对话与记忆设计](../architecture/session-round-memory.md)。

## 功能特性

### 核心功能

- **创建新 Session**: 用户可以创建新的对话会话
- **切换不同 Session**: 在多个 Session 之间快速切换
- **删除 Session**: 删除不再需要的 Session
- **Session 历史记录**: 查看和管理所有 Session 的历史
- **Session 级别的状态管理**: 每个 Session 维护独立的状态和配置

### 高级功能

- **Session 标题自动生成**: 根据对话内容自动生成 Session 标题
- **Session 搜索**: 支持按标题、内容搜索 Session
- **Session 导出/导入**: 导出 Session 数据，支持备份和恢复
- **Session 共享**: 分享 Session 给其他用户（可选功能）

## 数据模型

### Session 模型

```python
# app/models/session.py
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from datetime import datetime
from enum import Enum

class SessionStatus(str, Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"
    DELETED = "deleted"

class Session(BaseModel):
    id: str
    title: str
    status: SessionStatus = SessionStatus.ACTIVE
    messages: List[Dict[str, Any]] = []
    metadata: Dict[str, Any] = {}  # 存储额外信息（模型、配置等）
    created_at: datetime
    updated_at: datetime
    last_message_at: Optional[datetime] = None
    
    class Config:
        json_schema_extra = {
            "example": {
                "id": "session-123",
                "title": "关于 Python 编程的讨论",
                "status": "active",
                "messages": [],
                "metadata": {
                    "model": "gpt-4",
                    "temperature": 0.7
                },
                "created_at": "2024-01-01T00:00:00Z",
                "updated_at": "2024-01-01T00:00:00Z"
            }
        }
```

### 数据库模型

```python
# app/storage/database.py
from sqlalchemy import Column, String, DateTime, JSON, Enum
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()

class SessionModel(Base):
    __tablename__ = "sessions"
    
    id = Column(String, primary_key=True)
    title = Column(String, nullable=False)
    status = Column(Enum(SessionStatus), default=SessionStatus.ACTIVE)
    messages = Column(JSON, default=list)
    metadata = Column(JSON, default=dict)
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False)
    last_message_at = Column(DateTime, nullable=True)
```

## 实现要点

### Session 管理器

```python
# app/storage/session_manager.py
from typing import List, Optional
from app.models.session import Session, SessionStatus
from app.storage.database import SessionModel
from sqlalchemy.orm import Session as DBSession

class SessionManager:
    def __init__(self, db: DBSession):
        self.db = db
    
    async def create_session(
        self, 
        title: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Session:
        """创建新 Session"""
        session_id = self._generate_session_id()
        session = SessionModel(
            id=session_id,
            title=title or "新对话",
            status=SessionStatus.ACTIVE,
            messages=[],
            metadata=metadata or {},
            created_at=datetime.now(),
            updated_at=datetime.now()
        )
        self.db.add(session)
        self.db.commit()
        return Session.from_orm(session)
    
    async def get_session(self, session_id: str) -> Optional[Session]:
        """获取 Session"""
        session = self.db.query(SessionModel).filter(
            SessionModel.id == session_id
        ).first()
        return Session.from_orm(session) if session else None
    
    async def list_sessions(
        self, 
        status: Optional[SessionStatus] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[Session]:
        """列出 Session"""
        query = self.db.query(SessionModel)
        if status:
            query = query.filter(SessionModel.status == status)
        
        sessions = query.order_by(
            SessionModel.updated_at.desc()
        ).limit(limit).offset(offset).all()
        
        return [Session.from_orm(s) for s in sessions]
    
    async def update_session(
        self, 
        session_id: str, 
        title: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Optional[Session]:
        """更新 Session"""
        session = self.db.query(SessionModel).filter(
            SessionModel.id == session_id
        ).first()
        
        if not session:
            return None
        
        if title:
            session.title = title
        if metadata:
            session.metadata.update(metadata)
        
        session.updated_at = datetime.now()
        self.db.commit()
        return Session.from_orm(session)
    
    async def delete_session(self, session_id: str) -> bool:
        """删除 Session（软删除）"""
        session = self.db.query(SessionModel).filter(
            SessionModel.id == session_id
        ).first()
        
        if not session:
            return False
        
        session.status = SessionStatus.DELETED
        session.updated_at = datetime.now()
        self.db.commit()
        return True
    
    async def archive_session(self, session_id: str) -> bool:
        """归档 Session"""
        session = self.db.query(SessionModel).filter(
            SessionModel.id == session_id
        ).first()
        
        if not session:
            return False
        
        session.status = SessionStatus.ARCHIVED
        session.updated_at = datetime.now()
        self.db.commit()
        return True
    
    def _generate_session_id(self) -> str:
        """生成 Session ID"""
        import uuid
        return f"session-{uuid.uuid4().hex[:12]}"
```

### Session 标题自动生成

```python
# app/utils/session_title.py
from app.agent.llm_client import LLMClient

class SessionTitleGenerator:
    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client
    
    async def generate_title(self, messages: List[Dict[str, Any]]) -> str:
        """根据对话内容生成标题"""
        if not messages:
            return "新对话"
        
        # 取前几条消息作为上下文
        context = "\n".join([
            f"{msg['role']}: {msg['content'][:100]}"
            for msg in messages[:3]
        ])
        
        prompt = f"""根据以下对话内容，生成一个简洁的标题（不超过20个字）：

{context}

标题："""
        
        title = await self.llm.generate(prompt, max_tokens=20)
        return title.strip().strip('"').strip("'")
```

### 支持多 Session 并发

```python
# app/storage/session_store.py
from typing import Dict
from app.models.session import Session

class SessionStore:
    """内存中的 Session 存储，用于快速访问"""
    def __init__(self):
        self.sessions: Dict[str, Session] = {}
    
    def get(self, session_id: str) -> Optional[Session]:
        """从内存获取 Session"""
        return self.sessions.get(session_id)
    
    def set(self, session: Session):
        """将 Session 存入内存"""
        self.sessions[session.id] = session
    
    def remove(self, session_id: str):
        """从内存移除 Session"""
        if session_id in self.sessions:
            del self.sessions[session_id]
```

## API 设计

### RESTful API 端点

- `GET /api/sessions`: 获取 Session 列表
- `POST /api/sessions`: 创建新 Session
- `GET /api/sessions/{id}`: 获取指定 Session
- `PUT /api/sessions/{id}`: 更新 Session
- `DELETE /api/sessions/{id}`: 删除 Session
- `POST /api/sessions/{id}/archive`: 归档 Session
- `GET /api/sessions/{id}/export`: 导出 Session 数据
- `POST /api/sessions/import`: 导入 Session 数据

### 请求/响应示例

**创建 Session**:
```json
POST /api/sessions

Request:
{
  "title": "Python 编程讨论",
  "metadata": {
    "model": "gpt-4",
    "temperature": 0.7
  }
}

Response:
{
  "id": "session-123",
  "title": "Python 编程讨论",
  "status": "active",
  "messages": [],
  "metadata": {
    "model": "gpt-4",
    "temperature": 0.7
  },
  "created_at": "2024-01-01T00:00:00Z",
  "updated_at": "2024-01-01T00:00:00Z"
}
```

**获取 Session 列表**:
```json
GET /api/sessions?status=active&limit=20&offset=0

Response:
{
  "sessions": [
    {
      "id": "session-123",
      "title": "Python 编程讨论",
      "status": "active",
      "last_message_at": "2024-01-01T00:05:00Z",
      "message_count": 10
    }
  ],
  "total": 50,
  "limit": 20,
  "offset": 0
}
```

## 前端集成

### Vue 3 组件示例

```vue
<template>
  <div class="session-list">
    <div 
      v-for="session in sessions" 
      :key="session.id"
      @click="selectSession(session.id)"
      :class="{ active: currentSessionId === session.id }"
    >
      <h3>{{ session.title }}</h3>
      <p>{{ formatDate(session.updated_at) }}</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useSessionStore } from '@/stores/session'

const sessionStore = useSessionStore()
const sessions = ref([])
const currentSessionId = ref('')

onMounted(async () => {
  sessions.value = await sessionStore.fetchSessions()
})

const selectSession = (sessionId: string) => {
  currentSessionId.value = sessionId
  sessionStore.setCurrentSession(sessionId)
}
</script>
```

## 最佳实践

1. **定期清理**: 定期清理已删除的 Session，释放存储空间
2. **分页加载**: 对于大量 Session，使用分页加载
3. **缓存策略**: 使用缓存减少数据库查询
4. **标题生成**: 在用户发送第一条消息后自动生成标题
5. **状态同步**: 确保前端和后端的 Session 状态同步

## 参考资源

- [FastAPI 数据库操作](https://fastapi.tiangolo.com/tutorial/sql-databases/)
- [SQLAlchemy 文档](https://docs.sqlalchemy.org/)
