export type ReferenceSnapshot = { id: string; name?: string }

const DEFAULT_ID_KEYS = ['id']

export function normalizeReferenceRows(raw: unknown, idKeys: string[] = DEFAULT_ID_KEYS): ReferenceSnapshot[] {
  if (!Array.isArray(raw)) return []
  const out: ReferenceSnapshot[] = []
  const seen = new Set<string>()
  for (const item of raw) {
    const row = item && typeof item === 'object' ? item as Record<string, unknown> : null
    const id = idKeys.map((key) => String(row?.[key] || '').trim()).find(Boolean) || ''
    const name = String(row?.name || row?.display_name || row?.label || '').trim()
    if (!id || seen.has(id)) continue
    out.push(name ? { id, name } : { id })
    seen.add(id)
  }
  return out
}

export function mergeReferenceRowsForIds(
  ids: string[],
  refs?: ReferenceSnapshot[],
  lookup?: Record<string, string>,
  idKeys: string[] = DEFAULT_ID_KEYS,
): ReferenceSnapshot[] {
  const old = new Map(normalizeReferenceRows(refs || [], idKeys).map((row) => [row.id, row.name || '']))
  const seen = new Set<string>()
  const out: ReferenceSnapshot[] = []
  for (const raw of ids || []) {
    const id = String(raw || '').trim()
    if (!id || seen.has(id)) continue
    const name = String((lookup || {})[id] || old.get(id) || '').trim()
    out.push(name ? { id, name } : { id })
    seen.add(id)
  }
  return out
}
