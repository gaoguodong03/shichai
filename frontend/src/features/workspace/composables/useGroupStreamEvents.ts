import { nextTick, type Ref } from 'vue'
import { appAlert } from '@/composables/useAppDialog'
import type { GroupMessage } from './useGroupMessageList'

type StreamEventState = {
  sawExpertAssistantMessageThisRun: boolean
}

type StreamStatusPayload = {
  text?: string
  agent_id?: string
  meta?: { phase?: string }
}

export function useGroupStreamEvents(args: {
  selectedGroupSessionId: () => string | null
  groupDisplayMessages: Ref<GroupMessage[]>
  groupNextPrompt: Ref<string>
  groupTurnLimitReached: Ref<boolean>
  groupWaitingForUser: Ref<boolean>
  groupSuggestedNextSpeaker: Ref<string | null>
  groupSuggestedAddAgentIds: Ref<string[]>
  patchGroupStreamState: (sessionId: string, patch: Record<string, unknown>) => void
  scheduleHydrateAuthImages: () => void
  scrollLatestAssistantRowToLowerMiddle: () => void
  scrollGroupAssistantMessageIntoView: (data: Record<string, unknown>) => void
  scrollToMessage: (messageId: string) => void
  applyOrchestrationEndMeta: (data: Record<string, unknown>) => void
  extractAutoInvitedIds: (data: Record<string, unknown> | null | undefined) => string[]
  resolveSuggestedIdsFromPayload: (data: Record<string, unknown> | null | undefined) => string[]
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
    groupSuggestedAddAgentIds,
    patchGroupStreamState,
    scheduleHydrateAuthImages,
    scrollLatestAssistantRowToLowerMiddle,
    scrollGroupAssistantMessageIntoView,
    scrollToMessage,
    applyOrchestrationEndMeta,
    extractAutoInvitedIds,
    resolveSuggestedIdsFromPayload,
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

  /** 流式展示：追加一条 content chunk 到当前专家占位消息，或新建占位 */
  function appendStreamingContent(agentId: string, text: string) {
    const list = [...groupDisplayMessages.value]
    const last = list[list.length - 1] as (GroupMessage & { _streaming?: boolean }) | undefined
    const appendToExisting =
      last?.role === 'assistant' && last?.agent_id === agentId && (last as { _streaming?: boolean })._streaming
    if (appendToExisting) {
      const next = [...list.slice(0, -1), { ...last, content: (last.content || '') + text } as GroupMessage]
      groupDisplayMessages.value = next
    } else {
      const cleared = list.map((m) => ((m as GroupMessage)._streaming ? ({ ...(m as GroupMessage), _streaming: false } as GroupMessage) : m))
      groupDisplayMessages.value = [...cleared, { role: 'assistant', agent_id: agentId, content: text, _streaming: true } as unknown as GroupMessage]
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
      last?.agent_id === data.agent_id &&
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
    if (phase === 'file_resolving' || phase === 'preparing') {
      patchGroupStreamState(id, { phase: '正在处理文件引用…' })
      return true
    }
    if (phase === 'file_resolved' || phase === 'file_parsed') {
      patchGroupStreamState(id, { phase: '文件引用已处理' })
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
      if (extractAutoInvitedIds(data).length) {
        groupSuggestedAddAgentIds.value = []
        emitAgentAdded()
        loadGroupDetail()
      }
      const suggestedIds = resolveSuggestedIdsFromPayload(data)
      if (suggestedIds.length) {
        groupSuggestedAddAgentIds.value = suggestedIds
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
      if (extractAutoInvitedIds(endData).length) {
        groupSuggestedAddAgentIds.value = []
        emitAgentAdded()
        loadGroupDetail()
      }
      const suggestedIds = resolveSuggestedIdsFromPayload(endData)
      if (suggestedIds.length) {
        groupSuggestedAddAgentIds.value = suggestedIds
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
    replaceOrPushAssistantMessage,
    clearStreamingPlaceholders,
    consumeStreamingStatusContent,
    handleStreamMessageEvent,
    handleStreamEndEvent,
  }
}
