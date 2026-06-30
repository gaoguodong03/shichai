import { nextTick, type Ref } from 'vue'
import { appAlert } from '@/composables/useAppDialog'
import type { GroupMessage } from './useGroupMessageList'

type StreamEventState = {
  sawExpertAssistantMessageThisRun: boolean
}

type StreamStatusPayload = {
  text?: string
  agent_name?: string
  meta?: { phase?: string }
}

type StreamRoutePayload = {
  agent_name?: string
  skill?: string
}

const STREAMING_STATUS_DEFAULT = '正在运行中...'

export function useGroupStreamEvents(args: {
  selectedGroupSessionId: () => string | null
  groupDisplayMessages: Ref<GroupMessage[]>
  groupNextPrompt: Ref<string>
  groupTurnLimitReached: Ref<boolean>
  groupWaitingForUser: Ref<boolean>
  groupSuggestedNextSpeaker: Ref<string | null>
  groupSuggestedAddAgentNames: Ref<string[]>
  patchGroupStreamState: (sessionId: string, patch: Record<string, unknown>) => void
  scheduleHydrateAuthImages: () => void
  scrollLatestAssistantRowToLowerMiddle: () => void
  scrollGroupAssistantMessageIntoView: (data: Record<string, unknown>) => void
  scrollToMessage: (messageId: string) => void
  applyOrchestrationEndMeta: (data: Record<string, unknown>) => void
  extractAutoInvitedNames: (data: Record<string, unknown> | null | undefined) => string[]
  resolveSuggestedNamesFromPayload: (data: Record<string, unknown> | null | undefined) => string[]
  isExpertAssistantMessagePayload: (data: Record<string, unknown> | null | undefined) => boolean
  clearAttachedFiles: () => void
  clearAutoSwitchHint: () => void
  emitAgentAdded: () => void
  loadGroupDetail: () => Promise<void> | void
  confirmGroupNext: (nextSpeaker: string) => Promise<void> | void
}) {
  const {
    selectedGroupSessionId,
    groupDisplayMessages,
    groupNextPrompt,
    groupTurnLimitReached,
    groupWaitingForUser,
    groupSuggestedNextSpeaker,
    groupSuggestedAddAgentNames,
    patchGroupStreamState,
    scheduleHydrateAuthImages,
    scrollLatestAssistantRowToLowerMiddle,
    scrollGroupAssistantMessageIntoView,
    scrollToMessage,
    applyOrchestrationEndMeta,
    extractAutoInvitedNames,
    resolveSuggestedNamesFromPayload,
    isExpertAssistantMessagePayload,
    clearAttachedFiles,
    clearAutoSwitchHint,
    emitAgentAdded,
    loadGroupDetail,
    confirmGroupNext,
  } = args

  function activeSessionId(sessionId = selectedGroupSessionId() || ''): string {
    return sessionId || selectedGroupSessionId() || ''
  }

  function streamingStatusTextForPhase(phase: string): string {
    const key = String(phase || '').trim().toLowerCase()
    if (!key) return STREAMING_STATUS_DEFAULT
    if (key === 'file_resolving' || key === 'preparing') return '正在处理文件...'
    if (key === 'file_resolved' || key === 'file_parsed') return '文件已处理，正在继续...'
    if (
      key === 'file_writing' ||
      key === 'file_write' ||
      key === 'writing_file' ||
      key === 'workspace_writing'
    ) {
      return '写入文件中...'
    }
    if (key === 'file_written' || key === 'workspace_written') return '文件已写入，正在继续...'
    if (key === 'tool_running' || key === 'tool_pending') return '正在运行中...'
    if (key === 'agent_waiting') return '正在等待任务完成...'
    if (key === 'generating' || key === 'llm_generating' || key === 'assistant_generating') return '正在生成回复...'
    return STREAMING_STATUS_DEFAULT
  }

  function ensureStreamingStatusPlaceholder(agentName: string, content = STREAMING_STATUS_DEFAULT, extra: Record<string, unknown> = {}) {
    const id = String(agentName || '').trim()
    if (!id) return
    const statusContent = String(content || STREAMING_STATUS_DEFAULT)
    const list = [...groupDisplayMessages.value]
    const last = list[list.length - 1] as (GroupMessage & { _streaming?: boolean; _streamingStatus?: boolean }) | undefined
    const isSameStreaming =
      last?.role === 'assistant' && last?.agent_name === id && (last as { _streaming?: boolean })._streaming
    if (isSameStreaming) {
      if ((last as { _streamingStatus?: boolean })._streamingStatus || !(last.content || '').trim()) {
        groupDisplayMessages.value = [
          ...list.slice(0, -1),
          { ...last, ...extra, content: statusContent, _streaming: true, _streamingStatus: true } as GroupMessage,
        ]
      }
      return
    }
    const cleared = list.map((m) => ((m as GroupMessage)._streaming ? ({ ...(m as GroupMessage), _streaming: false } as GroupMessage) : m))
    groupDisplayMessages.value = [
      ...cleared,
      {
        role: 'assistant',
        agent_name: id,
        content: statusContent,
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
      phase: STREAMING_STATUS_DEFAULT,
      agentName,
      skill: String(data?.skill || '').trim(),
    })
    ensureStreamingStatusPlaceholder(agentName, STREAMING_STATUS_DEFAULT, {
      skill: String(data?.skill || '').trim(),
    })
  }

  /** 流式展示：追加一条 content chunk 到当前专家占位消息，或新建占位 */
  function appendStreamingContent(agentName: string, text: string) {
    const list = [...groupDisplayMessages.value]
    const last = list[list.length - 1] as (GroupMessage & { _streaming?: boolean; _streamingStatus?: boolean }) | undefined
    const appendToExisting =
      last?.role === 'assistant' && last?.agent_name === agentName && (last as { _streaming?: boolean })._streaming
    if (appendToExisting) {
      const content = (last as { _streamingStatus?: boolean })._streamingStatus ? text : (last.content || '') + text
      const next = [...list.slice(0, -1), { ...last, content, _streamingStatus: false } as GroupMessage]
      groupDisplayMessages.value = next
    } else {
      const cleared = list.map((m) => ((m as GroupMessage)._streaming ? ({ ...(m as GroupMessage), _streaming: false } as GroupMessage) : m))
      groupDisplayMessages.value = [...cleared, { role: 'assistant', agent_name: agentName, content: text, _streaming: true, _streamingStatus: false } as unknown as GroupMessage]
      scrollLatestAssistantRowToLowerMiddle()
    }
    scrollLatestAssistantRowToLowerMiddle()
    nextTick(() => scheduleHydrateAuthImages())
  }

  /** 流式结束：用服务端完整 assistant 消息替换占位，或直接追加 */
  function replaceOrPushAssistantMessage(data: Record<string, unknown>) {
    const list = groupDisplayMessages.value
    const last = list[list.length - 1] as (GroupMessage & { _streaming?: boolean }) | undefined
    const replacedStreamingPlaceholder =
      data.role === 'assistant' &&
      last?.role === 'assistant' &&
      last?.agent_name === data.agent_name &&
      (last as { _streaming?: boolean })._streaming
    if (replacedStreamingPlaceholder) {
      const { _streaming: _, ...rest } = data
      groupDisplayMessages.value = [...list.slice(0, -1), rest as GroupMessage]
    } else {
      groupDisplayMessages.value = [...list, data as GroupMessage]
    }
    nextTick(() => {
      scheduleHydrateAuthImages()
      if (replacedStreamingPlaceholder) {
        scrollLatestAssistantRowToLowerMiddle()
        return
      }
      scrollGroupAssistantMessageIntoView(data)
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
    const phase = String(data?.meta?.phase || '').trim()
    if (!phase) return false
    const id = activeSessionId(sessionId)
    const agentName = String(data?.agent_name || '').trim()
    if (agentName) ensureStreamingStatusPlaceholder(agentName, streamingStatusTextForPhase(phase))
    if (phase === 'file_resolving' || phase === 'preparing') {
      patchGroupStreamState(id, { phase: '正在处理文件引用…' })
      return true
    }
    if (phase === 'file_resolved' || phase === 'file_parsed') {
      patchGroupStreamState(id, { phase: '文件引用已处理' })
      return true
    }
    if (phase === 'file_writing' || phase === 'file_write' || phase === 'writing_file' || phase === 'workspace_writing') {
      patchGroupStreamState(id, { phase: '写入文件中…' })
      return true
    }
    if (phase === 'file_written' || phase === 'workspace_written') {
      patchGroupStreamState(id, { phase: '文件已写入' })
      return true
    }
    if (phase === 'tool_running' || phase === 'tool_pending') {
      patchGroupStreamState(id, { phase: '技能任务运行中，完成后会继续回复…' })
      return true
    }
    if (phase === 'agent_waiting') {
      patchGroupStreamState(id, { phase: '仍在等待技能任务完成…' })
      return true
    }
    return false
  }

  function handleStreamMessageEvent(data: Record<string, unknown>, state: StreamEventState, sessionId = selectedGroupSessionId() || '') {
    if (sessionId && selectedGroupSessionId() !== sessionId) return
    patchGroupStreamState(activeSessionId(sessionId), { phase: '正在生成回复…' })
    if (data && (data.role === 'assistant' || data.role === 'user' || data.role === 'host')) {
      if (data.role === 'assistant') {
        replaceOrPushAssistantMessage(data)
        if (isExpertAssistantMessagePayload(data)) {
          state.sawExpertAssistantMessageThisRun = true
        }
      } else {
        groupDisplayMessages.value = [...groupDisplayMessages.value, data as GroupMessage]
        if (data.role === 'user' && (data as { message_id?: string }).message_id) {
          nextTick(() => scrollToMessage(String((data as { message_id?: string }).message_id || '')))
        }
      }
      if (data.next_prompt) {
        groupNextPrompt.value = (data.next_prompt as string || '').trim()
      }
      if (extractAutoInvitedNames(data).length) {
        groupSuggestedAddAgentNames.value = []
        emitAgentAdded()
        loadGroupDetail()
      }
      const suggestedNames = resolveSuggestedNamesFromPayload(data)
      if (suggestedNames.length) {
        groupSuggestedAddAgentNames.value = suggestedNames
        clearStreamingPlaceholders()
        patchGroupStreamState(activeSessionId(sessionId), { phase: '等待你确认邀请…' })
      }
    }
  }

  function handleStreamEndEvent(endData: Record<string, unknown>, state: StreamEventState, sessionId = selectedGroupSessionId() || '') {
    if (sessionId && selectedGroupSessionId() !== sessionId) return
    applyOrchestrationEndMeta(endData)
    if (endData.waiting_for_user) {
      groupTurnLimitReached.value = !!endData.turns_limit_reached
      groupWaitingForUser.value = !!endData.turns_limit_reached
      groupSuggestedNextSpeaker.value = endData.suggested_next_speaker != null
        ? String(endData.suggested_next_speaker)
        : null
      if (extractAutoInvitedNames(endData).length) {
        groupSuggestedAddAgentNames.value = []
        emitAgentAdded()
        loadGroupDetail()
      }
      const suggestedNames = resolveSuggestedNamesFromPayload(endData)
      if (suggestedNames.length) {
        groupSuggestedAddAgentNames.value = suggestedNames
        clearStreamingPlaceholders()
        patchGroupStreamState(activeSessionId(sessionId), { phase: '等待你确认邀请…' })
      }
      if (endData.next_prompt) {
        groupNextPrompt.value = String(endData.next_prompt || '').trim()
      }
      if (endData.suggested_next_speaker === 'user' || endData.discussion_ended) {
        clearAttachedFiles()
      }
      if (groupTurnLimitReached.value) {
        void appAlert({
          title: '已自动暂停',
          message: '本次任务中专家已连续运行 32 轮。\n\n如需继续，请检查并必要时编辑「下一专家提示词」，然后点击「确认并继续」。',
          variant: 'warning',
        })
      }
      if (!endData.turns_limit_reached) {
        const suggestedNext = endData.suggested_next_speaker
        if (suggestedNext && suggestedNext !== 'user') {
          nextTick(() => confirmGroupNext(String(suggestedNext)))
        }
      }
    }
    if (endData.discussion_ended) {
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
