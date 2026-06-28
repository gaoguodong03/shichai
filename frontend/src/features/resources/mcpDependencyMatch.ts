import { normalizeReferenceRows, type ReferenceSnapshot } from './referenceSnapshots'

const MCP_REFERENCE_ID_KEYS = ['id', 'mcp_server_id']

export function normalizedMcpNameKey(raw: unknown): string {
  return String(raw ?? '').trim().toLowerCase()
}

export type McpServerRow = { id: string; name?: string; enabled?: boolean }

export function buildMcpServerIndex(servers: McpServerRow[]) {
  const byId = new Map<string, McpServerRow>()
  const byName = new Map<string, McpServerRow>()
  for (const server of servers) {
    const id = String(server.id || '').trim()
    if (id) byId.set(id, server)
    const nameKey = normalizedMcpNameKey(server.name)
    if (nameKey && !byName.has(nameKey)) byName.set(nameKey, server)
  }
  return { byId, byName }
}

function uniqueNameContainsMatch(candidate: string, index: ReturnType<typeof buildMcpServerIndex>): McpServerRow | null {
  const key = normalizedMcpNameKey(candidate)
  if (!key) return null
  const matches = Array.from(index.byName.entries())
    .filter(([nameKey]) => nameKey.includes(key))
    .map(([, server]) => server)
  return matches.length === 1 ? matches[0] : null
}

export function resolveMcpDeclaration(
  declaredId: string,
  mcpRefs: ReferenceSnapshot[],
  index: ReturnType<typeof buildMcpServerIndex>,
): McpServerRow | null {
  const decl = String(declaredId || '').trim()
  if (!decl) return null
  if (index.byId.has(decl)) return index.byId.get(decl) || null
  const snap = normalizeReferenceRows(mcpRefs, MCP_REFERENCE_ID_KEYS).find((row) => row.id === decl)
  for (const candidate of [decl, snap?.name]) {
    const nameKey = normalizedMcpNameKey(candidate)
    if (!nameKey) continue
    const hit = index.byName.get(nameKey)
    if (hit) return hit
    const fuzzyHit = uniqueNameContainsMatch(candidate, index)
    if (fuzzyHit) return fuzzyHit
  }
  return null
}

export function isMcpDeclarationMissing(
  declaredId: string,
  mcpRefs: ReferenceSnapshot[],
  index: ReturnType<typeof buildMcpServerIndex>,
): boolean {
  return resolveMcpDeclaration(declaredId, mcpRefs, index) === null
}
