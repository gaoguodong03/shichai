"""
场景群聊：主持人/默认调度决策的后处理。

将「招募建议」与 next_speaker 的 product 规则集中在此，避免 group_chat.py 内多处复制且行为不一致。
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from app.agent.orchestrator_runtime import normalize_scheduler_decision
from app.core.recruitment_helpers import (
    extract_valid_agent_ids_from_text_or_names,
    prioritize_suggested_add_ids,
)

# 与 group_chat 气泡文案保持一致
RECRUIT_FIXED_MESSAGE = "当前成员无法完成该工作，建议先邀请更匹配的专家。"


def user_explicitly_requests_recruit(user_message: str) -> bool:
    """用户是否明确表达要加人/换人/再请专家（用于首轮抑制误招募）。"""
    um = (user_message or "").strip()
    if not um:
        return False
    return bool(
        re.search(
            r"(邀请|加人|补人|招人|再请|换一位|换专家|拉人|需要.{0,8}专家|再加|增员|另请)",
            um,
        )
    )


def _suppress_misleading_recruitment_when_room_configured(
    suggested_add: List[str],
    *,
    dha_list: List[Dict[str, Any]],
    agent_ids: List[str],
    user_message: str,
    explicit_requested_agent_ids: List[str],
) -> Tuple[List[str], bool]:
    """
    只要会话里已有协作配置或场内能解析出专家，就抑制模型误发的「邀请更多专家」，
    除非用户显式要加人或显式点名可招募专家。

    此前在「已有专家发言」后不再抑制（last_speaker 早退），会导致每轮 LLM 仍带 suggested_add，
    界面反复出现招募气泡。

    真实 0 成员（agent_ids 与 dha_list 皆空）时保留 suggested_add，便于组队。
    """
    if not suggested_add:
        return suggested_add, False
    if explicit_requested_agent_ids:
        return suggested_add, False
    if user_explicitly_requests_recruit(user_message):
        return suggested_add, False
    if not dha_list and not agent_ids:
        return suggested_add, False
    return [], True


def _recover_next_speaker_after_suppress(data: Dict[str, Any]) -> None:
    """清空误招募后：不猜测下一位专家，固定交还 user，由下一轮四九按流程图重新调度（步骤 6/2）。"""
    data["suggested_add_agent_ids"] = []
    data["suggested_add_expert_ids"] = []
    data["next_speaker"] = "user"
    data["task_done"] = True
    if not str(data.get("reason") or "").strip():
        data["reason"] = "误招募建议已忽略；等待用户继续输入，由下轮主持人调度。"


def finalize_host_scheduler_decision(
    raw: Optional[Dict[str, Any]],
    *,
    agent_ids: List[str],
    dha_list: List[Dict[str, Any]],
    available_to_add: List[Dict[str, Any]],
    last_speaker_agent_id: Optional[str],
    user_message: str,
    explicit_requested_agent_ids: List[str],
    orchestration_profile: str = "recruitment",
) -> Dict[str, Any]:
    """
    将主持人或 leader_decide 的原始 JSON 规范化为 orchestration 决策 dict。

    顺序：解析 suggested_add → 仅在场内无人时从 announcement 抠 id → 显式优先级 →
    非显式招募抑制 → 误招募清空时由 _recover 将 next_speaker 指回场内专家（若存在）→ normalize_scheduler_decision。

    orchestration_profile==scene 时强制不产生招募建议，且 next_speaker 仅能为场内专家或 user/end。
    """
    data = dict(raw or {})
    if orchestration_profile == "scene":
        data["suggested_add_agent_ids"] = []
        data["suggested_add_expert_ids"] = []
    announcement = data.get("announcement") if isinstance(data.get("announcement"), str) else None
    recruitable_ids = {d.get("agent_id") for d in available_to_add if d.get("agent_id")}
    raw_suggested = data.get("suggested_add_expert_ids") or data.get("suggested_add_agent_ids") or []
    suggested_add = list(dict.fromkeys([x for x in raw_suggested if x in recruitable_ids]))[:3]
    # 仅从主持词抠 id：仅「真实 0 成员」场景（meta 里也没有 agent_ids）。若 meta 有 id 但 dha_list 空，
    # 说明孤儿/失效 id，抠名字会误伤，交给 suppress 清掉 suggested_add。
    if not suggested_add and isinstance(announcement, str) and not dha_list and not agent_ids:
        suggested_add = extract_valid_agent_ids_from_text_or_names(
            announcement, recruitable_ids, available_to_add, max_n=3
        )
    suggested_add = prioritize_suggested_add_ids(
        suggested_add,
        explicit_requested_agent_ids=explicit_requested_agent_ids,
        recruitable_ids=recruitable_ids,
        max_n=3,
    )
    suggested_add, stripped = _suppress_misleading_recruitment_when_room_configured(
        suggested_add,
        dha_list=dha_list,
        agent_ids=agent_ids,
        user_message=user_message,
        explicit_requested_agent_ids=explicit_requested_agent_ids,
    )
    data["suggested_add_agent_ids"] = suggested_add
    data["suggested_add_expert_ids"] = suggested_add
    if stripped:
        _recover_next_speaker_after_suppress(data)

    rid_list = [str(d.get("agent_id") or "") for d in available_to_add if d.get("agent_id")]
    return normalize_scheduler_decision(
        data,
        agent_ids=agent_ids,
        recruitable_ids=rid_list,
        current_owner_agent_id=last_speaker_agent_id,
    )
