"""只读读取 Skill 目录下 references/assets/others 等附加文件的工具。

不经过沙箱路径，从宿主直读。路径限定在当前登录用户的技能目录以内，
避免目录穿越攻击。
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from app.agent.path_whitelist_guard import ensure_within_root, normalize_rel_path
from app.agent.tool_spec import ToolSpec
from app.skills.loader import get_builtin_skills_dir
from app.core.user_context import get_current_user_context

logger = logging.getLogger(__name__)


class ReadSkillFileInput(BaseModel):
    path: str = Field(description="Skill 附加文件的相对路径，例如 references/hello.md")


def _resolve_skill_dir(directory_name: str) -> Optional[Path]:
    """返回指定 directory_name 对应的技能目录路径，或 None。

    先查当前用户的 skills 目录，再查 builtin 技能目录。
    保证返回的路径无法穿越到父目录之外。
    """
    safe = (directory_name or "").strip()
    if not safe or ".." in safe or "/" in safe or "\\" in safe:
        return None

    # 当前用户技能目录
    try:
        user_ctx = get_current_user_context(default_fallback=False)
        if user_ctx is not None:
            skills_dir = user_ctx.skills_dir.resolve()
            candidate = (skills_dir / safe).resolve()
            if candidate.is_dir() and str(candidate).startswith(str(skills_dir)) and (candidate / "SKILL.md").is_file():
                return candidate
    except Exception:
        pass

    # 内置技能目录
    try:
        builtin_dir = get_builtin_skills_dir().resolve()
        if builtin_dir.is_dir():
            candidate = (builtin_dir / safe).resolve()
            if candidate.is_dir() and str(candidate).startswith(str(builtin_dir)) and (candidate / "SKILL.md").is_file():
                return candidate
    except Exception:
        pass

    return None


def create_read_skill_file_tool(directory_name: str) -> ToolSpec:
    """新建只读 Skill 文件读取工具。

    该工具读取由 directory_name 标识的技能目录下的附加文件
    （references/、assets/ 等），不做沙箱挂载，宿主直读。
    路径被严格限制在该技能目录内。
    """

    async def _read_skill_file(path: str = "") -> str:
        raw = (path or "").strip()
        if not raw:
            return "错误：path 参数不能为空。请指定 Skill 附加文件的相对路径，例如 references/hello.md"

        # 总是用调用时刻的目录名解析，确保路径最新
        skill_dir = _resolve_skill_dir(directory_name)
        if skill_dir is None:
            return f"错误：无法找到 Skill 目录「{directory_name}」。技能可能已被删除或路径异常。"

        # 标准化用户传入的相对路径
        rel = normalize_rel_path(raw)
        if not rel:
            return "错误：path 不能指向 Skill 根目录。请指定文件路径。"

        # 路径穿越防护
        try:
            target = ensure_within_root(skill_dir / rel, skill_dir)
        except ValueError:
            return f"错误：路径超出 Skill 目录范围。不允许向上穿越。"

        if not target.exists():
            return f"错误：文件不存在：{rel}"
        if target.is_dir():
            return f"错误：{rel} 是目录，无法读取。"
        if target.name == "SKILL.md":
            return "错误：SKILL.md 已在技能指令中加载，无需手动读取。"
        if target.parent.name == "scripts":
            return "错误：scripts/ 下的文件需要通过 run_skill_script 工具执行，不可直接读取。"

        try:
            text = target.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return f"错误：{rel} 不是 UTF-8 编码的文本文件，无法读取。"
        except Exception as e:
            logger.warning("read_skill_file_failed path=%s err=%s", rel, e)
            return f"错误：读取文件失败：{e}"

        return text

    tool = ToolSpec.from_function(
        name=f"read_skill_file",
        description=f"读取 Skill「{directory_name}」的附加文件（references/、assets/ 等）。传入文件相对路径，例如 references/hello.md。SKILL.md 和 scripts/ 下的文件不可用此工具读取。",
        coroutine=_read_skill_file,
        args_schema=ReadSkillFileInput,
    )
    tool.metadata = {"source": "skill_file"}
    return tool
