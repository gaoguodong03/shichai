import { apiUrl, apiFetch, ApiResult } from './base'

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

/** 构建导出/下载链接：优先 download_url，否则 /api/files/download?path= */
export function downloadUrl(data: { download_url?: string; path?: string }): string {
  const base = typeof window !== 'undefined' ? window.location.origin : ''
  if (data.download_url) return `${base}${data.download_url}`
  if (data.path) return `${base}/api/files/download?path=${encodeURIComponent(data.path)}`
  return ''
}
