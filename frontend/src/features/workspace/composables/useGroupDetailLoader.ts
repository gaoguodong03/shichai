import type { Ref } from 'vue'
import type { GroupStreamRuntime } from './useGroupStreamRuntime'

export type GroupDetail = {
  id: string
  title: string
  messages: { message_id?: string; role: string; agent_name?: string; content: string }[]
  agent_map: Record<string, { name?: string; description?: string }>
  agent_names: string[]
  leader_agent_name?: string
  host_config?: { leader_agent_name?: string; llm_name?: string; system_prompt?: string; skill_name?: string; skill_directory?: string }
  runtime_state?: { running?: boolean; agent_name?: string; skill?: string; phase?: string; started_at?: string }
  /** recruitment：可推荐邀请；scene：名单固定，不展示招募条 */
  orchestration_profile?: string
}

function normalizeGroupDetail(raw: Record<string, unknown>, fallbackId: string): GroupDetail {
  const id = String(raw.id ?? fallbackId)
  const messages = Array.isArray(raw.messages) ? raw.messages as GroupDetail['messages'] : []
  const agent_map = (raw.agent_map && typeof raw.agent_map === 'object') ? (raw.agent_map as GroupDetail['agent_map']) : {}
  const agent_names = Array.isArray(raw.agent_names) ? (raw.agent_names as string[]) : []
  const host_config = (raw.host_config && typeof raw.host_config === 'object')
    ? (raw.host_config as GroupDetail['host_config'])
    : undefined
  const orch = String(raw.orchestration_profile ?? '').trim().toLowerCase()
  const runtime_state = (raw.runtime_state && typeof raw.runtime_state === 'object')
    ? (raw.runtime_state as GroupDetail['runtime_state'])
    : undefined
  return {
    id,
    title: String(raw.title ?? '群聊'),
    messages,
    agent_map,
    agent_names,
    leader_agent_name: String(raw.leader_agent_name ?? ''),
    host_config,
    runtime_state,
    orchestration_profile: orch === 'scene' || orch === 'recruitment' ? orch : undefined,
  }
}

export function parseGroupResponse(id: string, body: unknown): GroupDetail | null {
  if (body == null) return null
  if (Array.isArray(body)) {
    return normalizeGroupDetail({ id, title: '群聊', messages: body, agent_names: [], agent_map: {} }, id)
  }
  if (typeof body !== 'object') return null
  const o = body as Record<string, unknown>
  if (o.status === 'ok' && o.data != null && typeof o.data === 'object') {
    return normalizeGroupDetail(o.data as Record<string, unknown>, id)
  }
  if (o.id != null && (Array.isArray(o.messages) || o.messages === undefined)) {
    return normalizeGroupDetail(o, id)
  }
  return null
}

export function hydrateRuntimeStateFromServer(args: {
  detail: GroupDetail
  groupStreamStates: Ref<Record<string, GroupStreamRuntime>>
  patchGroupStreamState: (sessionId: string, patch: Partial<GroupStreamRuntime>) => void
  clearRestoredRuntimePollTimer: () => void
  scheduleRestoredRuntimePoll: (sessionId: string) => void
  setLastRoute: (route: { sessionId: string; expertName: string; skill: string }) => void
}) {
  const {
    detail,
    groupStreamStates,
    patchGroupStreamState,
    clearRestoredRuntimePollTimer,
    scheduleRestoredRuntimePoll,
    setLastRoute,
  } = args
  const rt = detail.runtime_state
  const st = groupStreamStates.value[detail.id]
  if (!rt?.running) {
    clearRestoredRuntimePollTimer()
    if (st?.restored) {
      patchGroupStreamState(detail.id, { streaming: false, phase: '', abort: null, agentName: '', skill: '', restored: false })
    }
    return
  }
  const phase = String(rt.phase || '').trim()
  const agentName = String(rt.agent_name || '').trim()
  const skill = String(rt.skill || '').trim()
  const hasLocalAbort = Boolean(st?.streaming && st.abort)
  patchGroupStreamState(detail.id, {
    streaming: true,
    phase: phase === 'tool_running' ? '技能任务运行中，完成后会继续回复…' : '仍在等待技能任务完成…',
    abort: hasLocalAbort ? st?.abort || null : null,
    runToken: Number(groupStreamStates.value[detail.id]?.runToken || 0),
    agentName,
    skill,
    restored: !hasLocalAbort,
  })
  if (agentName || skill) {
    setLastRoute({ sessionId: detail.id, expertName: agentName, skill })
  }
  if (!hasLocalAbort) scheduleRestoredRuntimePoll(detail.id)
}
