type ArtifactDisplayMeta = { label: string; serialized: string }

function parseArtifactDisplayItem(serialized: string): ArtifactDisplayMeta {
  try {
    const parsed = JSON.parse((serialized || '').trim()) as {
      type?: string
      name?: string
      path?: string
    }
    const type = String(parsed?.type || '').trim()
    const name = String(parsed?.name || parsed?.path || '').trim()
    if (type || name) {
      return { label: type ? `artifact: ${type}` : 'artifact', serialized }
    }
  } catch {
    // ignore malformed artifact payloads
  }
  return { label: 'artifact', serialized }
}

const artifactDisplayMetaCache = new Map<string, ArtifactDisplayMeta>()

export function artifactDisplayMeta(serialized: string): ArtifactDisplayMeta {
  const key = String(serialized || '')
  const hit = artifactDisplayMetaCache.get(key)
  if (hit) return hit
  const parsed = parseArtifactDisplayItem(key)
  artifactDisplayMetaCache.set(key, parsed)
  if (artifactDisplayMetaCache.size > 500) {
    const firstKey = artifactDisplayMetaCache.keys().next().value
    if (firstKey) artifactDisplayMetaCache.delete(firstKey)
  }
  return parsed
}

export function formatArtifactPopover(serialized: string): string {
  return tryFormatJson(artifactDisplayMeta(serialized).serialized)
}

export function getArtifactDisplayItems(msg: { skill_result?: { artifacts?: unknown[] } }): string[] {
  return (msg.skill_result?.artifacts || [])
    .map((item) => {
      if (!item || typeof item !== 'object') return ''
      return JSON.stringify(item, null, 2)
    })
    .filter((x) => !!(x || '').trim())
}

function tryFormatJson(s: string): string {
  if (!s?.trim()) return s
  try {
    const parsed = JSON.parse(s.trim())
    return JSON.stringify(parsed, null, 2)
  } catch {
    return s
  }
}

export function agentBodyContent(content: string): string {
  if (!content?.trim()) return ''
  return collapseBlankLines(content.trim())
}

function escapeHtml(s: string) {
  if (!s) return ''
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

function collapseBlankLines(s: string): string {
  if (!s) return ''
  return s
    .replace(/\r\n/g, '\n')
    .trim()
    .replace(/\n[ \t]*\n+/g, '\n\n')
    .replace(/^\s+/, '')
    .replace(/\s+$/, '')
    .trim()
}

export function sanitizeWorkspaceDownloadUrl(raw: string): string {
  let s = (raw || '').trim().replace(/^["'`]+|["'`]+$/g, '').trim()
  if (!s.includes('files/download') || !s.includes('path=')) return s
  try {
    const u = s.startsWith('http') ? new URL(s) : new URL(s, window.location.origin)
    let p = u.searchParams.get('path')
    if (p == null || p === '') return s
    p = p
      .replace(/^["'`]+|["'`]+$/g, '')
      .replace(/,\s*$/g, '')
      .replace(/%22[,;]*$/g, '')
      .trim()
    u.searchParams.set('path', p)
    return u.pathname + u.search + u.hash
  } catch {
    return s
  }
}

function sanitizeDownloadUrlsInRenderedHtml(html: string): string {
  if (!html || !html.includes('files/download')) return html
  return html.replace(/\/api\/workspaces\/[^"'>\s]+\/files\/download\?[^"'>\s]+/gi, (matched) =>
    sanitizeWorkspaceDownloadUrl(matched)
  )
}

function rewriteDownloadImagesForAuth(html: string): string {
  if (!html) return html
  return html.replace(
    /(<img\b[^>]*?)\s+src="([^"]*\/files\/download\?path=[^"]+)"([^>]*?>)/gi,
    (_matched, prefix, src, suffix) => {
      const clean = sanitizeWorkspaceDownloadUrl(src)
      const escaped = clean.replace(/&/g, '&amp;').replace(/"/g, '&quot;')
      return `${prefix} data-agent-auth-src="${escaped}" src=""${suffix}`
    }
  )
}

export function renderMarkdownHtml(md: { render: (s: string) => string } | null, text: string) {
  if (!text) return ''
  if (!md) return escapeHtml(text)
  try {
    let html = md.render(text)
    html = html.replace(/<p>\s*<\/p>/gi, '')
    html = sanitizeDownloadUrlsInRenderedHtml(html)
    html = rewriteDownloadImagesForAuth(html)
    return html
  } catch {
    return escapeHtml(text)
  }
}

export function renderSnippetMarkdownHtml(html: string): string {
  return html.replace(/^<p>\s*/i, '').replace(/\s*<\/p>\s*$/i, '')
}
