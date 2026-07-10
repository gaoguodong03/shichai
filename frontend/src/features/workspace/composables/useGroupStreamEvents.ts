import { nextTick, type Ref } from 'vue'
import type { GroupMessage } from './useGroupMessageList'

type StreamEventState = {
  sawExpertAssistantMessageThisRun: boolean
}

type StreamStatusPayload = {
  text?: string
  agent_name?: string
  phase?: string
  skill?: string
}

type StreamRoutePayload = {
  agent_name?: string
  skill?: string
}

const STREAMING_STATUS_DEFAULT = '正在运行中...'

function speakerType(data: Record<string, unknown> | GroupMessage | null | undefined): string {
  const speaker = data?.speaker && typeof data.speaker === 'object' ? data.speaker as { type?: unknown } : null
  return String(speaker?.type || '').trim()
}

function speakerAgentName(data: Record<string, unknown> | GroupMessage | null | undefined): string {
  const speaker = data?.speaker && typeof data.speaker === 'object' ? data.speaker as { agent_name?: unknown } : null
  return String(speaker?.agent_name || '').trim()
}

function messageContent(data: Record<string, unknown> | GroupMessage | null | undefined): string {
  const body = data?.message && typeof data.message === 'object' ? data.message as { content?: unknown } : null
  return String(body?.content ?? '')
}

function toDisplayMessage(data: Record<string, unknown>): GroupMessage {
  return {
    ...data,
    message: {
      ...((data.message && typeof data.message === 'object') ? data.message : {}),
      content: messageContent(data),
    },
  } as GroupMessage
}

function withMessageContent(msg: GroupMessage, content: string): GroupMessage {
  return {
    ...msg,
    message: {
      ...(msg.message || {}),
      content,
    },
  }
}

