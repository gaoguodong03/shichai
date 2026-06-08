/**
 * 统一 API 基址：相对当前域名，便于开发时代理与生产同源。
 * 开发时 Vite 可将 /api 代理到后端；生产为同源。
 */
const apiBase =
  typeof import.meta.env?.VITE_API_BASE === 'string' && import.meta.env.VITE_API_BASE
    ? import.meta.env.VITE_API_BASE.replace(/\/$/, '')
    : '/api'

export function apiUrl(path: string): string {
  const p = path.startsWith('/') ? path : `/${path}`
  return p.startsWith(apiBase) ? p : `${apiBase}${p}`
}

export function apiRequest(path: string, options?: RequestInit): Promise<Response> {
  return fetch(apiUrl(path), options)
}

export interface ApiResult<T = unknown> {
  status: 'ok' | 'error'
  data?: T
  error?: { message?: string }
  detail?: string
}

export async function apiFetch<T = unknown>(
  path: string,
  options?: RequestInit
): Promise<ApiResult<T>> {
  const url = apiUrl(path)
  const res = await fetch(url, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...options?.headers,
    },
  })
  const json = (await res.json().catch(() => ({}))) as ApiResult<T>
  if (!res.ok) {
    return {
      status: 'error',
      error: { message: (json as { detail?: string }).detail || res.statusText },
      ...json,
    }
  }
  return json
}
