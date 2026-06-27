type ToolRawMeta = { toolName: string; rawReturn: string }

function parseToolRawResult(raw: string): ToolRawMeta {
  const matched = raw.match(/^工具\s+([^\s]+)\s+的执行结果:\s*/)
  if (matched) return { toolName: matched[1], rawReturn: raw.slice(matched[0].length) || raw }
  try {
    const parsed = JSON.parse((raw || '').trim()) as {
      action?: string
      tool?: string
      _sandbox_trace?: { tool_name?: string }
    }
    if (parsed?.action === 'tool_call' && parsed?.tool) {
      return { toolName: String(parsed.tool), rawReturn: raw }
    }
    if (parsed?._sandbox_trace) {
      const sandboxToolName = String(parsed._sandbox_trace.tool_name || '').trim()
      return { toolName: sandboxToolName ? `sandbox: ${sandboxToolName}` : 'sandbox', rawReturn: raw }
    }
  } catch {
    // ignore malformed tool payloads
  }
  return { toolName: 'sandbox', rawReturn: raw }
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

export function getSchedulerStateRaw(msg: { meta?: unknown }): string {
  const meta = msg.meta && typeof msg.meta === 'object' ? msg.meta as { scheduler_state?: unknown } : null
  const state = meta?.scheduler_state
  if (!state || typeof state !== 'object') return ''
  const data = state as {
    current_phase?: unknown
    next_speaker?: unknown
    speaker_task?: unknown
  }
  const out = {
    current_phase: String(data.current_phase || '').trim(),
    next_speaker: String(data.next_speaker || '').trim(),
    speaker_task: String(data.speaker_task || '').trim(),
  }
  if (!out.current_phase && !out.next_speaker && !out.speaker_task) return ''
  return JSON.stringify(out, null, 2)
}

export function formatSchedulerStatePopover(raw: string): string {
  return tryFormatJson(raw)
}

function extractToolCallBlocks(content: string): string[] {
  const text = content || ''
  if (!text.trim()) return []
  const blocks = text.match(/```json\s*([\s\S]*?)```/gi) || []
  const out: string[] = []
  for (const block of blocks) {
    const inner = block.replace(/^```json\s*/i, '').replace(/```$/i, '').trim()
    if (!inner) continue
    try {
      const parsed = JSON.parse(inner) as { action?: string; tool?: string }
      if (parsed?.action === 'tool_call' && parsed?.tool) {
        out.push(inner)
      }
    } catch {
      // ignore malformed fenced JSON
    }
  }
  return out
}

export function getToolRawResults(msg: { content?: string; tool_raw_results?: string[] }): string[] {
  const explicit = (msg.tool_raw_results || []).filter((x) => !!(x || '').trim())
  if (explicit.length) return explicit
  return extractToolCallBlocks(msg.content || '')
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
