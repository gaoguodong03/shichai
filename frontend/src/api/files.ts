import { apiFetch, ApiResult } from './base'

export interface FileEntry {
  name: string
  path: string
  is_dir?: boolean
  size?: number
}

/** GET /api/workspaces/:workspaceId/files?path=... */
export async function listWorkspaceFiles(
  workspaceId: string,
  path?: string
): Promise<ApiResult<{ entries: FileEntry[] }>> {
  const base = `/workspaces/${encodeURIComponent(workspaceId)}/files`
  const url = path ? `${base}?path=${encodeURIComponent(path)}` : base
  return apiFetch(url)
}

/** 构建后端返回的导出/下载链接。 */
export function downloadUrl(data: { download_url?: string; path?: string }): string {
  const base = typeof window !== 'undefined' ? window.location.origin : ''
  if (data.download_url) return `${base}${data.download_url}`
  return ''
}
