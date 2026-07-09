type ToolRawMeta = { toolName: string; rawReturn: string }

function parseToolRawResult(raw: string): ToolRawMeta {
  try {
    const parsed = JSON.parse((raw || '').trim()) as {
      type?: string
      name?: string
      path?: string
    }
    const type = String(parsed?.type || '').trim()
    const name = String(parsed?.name || parsed?.path || '').trim()
    if (type || name) {
      return { toolName: type ? `artifact: ${type}` : 'artifact', rawReturn: raw }
    }
  } catch {
    // ignore malformed artifact payloads
  }
  return { toolName: 'artifact', rawReturn: raw }
}

const toolRawMetaCache = new Map<string, ToolRawMeta>()

export function toolRawMeta(raw: string): ToolRawMeta {
  const key = String(raw || '')
  const hit = toolRawMetaCache.get(key)
  if (hit) return hit
  const parsed = parseToolRawResult(key)
  toolRawMetaCache.set(key, parsed)
  if (toolRawMetaCache.size > 500) {
    const firstKey = toolRawMetaCache.keys().next().value
    if (firstKey) toolRawMetaCache.delete(firstKey)
  }
  return parsed
}

export function formatToolPopover(raw: string): string {
  return tryFormatJson(toolRawMeta(raw).rawReturn)
}

export function getToolRawResults(msg: { skill_result?: { artifacts?: unknown[] } }): string[] {
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

function unescapeHtmlEntities(s: string) {
  if (!s) return ''
  return s
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&amp;/g, '&')
}

function wrapToolCallPreBlocks(html: string) {
  if (!html) return html

  const wrapOne = (rawInner: string) => {
    const inner = rawInner.trim()
    const text = unescapeHtmlEntities(inner)
      .replace(/<code[^>]*>/gi, '')
      .replace(/<\/code>/gi, '')
      .replace(/<[^>]+>/g, '')
      .trim()

    if (!text.startsWith('{') || !text.includes('"tool"')) return null
    try {
      const parsed = JSON.parse(text) as { action?: string; tool?: string; arguments?: unknown }
      if (parsed?.action !== 'tool_call' || !parsed?.tool) return null
      const toolName = String(parsed.tool)
      const pretty = JSON.stringify(parsed, null, 2)
      return [
        `<details class="group-chat-tool-call" data-tool="${escapeHtml(toolName)}">`,
        `<summary class="group-chat-tool-call-summary">`,
        `<span class="group-chat-tool-call-pill">${escapeHtml(toolName)}</span>`,
        `<span class="group-chat-tool-call-hint">工具调用</span>`,
        `</summary>`,
        `<pre class="group-chat-tool-call-pre">${escapeHtml(pretty)}</pre>`,
        `</details>`,
      ].join('')
    } catch {
      return null
    }
  }

  return html.replace(/<pre>([\s\S]*?)<\/pre>/gi, (matched, inner) => {
    const wrapped = wrapOne(inner)
    return wrapped ?? matched
  })
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
    html = wrapToolCallPreBlocks(html)
    html = rewriteDownloadImagesForAuth(html)
    return html
  } catch {
    return escapeHtml(text)
  }
}

export function renderSnippetMarkdownHtml(html: string): string {
  return html.replace(/^<p>\s*/i, '').replace(/\s*<\/p>\s*$/i, '')
}
