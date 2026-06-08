export function normalizePartPath(path: string) {
  return String(path || '').replace(/^\/+|\/+$/g, '')
}

export function dirnameOfPath(path: string) {
  const normalized = normalizePartPath(path)
  const idx = normalized.lastIndexOf('/')
  return idx >= 0 ? normalized.slice(0, idx) : ''
}

export function shouldHideEntryByPath(path: string) {
  const normalized = normalizePartPath(path)
  if (!normalized) return false
  const segments = normalized.split('/').filter(Boolean)
  if (segments.some((segment) => segment === '__pycache__')) return true
  const base = segments[segments.length - 1] || ''
  return /\.(pyc|pyo)$/i.test(base)
}

export function validateNewPartPath(
  rawPath: string,
  options: { allowEmpty?: boolean; trimTrailingSlash?: boolean } = {},
) {
  let path = String(rawPath || '').trim().replace(/^\/+/, '')
  if (options.trimTrailingSlash) {
    path = path.replace(/\/+$/, '')
  }
  if (!options.allowEmpty && !path) {
    return { path, error: '路径不能为空' }
  }
  if (path.includes('..')) {
    return { path, error: '路径不能包含 ..' }
  }
  return { path, error: '' }
}
