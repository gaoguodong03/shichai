import { apiRequest } from '@/api/base'
import type { ComputedRef, Ref } from 'vue'
import { createGroupChatStreamRunner } from './useGroupChatStreamRunner'
import type { AttachedFile } from './useGroupFileReferences'
import type { GroupDetail } from './useGroupDetailLoader'
import type { GroupMessage } from './useGroupMessageList'
import {
  buildGroupDraftMessage,
  createClientMessageId,
} from './groupMessageDraft'

type LastSentDraft = {
  goal: string
  nextPrompt: string
  files: AttachedFile[]
}

type StreamState = { sawExpertAssistantMessageThisRun: boolean }
type StreamContent = { text?: string; agent_name?: string; phase?: string; skill?: string }
type StreamRoute = { agent_name?: string; skill?: string }

export function useGroupComposerActions(args: {
  selectedGroupSessionId: () => string | null
  groupDetail: Ref<GroupDetail | null>
  groupDisplayMessages: Ref<GroupMessage[]>
  groupDiscussionGoal: Ref<string | null>
  groupNextPrompt: Ref<string>
  groupStreaming: ComputedRef<boolean>
  groupWaitingForUser: Ref<boolean>
  groupSuggestedNextSpeaker: Ref<string | null>
  attachedFiles: Ref<AttachedFile[]>
  effectiveHostDisplayName: ComputedRef<string>
  defaultHostDisplayName: string
  lastSentDraft: Ref<LastSentDraft | null>
  beginGroupStream: (sessionId: string, phase: string) => { runToken: number; abort: AbortController }
  isCurrentGroupRun: (sessionId: string, runToken: number) => boolean
  finishGroupStream: (sessionId: string, runToken: number, phase?: string) => void
  abortGroupStream: (sessionId: string) => void
  patchGroupStreamState: (sessionId: string, patch: Record<string, unknown>) => void
  updateAutoSwitchHint: (payload: Record<string, unknown>, sessionId: string) => void
  showStreamingRoutePlaceholder: (payload: StreamRoute, sessionId: string) => void
  consumeStreamingStatusContent: (data: StreamContent, sessionId: string) => boolean
  appendStreamingContent: (agentName: string, text: string) => void
  handleStreamMessageEvent: (data: Record<string, unknown>, state: StreamState, sessionId: string) => void
  handleStreamEndEvent: (data: Record<string, unknown>, state: StreamState, sessionId: string) => void
  clearAutoSwitchHint: () => void
  clearStreamingPlaceholders: () => void
  scrollGroupToBottom: () => void
  refreshGroupWorkspaceAfterExternalChange: () => Promise<unknown>
  emitMessageSent: () => void
}) {
  const runGroupStream = createGroupChatStreamRunner({
    isSelectedSession: (sessionId) => args.selectedGroupSessionId() === sessionId,
    setStreamingPhase: (text, sessionId) => {
      args.patchGroupStreamState(sessionId || args.selectedGroupSessionId() || '', { phase: text })
    },
    appendHostError: (content) => {
      args.groupDisplayMessages.value = [
        ...args.groupDisplayMessages.value,
        { message_id: `msg-${Date.now()}`, speaker: { type: 'host' }, message: { content } } as GroupMessage,
      ]
    },
    updateAutoSwitchHint: args.updateAutoSwitchHint,
    showStreamingRoutePlaceholder: args.showStreamingRoutePlaceholder,
    consumeStreamingStatusContent: args.consumeStreamingStatusContent,
    appendStreamingContent: args.appendStreamingContent,
    handleStreamMessageEvent: args.handleStreamMessageEvent,
    handleStreamEndEvent: args.handleStreamEndEvent,
  })

  function builtMessage(): string {
    return buildGroupDraftMessage(args.groupDiscussionGoal.value || '', args.groupNextPrompt.value || '')
  }

  function requestAttachments(): Array<{ type: 'workspace_file'; path: string; name?: string }> {
    return (args.attachedFiles.value || []).map((file) => ({
      type: 'workspace_file',
      path: file.path,
      name: file.name,
    }))
  }

  async function confirmGroupNext(_nextSpeaker: string) {
    const detail = args.groupDetail.value
    const id = detail?.id
    if (!detail || !id || args.groupStreaming.value) return
    args.clearAutoSwitchHint()
    args.groupWaitingForUser.value = false
    args.groupSuggestedNextSpeaker.value = null
    const { runToken, abort } = args.beginGroupStream(id, '正在确认…')
    const body: {
      message?: string
      client_message_id: string
      attachments?: Array<{ type: 'workspace_file'; path: string; name?: string }>
    } = { client_message_id: createClientMessageId() }
    const base = builtMessage()
    args.lastSentDraft.value = {
      goal: String(args.groupDiscussionGoal.value || ''),
      nextPrompt: String(args.groupNextPrompt.value || ''),
      files: [...(args.attachedFiles.value || [])],
    }
    const hasFiles = args.attachedFiles.value.length > 0
    try {
      const msg = base
      if (msg) body.message = msg
      if (hasFiles) body.attachments = requestAttachments()
      const shouldEmitMessageSent = await runGroupStream(id, body, abort.signal)
      if (shouldEmitMessageSent) {
        await args.refreshGroupWorkspaceAfterExternalChange()
        args.emitMessageSent()
      }
    } catch (e) {
      console.error('确认下一发言人失败', e)
    } finally {
      if (args.isCurrentGroupRun(id, runToken)) {
        args.clearStreamingPlaceholders()
        args.finishGroupStream(id, runToken)
      }
    }
  }

  async function sendGroupMessage() {
    const detail = args.groupDetail.value
    if (!detail) return
    const base = builtMessage()
    const hasFiles = args.attachedFiles.value.length > 0
    if (!detail || args.groupStreaming.value || (!base && !hasFiles)) return
    args.clearAutoSwitchHint()
    args.lastSentDraft.value = {
      goal: String(args.groupDiscussionGoal.value || ''),
      nextPrompt: String(args.groupNextPrompt.value || ''),
      files: [...(args.attachedFiles.value || [])],
    }
    args.groupDiscussionGoal.value = ''
    args.groupNextPrompt.value = ''
    const { runToken, abort } = args.beginGroupStream(detail.id, '正在分配专家…')
    try {
      const msg = base
      const clientMessageId = createClientMessageId()
      const attachments = requestAttachments()
      const userMsg: GroupMessage = {
        message_id: `msg-${Date.now()}`,
        speaker: { type: 'user' },
        message: { content: msg, attachments },
        client_message_id: clientMessageId,
      } as GroupMessage
      args.groupDisplayMessages.value = [...args.groupDisplayMessages.value, userMsg]
      args.scrollGroupToBottom()
      const body: {
        message?: string
        client_message_id: string
        attachments?: Array<{ type: 'workspace_file'; path: string; name?: string }>
      } = {
        message: msg,
        client_message_id: clientMessageId,
      }
      if (attachments.length) body.attachments = attachments
      const shouldEmitMessageSent = await runGroupStream(detail.id, body, abort.signal)
      if (shouldEmitMessageSent) {
        await args.refreshGroupWorkspaceAfterExternalChange()
        args.emitMessageSent()
      }
    } catch (e) {
      console.error('群聊发送失败', e)
    } finally {
      if (args.isCurrentGroupRun(detail.id, runToken)) {
        args.clearStreamingPlaceholders()
        args.finishGroupStream(detail.id, runToken)
      }
    }
  }

  async function stopGroupStream() {
    const id = args.selectedGroupSessionId() || ''
    if (!id) return
    args.abortGroupStream(id)
    try {
      await apiRequest(`/sessions/${encodeURIComponent(id)}/chat/stop`, { method: 'POST' })
    } catch {
      // UI has already stopped locally; the next request will resync backend state.
    }
    args.clearStreamingPlaceholders()
  }

  return {
    confirmGroupNext,
    sendGroupMessage,
    stopGroupStream,
  }
}
