import { apiUrl, apiFetch, ApiResult } from './base'

export interface ChatStreamOptions {
  message: string
  session_id?: string
  skill_ids?: string[]
}

/** POST /api/chat/stream，返回 Response 用于流式读取 body */
export function chatStreamRequest(options: ChatStreamOptions): Promise<Response> {
  const url = apiUrl('/chat/stream')
  return fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      message: options.message,
      session_id: options.session_id || 'default',
      ...(options.skill_ids?.length ? { skill_ids: options.skill_ids } : {}),
    }),
  })
}

export interface ExportSessionResult {
  path?: string
  download_url?: string
}

/** POST /api/sessions/:sessionId/export */
export async function exportSession(sessionId: string): Promise<ApiResult<ExportSessionResult>> {
  return apiFetch<ExportSessionResult>(
    `/sessions/${encodeURIComponent(sessionId || 'default')}/export`,
    { method: 'POST' }
  )
}

/** GET /api/settings/skills，用于技能选择器等 */
export async function getSkills(): Promise<ApiResult<{ skills: Array<{ id: string; name: string; enabled?: boolean }> }>> {
  return apiFetch('/settings/skills')
}
