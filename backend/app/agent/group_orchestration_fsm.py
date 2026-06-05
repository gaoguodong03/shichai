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
    """用户侧表达：本段 Skill 可结束，下一轮应交四九调度（与专家正文中的 [[SKILL_SESSION_END]] 对应）。"""
    s = (user_message or "").strip()
    if len(s) < 4:
        return False
    return bool(_USER_SKILL_SESSION_EXIT_RE.search(s))


def user_message_is_pass_control(user_message: str) -> bool:
    """自由研讨里 pass 表示用户本轮不发言，仍应交由主持人推进阶段调度。"""
    return (user_message or "").strip().lower() == "pass"

ORCHESTRATION_RECRUITMENT = "recruitment"
ORCHESTRATION_SCENE = "scene"


def effective_orchestration_profile(meta_item: Dict[str, Any], *, agent_ids: List[str]) -> str:
    """
    返回 recruitment | scene。
    显式字段优先；缺省迁移：无成员视为招募房间，有成员视为场景（兼容旧会话）。
    """
    raw = str(meta_item.get("orchestration_profile") or "").strip().lower()
    if raw in (ORCHESTRATION_RECRUITMENT, ORCHESTRATION_SCENE):
        return raw
    return ORCHESTRATION_RECRUITMENT if not agent_ids else ORCHESTRATION_SCENE


def default_orchestration_profile_for_new_session(*, agent_ids: List[str]) -> str:
    """创建会话时写入 meta 的默认值。"""
    return ORCHESTRATION_SCENE if agent_ids else ORCHESTRATION_RECRUITMENT


def available_to_add_for_prompt(
    full_list: List[Dict[str, Any]],
    *,
    orchestration_profile: str,
) -> List[Dict[str, Any]]:
    """场景模式不向模型提供可邀请名单；新建会话（招募）提供完整列表。"""
    if orchestration_profile == ORCHESTRATION_SCENE:
        return []
    return list(full_list or [])


@dataclass(frozen=True)
class GroupEntryRoute:
    """单条用户消息进入流式编排时的入口判定。"""

    skip_host_dispatch: bool
    direct_expert_id: Optional[str]
    clear_skill_lock_before_host: bool


def resolve_group_entry_route(
    *,
    meta_item: Dict[str, Any],
    agent_ids: List[str],
    host_takeover_requested: bool,
    ignore_auto_expert_id: str,
    user_message: str = "",
) -> GroupEntryRoute:
    """
    是否跳过四九调度、直接由锁定专家处理本轮用户消息。
    （@ 点名由 group_chat 更前序分支处理，此处不再判断。）

    规则：存在 skill_session_owner_id 且仍在本场 agent_ids 内，且用户未要求主持人接管/
    未使用 ignore 排除该专家时，跳过主持人。
    """
    lock = str(meta_item.get("skill_session_owner_id") or "").strip().lower()
    if not lock or lock not in agent_ids:
        return GroupEntryRoute(
            skip_host_dispatch=False,
            direct_expert_id=None,
            clear_skill_lock_before_host=True,
        )

    if host_takeover_requested:
        return GroupEntryRoute(
            skip_host_dispatch=False,
            direct_expert_id=None,
            clear_skill_lock_before_host=True,
        )

    if user_message_is_pass_control(user_message):
        return GroupEntryRoute(
            skip_host_dispatch=False,
            direct_expert_id=None,
            clear_skill_lock_before_host=True,
        )

    if ignore_auto_expert_id and ignore_auto_expert_id == lock:
        return GroupEntryRoute(
            skip_host_dispatch=False,
            direct_expert_id=None,
            clear_skill_lock_before_host=True,
        )

    return GroupEntryRoute(
        skip_host_dispatch=True,
        direct_expert_id=lock,
        clear_skill_lock_before_host=False,
    )


def persist_skill_session_lock(
    meta_item: Dict[str, Any],
    *,
    owner_agent_id: str,
    skill_id: str,
) -> None:
    meta_item["skill_session_owner_id"] = str(owner_agent_id or "").strip().lower()
    meta_item["skill_session_skill_id"] = str(skill_id or "").strip()


def clear_skill_session_lock(meta_item: Dict[str, Any]) -> None:
    meta_item.pop("skill_session_owner_id", None)
    meta_item.pop("skill_session_skill_id", None)


def locked_skill_id_for_expert(
    meta_item: Dict[str, Any],
    *,
    expert_agent_id: str,
    expert_skill_ids: List[str],
) -> Optional[str]:
    """若本轮为 Skill 会话续跑（四九未调度），返回应继续使用的 skill_id。"""
    owner = str(meta_item.get("skill_session_owner_id") or "").strip().lower()
    sid = str(meta_item.get("skill_session_skill_id") or "").strip()
    eid = str(expert_agent_id or "").strip().lower()
    ids = {str(x).strip() for x in expert_skill_ids if str(x).strip()}
    if not owner or owner != eid or not sid:
        return None
    if sid in ids:
        return sid
    return None
