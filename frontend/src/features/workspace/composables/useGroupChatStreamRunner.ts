import { streamSessionChat, type ChatStreamRequestPayload } from '@/api/chat'

type StreamState = {
  sawExpertAssistantMessageThisRun: boolean
  sawPersistedFailureMessage: boolean
}
type StreamProgress = { text?: string; agent_name?: string; phase?: string; skill?: string }
type StreamRoute = { agent_name?: string; skill?: string }

function streamErrorDetail(error: unknown): string {
  if (error instanceof Error) return String(error.message || '').trim()
  const payload = error as Record<string, unknown> | null | undefined
  return String(payload?.message || payload?.detail || payload?.error || '').trim()
}

export function createGroupChatStreamRunner(deps: {
  isSelectedSession: (sessionId: string) => boolean
  setStreamingPhase: (phase: string, sessionId: string) => void
  appendHostError: (content: string) => void
  updateAutoSwitchHint: (payload: Record<string, unknown>, sessionId: string) => void
  showStreamingRoutePlaceholder: (payload: StreamRoute, sessionId: string) => void
  consumeStreamingStatusContent: (data: StreamProgress, sessionId: string) => boolean
  handleStreamMessageEvent: (data: Record<string, unknown>, state: StreamState, sessionId: string) => void
  handleStreamEndEvent: (data: Record<string, unknown>, state: StreamState, sessionId: string) => void
}) {
  return async function runGroupStream(
    sessionId: string,
    payload: Omit<ChatStreamRequestPayload, 'session_id'>,
    signal?: AbortSignal,
  ): Promise<boolean> {
    const isSelectedStreamSession = () => deps.isSelectedSession(sessionId)
    const state: StreamState = {
      sawExpertAssistantMessageThisRun: false,
      sawPersistedFailureMessage: false,
    }
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
            deps.consumeStreamingStatusContent(data, sessionId)
          },
          onMessage: (data) => {
            if (streamServerErrored) state.sawPersistedFailureMessage = true
            deps.handleStreamMessageEvent(data, state, sessionId)
          },
          onEnd: (data) => {
            deps.handleStreamEndEvent(data, state, sessionId)
            const endFailed = String(data?.phase || '').trim().toLowerCase() === 'failed'
            shouldEmitMessageSent = !endFailed && !streamServerErrored
            gotEnd = true
          },
          onError: (error) => {
            streamServerErrored = true
            console.error('SSE 事件失败', error)
            const detail = streamErrorDetail(error)
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

    const runFailed = !gotEnd || streamFailed || streamServerErrored || !shouldEmitMessageSent
    if (runFailed) {
      deps.setStreamingPhase('failed', sessionId)
    }
    if (runFailed && !state.sawPersistedFailureMessage && isSelectedStreamSession()) {
      const visibleError = failureHint
        ? `系统提示：本轮请求失败（${failureHint}）。请重新登录后重试。`
        : '系统提示：本轮请求失败。请重新登录后重试。'
      deps.appendHostError(visibleError)
    }
    return shouldEmitMessageSent
  }
}
