"""Skill flow-control instruction shared by expert runtimes.

This module carries only the current `skill_result.next_action` instruction
surface. Cross-turn state is derived in `group_chat_skill_session.py` from
strict script stdout JSON or the documented hidden state block.
"""
from __future__ import annotations

from typing import Literal, TypedDict


class SkillNextActionDict(TypedDict):
    agent_turn: Literal["respond", "continue"]
    skill_session: Literal["keep", "release"]


DEFAULT_SKILL_NEXT_ACTION: SkillNextActionDict = {
    "agent_turn": "respond",
    "skill_session": "release",
}


GROUP_EXPERT_SKILL_SESSION_STATE_INSTRUCTION = """

## Skill 会话状态
场景协作中，普通专家本轮发言完成后默认交回主持人调度。

脚本型 Skill 必须在 stdout JSON 中输出固定字段：
`execution_status`、`content`、`artifacts`、`next_action`。
非脚本 Skill、MCP / HTTP / workspace 工具后的流程判断，必须在专家最终回复末尾追加隐藏状态块。
隐藏状态块必须直接追加到正文末尾，平台会读取并从用户可见正文中移除：
[[SKILL_SESSION_STATE]]
{
  "execution_status": "succeeded",
  "content": "处理完成。",
  "artifacts": [],
  "next_action": {
    "agent_turn": "respond",
    "skill_session": "release"
  }
}
[[/SKILL_SESSION_STATE]]
`next_action.agent_turn` 只允许 `respond` 或 `continue`：
`respond` 表示本轮回复用户，`continue` 表示当前专家本轮继续行动。
`next_action.skill_session` 只允许 `keep` 或 `release`：
`keep` 表示下一条用户消息继续回到同一专家和同一 Skill，`release` 表示释放。
"""
