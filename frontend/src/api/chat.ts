import { apiFetch, apiUrl, type ApiResult } from './base'
import { getSkillsList } from './settings'

export interface ChatStreamRequestPayload {
  message?: string
  session_id: string
  skill_ids?: string[]
  override_next_speaker?: string
  action?: string
  custom_prompt?: string
}

/** POST /api/sessions/:id/chat/stream（返回原始 Response 以供 SSE 读取） */
export async function chatStreamRequest(payload: ChatStreamRequestPayload): Promise<Response> {
  const sessionId = encodeURIComponent(payload.session_id || 'default')
  const body = {
    message: payload.message ?? '',
    skill_ids: payload.skill_ids,
    override_next_speaker: payload.override_next_speaker,
    action: payload.action,
    custom_prompt: payload.custom_prompt,
  }
  return fetch(apiUrl(`/sessions/${sessionId}/chat/stream`), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
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