export function useGroupStreamEvents(args: {
  selectedGroupSessionId: () => string | null
  groupDisplayMessages: Ref<GroupMessage[]>
  groupWaitingForUser: Ref<boolean>
  groupSuggestedNextSpeaker: Ref<string | null>
  groupSuggestedAddAgentNames: Ref<string[]>
  patchGroupStreamState: (sessionId: string, patch: Record<string, unknown>) => void
  scheduleHydrateAuthImages: () => void
  scrollLatestAssistantRowToLowerMiddle: () => void
  scrollGroupAssistantMessageIntoView: (data: Record<string, unknown>) => void
  scrollToMessage: (messageId: string) => void
  applyOrchestrationEndMeta: (data: Record<string, unknown>) => void
  resolveSuggestedNamesFromPayload: (data: Record<string, unknown> | null | undefined) => string[]
  isExpertAssistantMessagePayload: (data: Record<string, unknown> | null | undefined) => boolean
  clearAttachedFiles: () => void
  clearAutoSwitchHint: () => void
}) {
  const {
    selectedGroupSessionId,
    groupDisplayMessages,
    groupWaitingForUser,
    groupSuggestedNextSpeaker,
    groupSuggestedAddAgentNames,
    patchGroupStreamState,
    scheduleHydrateAuthImages,
    scrollLatestAssistantRowToLowerMiddle,
    scrollGroupAssistantMessageIntoView,
    scrollToMessage,
    applyOrchestrationEndMeta,
    resolveSuggestedNamesFromPayload,
    isExpertAssistantMessagePayload,
    clearAttachedFiles,
    clearAutoSwitchHint,
  } = args

  function activeSessionId(sessionId = selectedGroupSessionId() || ''): string {
    return sessionId || selectedGroupSessionId() || ''
  }

  function streamingStatusTextForPhase(phase: string): string {
    const key = String(phase || '').trim().toLowerCase()
    if (!key) return STREAMING_STATUS_DEFAULT
    if (key === 'file_resolving') return '正在处理文件...'
    if (key === 'file_resolved') return '文件已处理，正在继续...'
    if (key === 'tool_running') return '正在运行中...'
    if (key === 'planning') return '正在规划...'
    if (key === 'executing') return '正在执行...'
    if (key === 'assistant_generating') return '正在生成回复...'
    if (key === 'finalizing') return '正在收尾...'
    return STREAMING_STATUS_DEFAULT
  }

  function ensureStreamingStatusPlaceholder(agentName: string, content = STREAMING_STATUS_DEFAULT, extra: Record<string, unknown> = {}) {
    const id = String(agentName || '').trim()
    if (!id) return
    const statusContent = String(content || STREAMING_STATUS_DEFAULT)
    const list = [...groupDisplayMessages.value]
    const last = list[list.length - 1] as (GroupMessage & { _streaming?: boolean; _streamingStatus?: boolean }) | undefined
    const isSameStreaming =
      speakerType(last) === 'expert' && speakerAgentName(last) === id && (last as { _streaming?: boolean })._streaming
    if (isSameStreaming) {
      if ((last as { _streamingStatus?: boolean })._streamingStatus || !messageContent(last).trim()) {
        groupDisplayMessages.value = [
          ...list.slice(0, -1),
          withMessageContent({ ...last, ...extra, _streaming: true, _streamingStatus: true } as GroupMessage, statusContent),
        ]
      }
      return
    }
    const cleared = list.map((m) => ((m as GroupMessage)._streaming ? ({ ...(m as GroupMessage), _streaming: false } as GroupMessage) : m))
    groupDisplayMessages.value = [
      ...cleared,
      {
        speaker: { type: 'expert', agent_name: id },
        message: { content: statusContent, attachments: [] },
        _streaming: true,
        _streamingStatus: true,
        ...extra,
      } as unknown as GroupMessage,
    ]
    scrollLatestAssistantRowToLowerMiddle()
    nextTick(() => scheduleHydrateAuthImages())
  }

  function showStreamingRoutePlaceholder(data: StreamRoutePayload, sessionId = selectedGroupSessionId() || '') {
    if (sessionId && selectedGroupSessionId() !== sessionId) return
    const agentName = String(data?.agent_name || '').trim()
    if (!agentName) return
    const id = activeSessionId(sessionId)
    patchGroupStreamState(id, {
      agentName,
      skill: String(data?.skill || '').trim(),
    })
    ensureStreamingStatusPlaceholder(agentName, STREAMING_STATUS_DEFAULT, {
      speaker: { type: 'expert', agent_name: agentName, skill: String(data?.skill || '').trim() },
    })
  }

  /** Append a progress text chunk to the current expert placeholder. */
  function appendStreamingContent(agentName: string, text: string) {
    const list = [...groupDisplayMessages.value]
    const last = list[list.length - 1] as (GroupMessage & { _streaming?: boolean; _streamingStatus?: boolean }) | undefined
    const appendToExisting =
      speakerType(last) === 'expert' && speakerAgentName(last) === agentName && (last as { _streaming?: boolean })._streaming
    if (appendToExisting) {
      const content = (last as { _streamingStatus?: boolean })._streamingStatus ? text : messageContent(last) + text
      const next = [...list.slice(0, -1), withMessageContent({ ...last, _streamingStatus: false } as GroupMessage, content)]
      groupDisplayMessages.value = next
    } else {
      const cleared = list.map((m) => ((m as GroupMessage)._streaming ? ({ ...(m as GroupMessage), _streaming: false } as GroupMessage) : m))
      groupDisplayMessages.value = [
        ...cleared,
        {
          speaker: { type: 'expert', agent_name: agentName },
          message: { content: text, attachments: [] },
          _streaming: true,
          _streamingStatus: false,
        } as unknown as GroupMessage,
      ]
      scrollLatestAssistantRowToLowerMiddle()
    }
    scrollLatestAssistantRowToLowerMiddle()
    nextTick(() => scheduleHydrateAuthImages())
  }

  /** Replace the streaming placeholder with the complete assistant message. */
  function replaceOrPushAssistantMessage(data: Record<string, unknown>) {
    const displayData = toDisplayMessage(data)
    const list = groupDisplayMessages.value
    const last = list[list.length - 1] as (GroupMessage & { _streaming?: boolean }) | undefined
    const replacedStreamingPlaceholder =
      speakerType(displayData) === 'expert' &&
      speakerType(last) === 'expert' &&
      speakerAgentName(last) === speakerAgentName(displayData) &&
      (last as { _streaming?: boolean })._streaming
    if (replacedStreamingPlaceholder) {
      const { _streaming: _, ...rest } = displayData
      groupDisplayMessages.value = [...list.slice(0, -1), rest as GroupMessage]
    } else {
      groupDisplayMessages.value = [...list, displayData]
    }
    nextTick(() => {
      scheduleHydrateAuthImages()
      if (replacedStreamingPlaceholder) {
        scrollLatestAssistantRowToLowerMiddle()
        return
      }
      scrollGroupAssistantMessageIntoView(displayData as unknown as Record<string, unknown>)
    })
  }

  function clearStreamingPlaceholders() {
    const list = groupDisplayMessages.value || []
    if (!list.length) return
    let changed = false
    const next = list.map((m) => {
      if ((m as GroupMessage)._streaming) {
        changed = true
        return { ...(m as GroupMessage), _streaming: false } as GroupMessage
      }
      return m
    })
    if (changed) groupDisplayMessages.value = next
  }

  function consumeStreamingStatusContent(data: StreamStatusPayload, sessionId = selectedGroupSessionId() || ''): boolean {
    const phase = String(data?.phase || '').trim()
    if (!phase) return false
    const id = activeSessionId(sessionId)
    const agentName = String(data?.agent_name || '').trim()
    if (agentName) ensureStreamingStatusPlaceholder(agentName, streamingStatusTextForPhase(phase))
    if (['file_resolving', 'file_resolved', 'tool_running', 'planning', 'executing', 'assistant_generating', 'finalizing'].includes(phase)) {
      patchGroupStreamState(id, { phase })
      return true
    }
    return false
  }

  function handleStreamMessageEvent(data: Record<string, unknown>, state: StreamEventState, sessionId = selectedGroupSessionId() || '') {
    if (sessionId && selectedGroupSessionId() !== sessionId) return
    const type = speakerType(data)
    if (data && (type === 'expert' || type === 'user' || type === 'host')) {
      if (type === 'expert') {
        replaceOrPushAssistantMessage(data)
        if (isExpertAssistantMessagePayload(data)) {
          state.sawExpertAssistantMessageThisRun = true
        }
      } else {
        groupDisplayMessages.value = [...groupDisplayMessages.value, toDisplayMessage(data)]
        if (type === 'user' && (data as { message_id?: string }).message_id) {
          nextTick(() => scrollToMessage(String((data as { message_id?: string }).message_id || '')))
        }
      }
      const suggestedNames = resolveSuggestedNamesFromPayload(data)
      if (suggestedNames.length) {
        groupSuggestedAddAgentNames.value = suggestedNames
        clearStreamingPlaceholders()
        patchGroupStreamState(activeSessionId(sessionId), { phase: 'recruiting' })
      }
    }
  }

  function handleStreamEndEvent(endData: Record<string, unknown>, state: StreamEventState, sessionId = selectedGroupSessionId() || '') {
    if (sessionId && selectedGroupSessionId() !== sessionId) return
    applyOrchestrationEndMeta(endData)
    if (endData.waiting_for_user) {
      groupWaitingForUser.value = true
      groupSuggestedNextSpeaker.value = endData.suggested_next_speaker != null
        ? String(endData.suggested_next_speaker)
        : null
      const suggestedNames = resolveSuggestedNamesFromPayload(endData)
      if (suggestedNames.length) {
        groupSuggestedAddAgentNames.value = suggestedNames
        clearStreamingPlaceholders()
        patchGroupStreamState(activeSessionId(sessionId), { phase: 'recruiting' })
      }
      if (endData.suggested_next_speaker === 'user' || endData.phase === 'completed') {
        clearAttachedFiles()
      }
    }
    if (endData.phase === 'completed') {
      clearAttachedFiles()
    }
    if (state.sawExpertAssistantMessageThisRun) {
      clearAutoSwitchHint()
    }
  }

  return {
    appendStreamingContent,
    showStreamingRoutePlaceholder,
    replaceOrPushAssistantMessage,
    clearStreamingPlaceholders,
    consumeStreamingStatusContent,
    handleStreamMessageEvent,
    handleStreamEndEvent,
  }
}
