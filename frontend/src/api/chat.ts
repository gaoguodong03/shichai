import { apiFetch, apiUrl, type ApiResult } from './base'
import { getSkillsList } from './settings'

export interface ChatStreamRequestPayload {
  message?: string
  session_id: string
  skill_ids?: string[]
  override_next_speaker?: string
  action?: string
  custom_prompt?: string
  host_takeover_requested?: boolean
  ignore_auto_expert_id?: string
  ignore_auto_skill_id?: string
}

export interface StreamChatEventHandlers {
  onRoute?: (data: Record<string, unknown>) => void
  onContent?: (data: { text?: string; agent_id?: string; meta?: { phase?: string } }) => void
  onMessage?: (data: Record<string, unknown>) => void
  onEnd?: (data: Record<string, unknown>) => void
  onError?: (error: unknown) => void
}

export interface ChatOnceResponseData {
  route?: Record<string, unknown> | null
  contents?: Array<{ text?: string; agent_id?: string; meta?: { phase?: string } }>
  messages?: Record<string, unknown>[]
  message?: Record<string, unknown> | null
  end?: Record<string, unknown> | null
  error?: Record<string, unknown> | null
}

/** 兼容旧调用：返回原始 Response（建议改用 streamSessionChat） */
export async function chatStreamRequest(payload: ChatStreamRequestPayload): Promise<Response> {
  const sessionId = encodeURIComponent(payload.session_id || 'default')
  return fetch(apiUrl(`/sessions/${sessionId}/chat/stream`), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      message: payload.message ?? '',
      skill_ids: payload.skill_ids,
      override_next_speaker: payload.override_next_speaker,
      action: payload.action,
      custom_prompt: payload.custom_prompt,
      host_takeover_requested: payload.host_takeover_requested,
      ignore_auto_expert_id: payload.ignore_auto_expert_id,
      ignore_auto_skill_id: payload.ignore_auto_skill_id,
    }),
  })
}

/** POST /api/sessions/:id/chat/stream 并分发 SSE 事件 */
export async function streamSessionChat(
  payload: ChatStreamRequestPayload,
  handlers: StreamChatEventHandlers = {},
  signal?: AbortSignal,
): Promise<void> {
  const sessionId = encodeURIComponent(payload.session_id || 'default')
  const body = {
    message: payload.message ?? '',
    skill_ids: payload.skill_ids,
    override_next_speaker: payload.override_next_speaker,
    action: payload.action,
    custom_prompt: payload.custom_prompt,
    host_takeover_requested: payload.host_takeover_requested,
    ignore_auto_expert_id: payload.ignore_auto_expert_id,
    ignore_auto_skill_id: payload.ignore_auto_skill_id,
  }
  const response = await fetch(apiUrl(`/sessions/${sessionId}/chat/stream`), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  })
  if (!response.ok) throw new Error(response.statusText || `HTTP ${response.status}`)
  if (!response.body) return

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true }).replace(/\r/g, '')
    const parts = buffer.split('\n\n')
    buffer = parts.pop() || ''
    for (const blockRaw of parts) {
      const block = blockRaw.trim()
      if (!block.startsWith('event: ')) continue
      const eventType = (block.split('\n')[0] || '').replace('event: ', '').trim()
      const dataStr = block
        .split('\n')
        .filter((line) => line.startsWith('data: '))
        .map((line) => line.slice(6).trim())
        .join('\n')
      if (!dataStr) continue
      try {
        const data = JSON.parse(dataStr) as Record<string, unknown>
        if (eventType === 'route') handlers.onRoute?.(data)
        else if (eventType === 'content') handlers.onContent?.(data as { text?: string; agent_id?: string; meta?: { phase?: string } })
        else if (eventType === 'message') handlers.onMessage?.(data)
        else if (eventType === 'end') handlers.onEnd?.(data)
      } catch (error) {
        handlers.onError?.(error)
      }
    }
  }
}

/** POST /api/sessions/:id/chat（非流式兜底） */
export async function chatOnceRequest(payload: ChatStreamRequestPayload): Promise<ApiResult<ChatOnceResponseData>> {
  const id = encodeURIComponent(payload.session_id || 'default')
  return apiFetch(`/sessions/${id}/chat`, {
    method: 'POST',
    body: JSON.stringify({
      message: payload.message ?? '',
      skill_ids: payload.skill_ids,
      override_next_speaker: payload.override_next_speaker,
      action: payload.action,
      custom_prompt: payload.custom_prompt,
      host_takeover_requested: payload.host_takeover_requested,
      ignore_auto_expert_id: payload.ignore_auto_expert_id,
      ignore_auto_skill_id: payload.ignore_auto_skill_id,
    }),
  })
}

/** POST /api/sessions/:id/export */
export async function exportSession(sessionId: string): Promise<ApiResult<{ path?: string; download_url?: string }>> {
  const id = encodeURIComponent(sessionId || 'default')
  return apiFetch(`/sessions/${id}/export`, { method: 'POST' })
}

/** 兼容旧调用：技能列表来自 settings/skills */
export async function getSkills(): Promise<
  ApiResult<{ skills: Array<{ id: string; name: string; description?: string; enabled?: boolean; source?: string; path?: string; url?: string }> }>
> {
  return getSkillsList()
}
