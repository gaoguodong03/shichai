from __future__ import annotations

from typing import Any, Dict, List

from app.agent.platform_prompts import render_platform_prompt


def build_expert_self_awareness_block(agent_profile: Dict[str, Any], skills_loader: Any) -> str:
    """构建专家“自我认知”提示块，列出绑定技能及描述。"""
    directories = [
        str(x.get("directory_name") if isinstance(x, dict) else "").strip()
        for x in (agent_profile.get("skills") or [])
    ]
    directories = [x for x in directories if x]
    if not directories:
        return ""

    lines: List[str] = []
    skills = getattr(skills_loader, "skills", {}) if skills_loader is not None else {}
    for sid in directories:
        sk = skills.get(sid) if isinstance(skills, dict) else None
        if sk and sk.metadata.get("enabled", True):
            name = (sk.name or sid).strip()
            desc = (sk.description or "").strip()
            if desc:
                lines.append(f"- **{name}**（标识：`{sid}`）\n  {desc}")
            else:
                lines.append(
                    f"- **{name}**（标识：`{sid}`）\n"
                    "  无描述，仅按技能名称推断能力边界。"
                )
        elif sk and not sk.metadata.get("enabled", True):
            lines.append(f"- （已禁用，不在此列举：`{sid}`）")
        else:
            lines.append(f"- （配置中已绑定但未在技能库加载：`{sid}`）")

    if not lines:
        return ""

    return render_platform_prompt("expert.self_awareness.v1", {"skill_lines": "\n\n".join(lines)})
