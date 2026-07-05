"""双轨群聊编排：显式 profile、入口路由与 Skill 会话锁（跨请求）。"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

# 用户明确表示「当前 Skill 段落结束、交回主持人」时的常见说法（避免过短句误触）
_USER_SKILL_SESSION_EXIT_RE = re.compile(
    "|".join(
        [
            r"你的任务完成(了|啦)?",
            r"任务(已经|已)?完成(了|啦)?",
            r"任务结束",
            r"不用继续(了)?",
            r"不用做了",
            r"到此为止",
            r"(交|还给).{0,8}主持人",
            r"请.{0,6}主持人",
            r"(换|叫|请).{0,6}(别的|其他|下一位)?.{0,4}专家",
            r"下一个专家",
            r"下个专家",
            r"(退出|结束).{0,8}(skill|技能)",
        ]
    ),
    re.IGNORECASE,
)


def user_requests_exit_skill_session(user_message: str) -> bool:
    """用户侧表达：本段 Skill 可结束，下一轮应交四九调度。"""
    s = (user_message or "").strip()
    if len(s) < 4:
        return False
    return bool(_USER_SKILL_SESSION_EXIT_RE.search(s))


ORCHESTRATION_RECRUITMENT = "recruitment"
ORCHESTRATION_SCENE = "scene"


def effective_orchestration_profile(session_item: Dict[str, Any], *, agent_names: List[str]) -> str:
    """
    返回 recruitment | scene。
    显式字段优先；缺省：无成员视为招募房间，有成员视为场景。
    """
    raw = str(session_item.get("orchestration_profile") or "").strip().lower()
    if raw in (ORCHESTRATION_RECRUITMENT, ORCHESTRATION_SCENE):
        return raw
    return ORCHESTRATION_RECRUITMENT if not agent_names else ORCHESTRATION_SCENE


def default_orchestration_profile_for_new_session(*, agent_names: List[str]) -> str:
    """新建会话时写入会话定义的默认值。"""
    return ORCHESTRATION_SCENE if agent_names else ORCHESTRATION_RECRUITMENT


def available_to_add_for_prompt(
    full_list: List[Dict[str, Any]],
    *,
    orchestration_profile: str,
    agent_names: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """仅真实空会话向模型提供可邀请名单。"""
    if orchestration_profile == ORCHESTRATION_SCENE:
        return []
    if agent_names:
        return []
    return list(full_list or [])


@dataclass(frozen=True)
class GroupEntryRoute:
    """单条用户消息进入流式编排时的入口判定。"""

    skip_host_dispatch: bool
    direct_agent_name: Optional[str]
    clear_skill_lock_before_host: bool


def resolve_group_entry_route(
    *,
    session_item: Dict[str, Any],
    agent_names: List[str],
    user_message: str = "",
) -> GroupEntryRoute:
    """
    是否跳过四九调度、直接由锁定专家处理本轮用户消息。
    （@ 点名由 group_chat 更前序分支处理，此处不再判断。）

    规则：存在 skill_session_owner_name 且仍在本场 agent_names 内时，跳过主持人。
    用户要求主持人接管、点名其他专家或结束当前 Skill 的情况在 group_chat_runtime 更前序清锁。
    """
    lock = str(session_item.get("skill_session_owner_name") or "").strip()
    agent_name_keys = {str(x or "").strip().casefold() for x in agent_names or [] if str(x or "").strip()}
    lock_key = lock.casefold()
    if not lock or lock_key not in agent_name_keys:
        return GroupEntryRoute(
            skip_host_dispatch=False,
            direct_agent_name=None,
            clear_skill_lock_before_host=True,
        )

    return GroupEntryRoute(
        skip_host_dispatch=True,
        direct_agent_name=lock,
        clear_skill_lock_before_host=False,
    )


def persist_skill_session_lock(
    session_item: Dict[str, Any],
    *,
    owner_agent_name: str,
    skill: str,
) -> None:
    session_item["skill_session_owner_name"] = str(owner_agent_name or "").strip()
    session_item["skill_session_skill"] = str(skill or "").strip()


def clear_skill_session_lock(session_item: Dict[str, Any]) -> None:
    session_item.pop("skill_session_owner_name", None)
    session_item.pop("skill_session_skill", None)


def locked_skill_for_expert(
    session_item: Dict[str, Any],
    *,
    expert_agent_name: str,
    expert_skills: List[str],
) -> Optional[str]:
    """若本轮为 Skill 会话续跑（四九未调度），返回应继续使用的 Skill 目录名。"""
    owner = str(session_item.get("skill_session_owner_name") or "").strip().casefold()
    skill = str(session_item.get("skill_session_skill") or "").strip()
    expert = str(expert_agent_name or "").strip().casefold()
    skills = {str(x).strip() for x in expert_skills if str(x).strip()}
    if not owner or owner != expert or not skill:
        return None
    if skill in skills:
        return skill
    return None
