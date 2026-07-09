import { chatOnceRequest, streamSessionChat, type ChatStreamRequestPayload } from '@/api/chat'

type StreamState = { sawExpertAssistantMessageThisRun: boolean }
type StreamProgress = { text?: string; agent_name?: string; phase?: string; skill?: string }
type StreamRoute = { agent_name?: string; skill?: string }

export function createGroupChatStreamRunner(deps: {
  isSelectedSession: (sessionId: string) => boolean
  setStreamingPhase: (phase: string, sessionId: string) => void
  appendHostError: (content: string) => void
  updateAutoSwitchHint: (payload: Record<string, unknown>, sessionId: string) => void
  showStreamingRoutePlaceholder: (payload: StreamRoute, sessionId: string) => void
  consumeStreamingStatusContent: (data: StreamProgress, sessionId: string) => boolean
  appendStreamingContent: (agentName: string, text: string) => void
  handleStreamMessageEvent: (data: Record<string, unknown>, state: StreamState, sessionId: string) => void
  handleStreamEndEvent: (data: Record<string, unknown>, state: StreamState, sessionId: string) => void
}) {
  return async function runGroupStream(
    sessionId: string,
    payload: Omit<ChatStreamRequestPayload, 'session_id'>,
    signal?: AbortSignal,
  ): Promise<boolean> {
    const isSelectedStreamSession = () => deps.isSelectedSession(sessionId)
    const state = { sawExpertAssistantMessageThisRun: false }
    let shouldEmitMessageSent = false
    let gotEnd = false
    let streamFailed = false
    let streamServerErrored = false
    let failureHint = ''
    try {
      await streamSessionChat(
        { ...payload, session_id: sessionId },
        {
          onRoute: (data) => {
            deps.updateAutoSwitchHint(data, sessionId)
            deps.showStreamingRoutePlaceholder(data, sessionId)
          },
          onProgress: (data) => {
            if (data?.text != null && data?.agent_name) {
              if (deps.consumeStreamingStatusContent(data, sessionId)) return
              if (!isSelectedStreamSession()) return
              deps.appendStreamingContent(data.agent_name, data.text)
            }
          },
          onMessage: (data) => {
            deps.handleStreamMessageEvent(data, state, sessionId)
          },
          onEnd: (data) => {
            deps.handleStreamEndEvent(data, state, sessionId)
            shouldEmitMessageSent = true
            gotEnd = true
          },
          onError: (error) => {
            streamServerErrored = true
            console.error('SSE 事件解析失败', error)
          },
        },
        signal,
      )
    } catch (error) {
      if (signal?.aborted || (error instanceof DOMException && error.name === 'AbortError')) {
        return false
      }
      streamFailed = true
      console.error('SSE 请求失败，准备非流式补偿', error)
      failureHint = error instanceof Error ? (error.message || '').trim() : ''
    }

    if (signal?.aborted) return false

    if (!gotEnd || streamFailed || streamServerErrored) {
      deps.setStreamingPhase('tool_running', sessionId)
      try {
        const fallback = await chatOnceRequest({ ...payload, session_id: sessionId })
        if (fallback.status !== 'ok') {
          const detail = String(fallback.error?.message || fallback.detail || '').trim()
          failureHint = detail || failureHint
          throw new Error(detail || 'chat once fallback failed')
        }
        const data = (fallback.data || {}) as {
          route?: Record<string, unknown> | null
          progress?: StreamProgress[]
          messages?: Record<string, unknown>[]
          message?: Record<string, unknown> | null
          end?: Record<string, unknown> | null
          error?: Record<string, unknown> | null
        }
        if (data.route) deps.updateAutoSwitchHint(data.route, sessionId)
        if (Array.isArray(data.progress)) {
          for (const chunk of data.progress) {
            if (chunk?.text != null && chunk?.agent_name) {
              if (deps.consumeStreamingStatusContent(chunk, sessionId)) continue
              if (!isSelectedStreamSession()) continue
              deps.appendStreamingContent(chunk.agent_name, chunk.text)
            }
          }
        }
        if (Array.isArray(data.messages)) {
          for (const msg of data.messages) deps.handleStreamMessageEvent(msg, state, sessionId)
        }
        if (data.message) deps.handleStreamMessageEvent(data.message, state, sessionId)
        if (data.end) {
          deps.handleStreamEndEvent(data.end, state, sessionId)
          shouldEmitMessageSent = true
        }
        if (!data.end && data.error) {
          const errText = String(data.error?.error || data.error?.detail || '').trim()
          failureHint = errText || failureHint
          deps.setStreamingPhase('failed', sessionId)
        }
      } catch (fallbackError) {
        console.error('非流式补偿失败', fallbackError)
        const errText = fallbackError instanceof Error ? (fallbackError.message || '').trim() : ''
        failureHint = failureHint || errText
        deps.setStreamingPhase('failed', sessionId)
      }
    }
    if (!shouldEmitMessageSent && !gotEnd && isSelectedStreamSession()) {
      const visibleError = failureHint
        ? `系统提示：本轮请求失败（${failureHint}）。请重新登录后重试。`
        : '系统提示：本轮请求失败。请重新登录后重试。'
      deps.appendHostError(visibleError)
    }
    return shouldEmitMessageSent
  }
}
