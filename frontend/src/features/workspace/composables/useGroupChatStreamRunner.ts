import { streamSessionChat, type ChatStreamRequestPayload } from '@/api/chat'

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
            console.error('SSE 事件失败', error)
            const detail = error instanceof Error ? (error.message || '').trim() : String((error as Record<string, unknown>)?.error || (error as Record<string, unknown>)?.detail || '').trim()
            failureHint = detail || failureHint
          },
        },
        signal,
      )
    } catch (error) {
      if (signal?.aborted || (error instanceof DOMException && error.name === 'AbortError')) {
        return false
      }
      streamFailed = true
      console.error('SSE 请求失败', error)
      failureHint = error instanceof Error ? (error.message || '').trim() : ''
    }

    if (signal?.aborted) return false

    if (!gotEnd || streamFailed || streamServerErrored) {
      deps.setStreamingPhase('failed', sessionId)
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
