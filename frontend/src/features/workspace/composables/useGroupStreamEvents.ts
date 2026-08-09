import { nextTick, type Ref } from 'vue'
import type { GroupMessage } from './useGroupMessageList'

type StreamEventState = {
  sawExpertAssistantMessageThisRun: boolean
  sawPersistedFailureMessage: boolean
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

const EXPERT_RUNNING_PLACEHOLDER_TEXT = '正在运行中...'

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

function isPersistedFailureMessage(data: Record<string, unknown>): boolean {
  const skillResult = data?.skill_result && typeof data.skill_result === 'object'
    ? data.skill_result as { execution_status?: unknown }
    : null
  return String(skillResult?.execution_status || '').trim().toLowerCase() === 'failed'
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
  syncMessageExecutionLogs?: (msg: GroupMessage | Record<string, unknown> | null | undefined) => void
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
    syncMessageExecutionLogs,
  } = args

  function activeSessionId(sessionId = selectedGroupSessionId() || ''): string {
    return sessionId || selectedGroupSessionId() || ''
  }

  function ensureStreamingExpertPlaceholder(data: StreamRoutePayload, sessionId = selectedGroupSessionId() || '') {
    if (sessionId && selectedGroupSessionId() !== sessionId) return
    const agentName = String(data?.agent_name || '').trim()
    if (!agentName) return
    const list = groupDisplayMessages.value || []
    const existingIndex = list.findIndex((message) => (message as GroupMessage)._streamingStatus)
    const existing = existingIndex >= 0 ? list[existingIndex] as GroupMessage : null
    const incomingSkill = String(data?.skill || '').trim()
    const skill = incomingSkill || (
      speakerAgentName(existing) === agentName
        ? String(existing?.speaker?.skill || '').trim()
        : ''
    )
    const placeholder: GroupMessage = {
      speaker: {
        type: 'expert',
        agent_name: agentName,
        ...(skill ? { skill } : {}),
      },
      message: { content: EXPERT_RUNNING_PLACEHOLDER_TEXT },
      _streaming: true,
      _streamingStatus: true,
    }
    if (existingIndex < 0) {
      groupDisplayMessages.value = [...list, placeholder]
      nextTick(() => scrollLatestAssistantRowToLowerMiddle())
      return
    }
    if (
      speakerAgentName(existing) === agentName &&
      String(existing.speaker?.skill || '').trim() === skill &&
      messageContent(existing) === EXPERT_RUNNING_PLACEHOLDER_TEXT
    ) return
    groupDisplayMessages.value = [
      ...list.slice(0, existingIndex),
      placeholder,
      ...list.slice(existingIndex + 1),
    ]
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
    ensureStreamingExpertPlaceholder(data, sessionId)
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
    syncMessageExecutionLogs?.(displayData)
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
    const next = list.filter((m) => {
      if ((m as GroupMessage)._streamingStatus) {
        changed = true
        return false
      }
      return true
    }).map((m) => {
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
    if (['file_resolving', 'file_resolved', 'tool_running', 'planning', 'executing', 'assistant_generating', 'finalizing'].includes(phase)) {
      const skill = String(data?.skill || '').trim()
      patchGroupStreamState(id, {
        phase,
        ...(agentName ? { agentName } : {}),
        ...(skill ? { skill } : {}),
      })
      if (agentName) ensureStreamingExpertPlaceholder({ agent_name: agentName, skill }, sessionId)
      return true
    }
    return false
  }

  function handleStreamMessageEvent(data: Record<string, unknown>, state: StreamEventState, sessionId = selectedGroupSessionId() || '') {
    if (sessionId && selectedGroupSessionId() !== sessionId) return
    const type = speakerType(data)
    if (data && (type === 'expert' || type === 'user' || type === 'host')) {
      if (isPersistedFailureMessage(data)) {
        state.sawPersistedFailureMessage = true
      }
      if (type === 'expert') {
        replaceOrPushAssistantMessage(data)
        if (isExpertAssistantMessagePayload(data)) {
          state.sawExpertAssistantMessageThisRun = true
        }
      } else {
        const displayData = toDisplayMessage(data)
        groupDisplayMessages.value = [...groupDisplayMessages.value, displayData]
        syncMessageExecutionLogs?.(displayData)
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
      clearAttachedFiles()
    }
    if (state.sawExpertAssistantMessageThisRun) {
      clearAutoSwitchHint()
    }
  }

  return {
    showStreamingRoutePlaceholder,
    ensureStreamingExpertPlaceholder,
    replaceOrPushAssistantMessage,
    clearStreamingPlaceholders,
    consumeStreamingStatusContent,
    handleStreamMessageEvent,
    handleStreamEndEvent,
  }
}
