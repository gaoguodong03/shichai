import { apiRequest } from '@/api/base'

export type ForkedSessionRow = {
  id: string
  title?: string
  updated_at?: string
}

export async function loadForkedSessionRow(sessionId: string): Promise<ForkedSessionRow> {
  const id = (sessionId || '').trim()
  if (!id) throw new Error('sessionId is required')
  const response = await apiRequest(`/sessions/${encodeURIComponent(id)}`)
  const payload = await response.json().catch(() => null)
  if (!response.ok || payload?.status !== 'ok' || !payload?.data) {
    throw new Error('forked session detail response is invalid')
  }
  return {
    id,
    title: typeof payload.data.title === 'string' ? payload.data.title : undefined,
    updated_at: typeof payload.data.updated_at === 'string' ? payload.data.updated_at : undefined,
  }
}
