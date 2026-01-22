"""Agent 类型定义"""
from enum import Enum
from typing import Optional, Dict, Any
from pydantic import BaseModel
from datetime import datetime

class ReActStepType(str, Enum):
    """ReAct 步骤类型"""
    THOUGHT = "thought"
    TOOL_CALL = "tool_call"
    OBSERVATION = "observation"
    FINAL_ANSWER = "final_answer"

class ToolCallInfo(BaseModel):
    """工具调用信息"""
    tool_name: str
    arguments: Dict[str, Any]
    result: Optional[Any] = None
    error: Optional[str] = None

class ReActStep(BaseModel):
    """ReAct 工作流步骤"""
    type: ReActStepType
    content: str
    tool_call: Optional[ToolCallInfo] = None
    timestamp: datetime = None
    
    def __init__(self, **data):
        if 'timestamp' not in data:
            data['timestamp'] = datetime.now()
        super().__init__(**data)

class StreamEvent(BaseModel):
    """流式事件"""
    event_type: str  # "react_step" 或 "content"
    data: Dict[str, Any]
