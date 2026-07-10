import { apiFetch, apiUrl, type ApiResult } from './base'

export interface ChatStreamRequestPayload {
  message?: string
  session_id: string
  client_message_id: string
  attachments?: Array<{ type: 'workspace_file'; path: string; name?: string }>
  target_agent_name?: string | null
}

interface StreamChatEventHandlers {
  onRoute?: (data: Record<string, unknown>) => void
  onProgress?: (data: { text?: string; phase?: string; agent_name?: string; skill?: string }) => void
  onMessage?: (data: Record<string, unknown>) => void
  onEnd?: (data: Record<string, unknown>) => void
  onError?: (error: unknown) => void
}

interface SessionEventHandlers {
  onSnapshot?: (data: Record<string, unknown>) => void
  onRuntime?: (data: Record<string, unknown>) => void
  onMessage?: (data: Record<string, unknown>) => void
  onDeleted?: (data: Record<string, unknown>) => void
  onKeepalive?: (data: Record<string, unknown>) => void
  onError?: (error: unknown) => void
}

interface ChatOnceResponseData {
  route?: Record<string, unknown> | null
  progress?: Array<{ text?: string; phase?: string; agent_name?: string; skill?: string }>
  messages?: Record<string, unknown>[]
  message?: Record<string, unknown> | null
  end?: Record<string, unknown> | null
  error?: Record<string, unknown> | null
}

function chatRequestBody(payload: ChatStreamRequestPayload) {
  const body: {
    message: string
    client_message_id: string
    attachments?: Array<{ type: 'workspace_file'; path: string; name?: string }>
    target_agent_name?: string
  } = {
    message: payload.message ?? '',
    client_message_id: payload.client_message_id,
  }
  const targetAgentName = String(payload.target_agent_name || '').trim()
  if (payload.attachments?.length) body.attachments = payload.attachments
  if (targetAgentName) body.target_agent_name = targetAgentName
  return body
}

async function readEventStream(
  response: Response,
  dispatch: (eventType: string, data: Record<string, unknown>) => void,
  onError?: (error: unknown) => void,
): Promise<void> {
  if (!response.body) return
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  const dispatchBlock = (blockRaw: string) => {
    const block = blockRaw.trim()
    if (!block.startsWith('event: ')) return
    const eventType = (block.split('\n')[0] || '').replace('event: ', '').trim()
    const dataStr = block
      .split('\n')
      .filter((line) => line.startsWith('data: '))
      .map((line) => line.slice(6).trim())
      .join('\n')
    if (!dataStr) return
    try {
      dispatch(eventType, JSON.parse(dataStr) as Record<string, unknown>)
    } catch (error) {
      onError?.(error)
    }
  }
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true }).replace(/\r/g, '')
    const parts = buffer.split('\n\n')
    buffer = parts.pop() || ''
    for (const blockRaw of parts) {
      dispatchBlock(blockRaw)
    }
  }
  buffer += decoder.decode()
  if (buffer.trim()) dispatchBlock(buffer)
}

/** POST /api/sessions/:id/chat/stream 并分发 SSE 事件 */
export async function streamSessionChat(
  payload: ChatStreamRequestPayload,
  handlers: StreamChatEventHandlers = {},
  signal?: AbortSignal,
): Promise<void> {
  const sessionId = encodeURIComponent(payload.session_id || 'default')
  const response = await fetch(apiUrl(`/sessions/${sessionId}/chat/stream`), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(chatRequestBody(payload)),
    signal,
  })
  if (!response.ok) throw new Error(response.statusText || `HTTP ${response.status}`)
  await readEventStream(
    response,
    (eventType, data) => {
      if (eventType === 'route') handlers.onRoute?.(data)
      else if (eventType === 'progress') handlers.onProgress?.(data as { text?: string; phase?: string; agent_name?: string; skill?: string })
      else if (eventType === 'message') handlers.onMessage?.(data)
      else if (eventType === 'end') handlers.onEnd?.(data)
      else if (eventType === 'error') handlers.onError?.(data)
    },
    handlers.onError,
  )
}

/** GET /api/sessions/:id/events/stream 并接收会话主动推送事件 */
export async function streamSessionEvents(
  sessionId: string,
  handlers: SessionEventHandlers = {},
  signal?: AbortSignal,
): Promise<void> {
  const id = encodeURIComponent(sessionId || 'default')
  const response = await fetch(apiUrl(`/sessions/${id}/events/stream`), {
    method: 'GET',
    headers: { Accept: 'text/event-stream' },
    signal,
  })
  if (!response.ok) throw new Error(response.statusText || `HTTP ${response.status}`)
  await readEventStream(
    response,
    (eventType, data) => {
      if (eventType === 'snapshot') handlers.onSnapshot?.(data)
      else if (eventType === 'runtime') handlers.onRuntime?.(data)
      else if (eventType === 'message') handlers.onMessage?.(data)
      else if (eventType === 'deleted') handlers.onDeleted?.(data)
      else if (eventType === 'keepalive') handlers.onKeepalive?.(data)
      else if (eventType === 'error') handlers.onError?.(data)
    },
    handlers.onError,
  )
}

/** POST /api/sessions/:id/chat（非流式聚合） */
export async function chatOnceRequest(payload: ChatStreamRequestPayload): Promise<ApiResult<ChatOnceResponseData>> {
  const id = encodeURIComponent(payload.session_id || 'default')
  return apiFetch(`/sessions/${id}/chat`, {
    method: 'POST',
    body: JSON.stringify(chatRequestBody(payload)),
  })
}
