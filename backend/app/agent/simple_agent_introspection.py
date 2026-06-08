from __future__ import annotations

import re

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

_WRAPPED_USER_CONTEXT_MARKERS = (
    "【最近讨论】",
    "【历史对话（供参考）】",
    "【最近几轮讨论内容",
    "【关键事实】",
    "memory/facts.md",
    "facts.md",
)


def _extract_text_content(message: BaseMessage) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    return str(content or "")


def _last_user_text(messages: list[BaseMessage]) -> str:
    for msg in reversed(messages or []):
        if isinstance(msg, HumanMessage):
            return _extract_text_content(msg).strip()
    return ""


def _section_text(text: str, heading: str) -> str:
    raw = text or ""
    start = raw.find(heading)
    if start < 0:
        return ""
    body = raw[start + len(heading) :]
    body = body.lstrip("\n\r\t ")
    next_heading = re.search(r"\n【[^】]+】", body)
    if next_heading:
        body = body[: next_heading.start()]
    return body.strip()


def _user_text_for_bound_skill_introspection(messages: list[BaseMessage]) -> str:
    """Use only the current user request for self-awareness routing, never reference/history blocks."""
    text = _last_user_text(messages)
    if not text:
        return ""
    current = _section_text(text, "【本轮用户输入】")
    if current:
        return "" if current in {"（无）", "(无)"} else current
    if any(marker in text for marker in _WRAPPED_USER_CONTEXT_MARKERS):
        return ""
    return text


def _is_bound_skill_introspection_request(text: str) -> bool:
    raw = (text or "").strip().lower()
    s = raw.replace(" ", "")
    if not s:
        return False
    explicit_skill_terms = ("skill", "技能", "工具包", "tool")
    explicit_scope_terms = ("哪些", "有什么", "有啥", "几个", "一共", "列出", "介绍")
    owner_terms = ("你", "当前", "绑定", "拥有", "会什么", "能做什么")
    if (
        any(term in s for term in explicit_skill_terms)
        and any(term in s for term in explicit_scope_terms)
        and any(term in s for term in owner_terms)
    ):
        return True
    if re.search(r"(你|当前).{0,12}(绑定|拥有).{0,12}(skill|技能|工具包|tool)", s):
        return True
    if re.search(r"你.{0,8}(有哪些|有什么|有啥).{0,4}能力", s):
        return True
    if re.search(r"你.{0,8}(会什么|能做什么)", s):
        return True
    if re.search(r"(what|which|list).{0,30}(your|you).{0,30}(skills?|tools?)", raw):
        return True
    if re.search(r"(what|which).{0,30}(skills?|tools?).{0,30}(do you have|can you use)", raw):
        return True
    return False


def _bound_skill_introspection_message(system_prompt: str, user_text: str) -> AIMessage | None:
    if not _is_bound_skill_introspection_request(user_text):
        return None
    prompt = system_prompt or ""
    marker = "## 你当前绑定的 Skill"
    start = prompt.find(marker)
    if start < 0:
        return None
    rest = prompt[start + len(marker) :].strip()
    if not rest:
        return None
    section_end = len(rest)
    for pattern in (
        r"\n##\s+",
        r"\n你可以使用以下工具：",
        r"\n当你需要使用工具时",
        r"\n当你不需要使用工具时",
    ):
        match = re.search(pattern, rest)
        if match:
            section_end = min(section_end, match.start())
    rest = rest[:section_end].strip()
    lines = [line.rstrip() for line in rest.splitlines()]
    while lines and not lines[0].lstrip().startswith("- "):
        lines.pop(0)
    body = "\n".join(lines).strip()
    if not body:
        return None
    return AIMessage(content=f"我当前绑定的 Skill 有：\n\n{body}")
