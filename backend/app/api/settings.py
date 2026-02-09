"""设置 API - MCP 和 Skills 配置"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import uuid
import yaml
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
router = APIRouter(tags=["settings"])

# 使用 mcp.manager 的全局单例，与 chat 共用
def get_mcp_manager():
    """获取 MCP Manager 实例（与 chat 共用同一实例）"""
    from app.mcp.manager import get_mcp_manager as _get_mcp
    return _get_mcp()

# 配置文件路径
MCP_CONFIG_PATH = os.getenv("MCP_CONFIG_PATH", "./config/mcp_servers.json")
SKILLS_DIR = os.getenv("SKILLS_DIR", "./skills")
APP_SETTINGS_PATH = os.getenv("APP_SETTINGS_PATH", "./config/app_settings.json")

# ========== 应用设置 API（LLM 选择、系统提示词） ==========

class AppSettingsBody(BaseModel):
    """应用设置请求体"""
    default_llm: Optional[str] = None  # 当前仅支持 qwen
    system_prompt: Optional[str] = None  # 每次 chat 前注入到大模型 prompt 的系统提示词

def load_app_settings() -> Dict[str, Any]:
    """加载应用设置"""
    path = Path(APP_SETTINGS_PATH)
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"default_llm": "qwen", "system_prompt": ""}

def save_app_settings(data: Dict[str, Any]):
    """保存应用设置"""
    path = Path(APP_SETTINGS_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    current = load_app_settings()
    current.update({k: v for k, v in data.items() if v is not None})
    with open(path, "w", encoding="utf-8") as f:
        json.dump(current, f, ensure_ascii=False, indent=2)

@router.get("/settings/app")
async def get_app_settings():
    """获取应用设置（LLM 选择、系统提示词）"""
    data = load_app_settings()
    return {"status": "ok", "data": data}

@router.put("/settings/app")
async def update_app_settings(body: AppSettingsBody):
    """更新应用设置"""
    save_app_settings(body.model_dump(exclude_none=True))
    return {"status": "ok", "data": load_app_settings()}

# ========== MCP 配置 API ==========

class MCPTransport(BaseModel):
    """MCP 传输配置"""
    type: str  # stdio, sse, http
    command: Optional[str] = None
    args: Optional[List[str]] = None
    url: Optional[str] = None
    base_url: Optional[str] = None
    headers: Optional[Dict[str, str]] = None
    env: Optional[Dict[str, str]] = None

class MCPServerCreate(BaseModel):
    """创建 MCP Server 请求"""
    name: str
    enabled: bool = True
    transport: MCPTransport
    metadata: Optional[Dict[str, Any]] = None

class MCPServerUpdate(BaseModel):
    """更新 MCP Server 请求"""
    name: Optional[str] = None
    enabled: Optional[bool] = None
    transport: Optional[MCPTransport] = None
    metadata: Optional[Dict[str, Any]] = None

def load_mcp_config() -> List[Dict[str, Any]]:
    """加载 MCP 配置"""
    config_path = Path(MCP_CONFIG_PATH)
    if config_path.exists():
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []

def save_mcp_config(servers: List[Dict[str, Any]]):
    """保存 MCP 配置"""
    config_path = Path(MCP_CONFIG_PATH)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(servers, f, ensure_ascii=False, indent=2)

@router.get("/settings/mcp")
async def get_mcp_servers():
    """获取 MCP Server 列表"""
    servers = load_mcp_config()
    mcp_manager = get_mcp_manager()
    
    # 确保 MCP Manager 已加载配置和初始化
    try:
        await mcp_manager.load_config()
        # 对每个已启用且尚未连接的 server 尝试连接（包括 HTTP 远程 server）
        for config in mcp_manager.server_configs:
            server_id = config.get("id", "")
            if not config.get("enabled", True):
                continue
            if server_id in mcp_manager.sessions:
                continue
            try:
                await mcp_manager.connect_server(server_id, config)
            except asyncio.CancelledError:
                # 请求被取消（如前端断开、超时），不再继续连接，直接返回当前状态
                break
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(f"MCP Server {server_id} 连接失败: {e}")
    except asyncio.CancelledError:
        pass  # 被取消时不再抛错，下面会按当前 sessions 返回列表
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"MCP 配置加载失败: {e}")
    
    # 统计每个 server 的工具数量
    server_tool_counts = {}
    for tool_name, tool in mcp_manager.tools.items():
        # 工具名称格式: server_id_tool_name
        if '_' in tool_name:
            server_id = tool_name.split('_', 1)[0]
            server_tool_counts[server_id] = server_tool_counts.get(server_id, 0) + 1
    
    # 检查连接状态
    server_status = {}
    for server_id in mcp_manager.sessions.keys():
        server_status[server_id] = "connected"
    
    # 添加状态信息
    result = []
    for server in servers:
        server_id = server.get("id", "")
        tool_count = server_tool_counts.get(server_id, 0)
        status = server_status.get(server_id, "disconnected")
        
        # 如果启用了但未连接，可能是连接失败
        if server.get("enabled", False) and status == "disconnected":
            status = "disconnected"
        
        server_info = {
            "id": server_id,
            "name": server.get("name", ""),
            "enabled": server.get("enabled", False),
            "tool_count": tool_count,
            "status": status,
            "transport": server.get("transport", {}),
            "metadata": server.get("metadata", {})
        }
        result.append(server_info)
    
    return {
        "status": "ok",
        "data": {
            "servers": result
        }
    }

@router.post("/settings/mcp")
async def create_mcp_server(server: MCPServerCreate):
    """创建 MCP Server"""
    servers = load_mcp_config()
    
    # 生成 ID
    server_id = f"mcp-{uuid.uuid4().hex[:8]}"
    
    new_server = {
        "id": server_id,
        "name": server.name,
        "enabled": server.enabled,
        "transport": server.transport.dict(exclude_none=True),
        "metadata": server.metadata or {}
    }
    
    servers.append(new_server)
    save_mcp_config(servers)
    
    return {
        "status": "ok",
        "data": new_server
    }

@router.put("/settings/mcp/{server_id}")
async def update_mcp_server(server_id: str, server_update: MCPServerUpdate):
    """更新 MCP Server"""
    servers = load_mcp_config()
    
    # 查找服务器
    server_index = None
    for i, s in enumerate(servers):
        if s.get("id") == server_id:
            server_index = i
            break
    
    if server_index is None:
        raise HTTPException(status_code=404, detail="MCP Server not found")
    
    # 更新字段
    server = servers[server_index]
    if server_update.name is not None:
        server["name"] = server_update.name
    if server_update.enabled is not None:
        server["enabled"] = server_update.enabled
    if server_update.transport is not None:
        server["transport"] = server_update.transport.dict(exclude_none=True)
    if server_update.metadata is not None:
        server["metadata"] = server_update.metadata
    
    save_mcp_config(servers)
    
    return {
        "status": "ok",
        "data": server
    }

@router.delete("/settings/mcp/{server_id}")
async def delete_mcp_server(server_id: str):
    """删除 MCP Server"""
    servers = load_mcp_config()
    
    # 查找并删除
    original_count = len(servers)
    servers = [s for s in servers if s.get("id") != server_id]
    
    if len(servers) == original_count:
        raise HTTPException(status_code=404, detail="MCP Server not found")
    
    save_mcp_config(servers)
    
    return {
        "status": "ok",
        "data": {
            "id": server_id,
            "deleted": True
        }
    }

@router.post("/settings/mcp/{server_id}/enable")
async def enable_mcp_server(server_id: str):
    """启用 MCP Server"""
    servers = load_mcp_config()
    
    for server in servers:
        if server.get("id") == server_id:
            server["enabled"] = True
            save_mcp_config(servers)
            return {
                "status": "ok",
                "data": server
            }
    
    raise HTTPException(status_code=404, detail="MCP Server not found")

@router.post("/settings/mcp/{server_id}/disable")
async def disable_mcp_server(server_id: str):
    """禁用 MCP Server"""
    servers = load_mcp_config()
    
    for server in servers:
        if server.get("id") == server_id:
            server["enabled"] = False
            save_mcp_config(servers)
            return {
                "status": "ok",
                "data": server
            }
    
    raise HTTPException(status_code=404, detail="MCP Server not found")

@router.post("/settings/mcp/{server_id}/test")
async def test_mcp_server(server_id: str):
    """测试 MCP Server 连接"""
    servers = load_mcp_config()
    
    # 查找服务器
    server = None
    for s in servers:
        if s.get("id") == server_id:
            server = s
            break
    
    if server is None:
        raise HTTPException(status_code=404, detail="MCP Server not found")
    
    # 简化版本：只返回成功，实际应该测试连接
    # TODO: 实际实现连接测试逻辑
    return {
        "status": "ok",
        "data": {
            "connected": True,
            "response_time": 100,
            "error": None
        }
    }

@router.get("/settings/mcp/{server_id}/tools")
async def get_mcp_server_tools(server_id: str):
    """获取 MCP Server 工具列表"""
    # TODO: 实际应该从 MCP Manager 获取工具列表
    return {
        "status": "ok",
        "data": {
            "tools": []
        }
    }

# ========== Skills 配置 API ==========

class SkillCreate(BaseModel):
    """创建 Skill 请求"""
    name: str
    description: Optional[str] = None
    source: str  # local or remote
    path: Optional[str] = None
    url: Optional[str] = None
    enabled: bool = True

class SkillUpdate(BaseModel):
    """更新 Skill 请求"""
    name: Optional[str] = None
    description: Optional[str] = None
    source: Optional[str] = None
    path: Optional[str] = None
    url: Optional[str] = None
    enabled: Optional[bool] = None

def load_skills_config() -> List[Dict[str, Any]]:
    """加载 Skills 配置"""
    # 从 skills 目录读取
    skills_dir = Path(SKILLS_DIR)
    if not skills_dir.exists():
        return []
    
    skills = []
    for skill_dir in skills_dir.iterdir():
        if skill_dir.is_dir():
            skill_file = skill_dir / "SKILL.md"
            if skill_file.exists():
                # 读取 SKILL.md 的 frontmatter
                content = skill_file.read_text(encoding='utf-8')
                if content.startswith('---'):
                    # 解析 frontmatter
                    parts = content.split('---', 2)
                    if len(parts) >= 3:
                        try:
                            frontmatter = yaml.safe_load(parts[1])
                            skill_id = skill_dir.name
                            skills.append({
                                "id": skill_id,
                                "name": frontmatter.get("name", skill_id),
                                "description": frontmatter.get("description", ""),
                                "enabled": frontmatter.get("enabled", True),
                                "source": "local",
                                "path": str(skill_dir)
                            })
                        except:
                            pass
    
    return skills

@router.get("/settings/skills")
async def get_skills():
    """获取 Skills 列表"""
    skills = load_skills_config()
    
    return {
        "status": "ok",
        "data": {
            "skills": skills
        }
    }

def _slugify(name: str) -> str:
    """生成可作目录名的 slug"""
    s = re.sub(r"[^\w\s-]", "", name)
    s = re.sub(r"[-\s]+", "-", s).strip("-").lower()
    return s or "skill"


@router.post("/settings/skills")
async def create_skill(skill: SkillCreate):
    """创建 Skill：在 skills 目录下创建 <id>/SKILL.md"""
    base = Path(SKILLS_DIR)
    base.mkdir(parents=True, exist_ok=True)
    raw_id = _slugify(skill.name)
    skill_id = raw_id
    idx = 0
    while (base / skill_id).exists():
        idx += 1
        skill_id = f"{raw_id}-{idx}"
    skill_dir = base / skill_id
    skill_dir.mkdir(parents=True, exist_ok=True)
    body = "\n## 说明\n\n（待补充）\n"
    frontmatter = {
        "name": skill.name,
        "description": skill.description or "",
        "enabled": skill.enabled,
    }
    content = "---\n" + yaml.dump(frontmatter, allow_unicode=True, default_flow_style=False) + "---\n" + body
    (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")
    new_skill = {
        "id": skill_id,
        "name": skill.name,
        "description": skill.description or "",
        "enabled": skill.enabled,
        "source": "local",
        "path": str(skill_dir),
        "url": skill.url,
    }
    return {"status": "ok", "data": new_skill}

def _read_skill_file(skill_dir: Path) -> tuple[Dict, str]:
    """读取 SKILL.md，返回 (frontmatter_dict, body)"""
    path = skill_dir / "SKILL.md"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Skill not found")
    text = path.read_text(encoding="utf-8")
    if not text.strip().startswith("---"):
        return ({}, text)
    parts = text.split("---", 2)
    if len(parts) < 3:
        return ({}, text)
    fm = yaml.safe_load(parts[1]) or {}
    return (fm, parts[2].lstrip("\n"))


def _write_skill_file(skill_dir: Path, frontmatter: Dict, body: str):
    """写入 SKILL.md"""
    content = "---\n" + yaml.dump(frontmatter, allow_unicode=True, default_flow_style=False) + "---\n" + body
    (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")


@router.put("/settings/skills/{skill_id}")
async def update_skill(skill_id: str, skill_update: SkillUpdate):
    """更新 Skill：修改 SKILL.md 的 frontmatter"""
    base = Path(SKILLS_DIR)
    skill_dir = base / skill_id
    if not skill_dir.is_dir():
        raise HTTPException(status_code=404, detail="Skill not found")
    fm, body = _read_skill_file(skill_dir)
    if skill_update.name is not None:
        fm["name"] = skill_update.name
    if skill_update.description is not None:
        fm["description"] = skill_update.description
    if skill_update.enabled is not None:
        fm["enabled"] = skill_update.enabled
    _write_skill_file(skill_dir, fm, body)
    return {"status": "ok", "data": {"id": skill_id, "updated": True}}

@router.delete("/settings/skills/{skill_id}")
async def delete_skill(skill_id: str):
    """删除 Skill：删除对应目录"""
    base = Path(SKILLS_DIR)
    skill_dir = base / skill_id
    if not skill_dir.is_dir():
        raise HTTPException(status_code=404, detail="Skill not found")
    shutil.rmtree(skill_dir)
    return {"status": "ok", "data": {"id": skill_id, "deleted": True}}

@router.post("/settings/skills/{skill_id}/enable")
async def enable_skill(skill_id: str):
    """启用 Skill"""
    base = Path(SKILLS_DIR)
    skill_dir = base / skill_id
    if not skill_dir.is_dir():
        raise HTTPException(status_code=404, detail="Skill not found")
    fm, body = _read_skill_file(skill_dir)
    fm["enabled"] = True
    _write_skill_file(skill_dir, fm, body)
    return {"status": "ok", "data": {"id": skill_id, "enabled": True}}

@router.post("/settings/skills/{skill_id}/disable")
async def disable_skill(skill_id: str):
    """禁用 Skill"""
    base = Path(SKILLS_DIR)
    skill_dir = base / skill_id
    if not skill_dir.is_dir():
        raise HTTPException(status_code=404, detail="Skill not found")
    fm, body = _read_skill_file(skill_dir)
    fm["enabled"] = False
    _write_skill_file(skill_dir, fm, body)
    return {"status": "ok", "data": {"id": skill_id, "enabled": False}}
