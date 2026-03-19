import { apiFetch, ApiResult } from './base'

/** GET /api/settings/skills */
export async function getSkillsList(): Promise<
  ApiResult<{ skills: Array<{ id: string; name: string; description?: string; enabled?: boolean; source?: string; path?: string; url?: string }> }>
> {
  return apiFetch('/settings/skills')
}

/** POST /api/settings/skills 或 PUT /api/settings/skills/:id */
export async function saveSkill(payload: {
  name: string
  description?: string
  source: 'local' | 'git'
  path?: string
  url?: string
  write_mode?: 'readonly' | 'workspace_all'
  id?: string
}): Promise<ApiResult> {
  const path = payload.id ? `/settings/skills/${payload.id}` : '/settings/skills'
  return apiFetch(path, {
    method: payload.id ? 'PUT' : 'POST',
    body: JSON.stringify(payload),
  })
}

/** DELETE /api/settings/skills/:id */
export async function deleteSkill(id: string): Promise<ApiResult> {
  return apiFetch(`/settings/skills/${id}`, { method: 'DELETE' })
}

/** POST /api/settings/skills/:id/enable 或 disable */
export async function toggleSkill(id: string, enabled: boolean): Promise<ApiResult> {
  const endpoint = enabled ? 'enable' : 'disable'
  return apiFetch(`/settings/skills/${id}/${endpoint}`, { method: 'POST' })
}

/** GET /api/settings/mcp */
export async function getMcpServers(): Promise<
  ApiResult<{ servers: Array<{ id: string; name?: string; enabled?: boolean; [k: string]: unknown }> }>
> {
  return apiFetch('/settings/mcp')
}

/** POST /api/settings/mcp 或 PUT /api/settings/mcp/:id */
export async function saveMcpServer(payload: Record<string, unknown> & { id?: string }): Promise<ApiResult> {
  const path = payload.id ? `/settings/mcp/${payload.id}` : '/settings/mcp'
  return apiFetch(path, {
    method: payload.id ? 'PUT' : 'POST',
    body: JSON.stringify(payload),
  })
}

/** DELETE /api/settings/mcp/:id */
export async function deleteMcpServer(id: string): Promise<ApiResult> {
  return apiFetch(`/settings/mcp/${id}`, { method: 'DELETE' })
}

/** POST /api/settings/mcp/:id/enable 或 disable */
export async function toggleMcpServer(id: string, enabled: boolean): Promise<ApiResult> {
  const endpoint = enabled ? 'enable' : 'disable'
  return apiFetch(`/settings/mcp/${id}/${endpoint}`, { method: 'POST' })
}

/** POST /api/settings/mcp/:id/test */
export async function testMcpServer(id: string): Promise<ApiResult> {
  return apiFetch(`/settings/mcp/${id}/test`, { method: 'POST' })
}
