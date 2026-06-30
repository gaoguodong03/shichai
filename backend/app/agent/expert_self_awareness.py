from __future__ import annotations

from typing import Any, Dict, List


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

    return (
        "## 你当前绑定的 Skill\n"
        "若用户询问你有哪些 skill、能力或工具包，必须依据下列清单回答，不要编造清单外的名称；"
        "本轮实际执行时仍以上文完整技能说明为准。\n\n"
        + "\n\n".join(lines)
    )
