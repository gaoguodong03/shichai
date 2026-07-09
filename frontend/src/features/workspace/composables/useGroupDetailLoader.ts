import type { Ref } from 'vue'
import type { GroupStreamRuntime } from './useGroupStreamRuntime'
import type { GroupMessage } from './useGroupMessageList'

export type GroupDetail = {
  id: string
  title: string
  messages: GroupMessage[]
  agent_map: Record<string, { name?: string; description?: string }>
  agent_names: string[]
  host?: { name?: string; llm_name?: string; system_prompt?: string; skill_name?: string; skill_directory?: string }
  runtime?: { running?: boolean; agent_name?: string; skill?: string; phase?: string; started_at?: string }
}

function normalizeGroupDetail(raw: Record<string, unknown>, fallbackId: string): GroupDetail {
  const id = String(raw.id ?? fallbackId)
  const messages = Array.isArray(raw.messages) ? raw.messages as GroupDetail['messages'] : []
  const agent_map = (raw.agent_map && typeof raw.agent_map === 'object') ? (raw.agent_map as GroupDetail['agent_map']) : {}
  const agent_names = Array.isArray(raw.agent_names) ? (raw.agent_names as string[]) : []
  const host = (raw.host && typeof raw.host === 'object')
    ? (raw.host as GroupDetail['host'])
    : undefined
  const runtime = (raw.runtime && typeof raw.runtime === 'object')
    ? (raw.runtime as GroupDetail['runtime'])
    : undefined
  return {
    id,
    title: String(raw.title ?? '群聊'),
    messages,
    agent_map,
    agent_names,
    host,
    runtime,
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
  const rt = detail.runtime
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
