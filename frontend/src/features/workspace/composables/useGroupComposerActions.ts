import { apiRequest } from '@/api/base'
import { appAlert } from '@/composables/useAppDialog'
import type { ComputedRef, Ref } from 'vue'
import { createGroupChatStreamRunner } from './useGroupChatStreamRunner'
import type { AttachedFile } from './useGroupFileReferences'
import type { GroupDetail } from './useGroupDetailLoader'
import type { GroupMessage } from './useGroupMessageList'
import {
  buildGroupDraftMessage,
  createMessageId,
} from './groupMessageDraft'
import { currentStorageTimestamp } from '../messageTimeFormat'

type LastSentDraft = {
  goal: string
  targetAgentName: string | null
  files: AttachedFile[]
}

type StreamState = {
  sawExpertAssistantMessageThisRun: boolean
  sawPersistedFailureMessage: boolean
}
type StreamContent = { text?: string; agent_name?: string; phase?: string; skill?: string }
type StreamRoute = { agent_name?: string; skill?: string }

const RESOURCE_WORKFLOW_AGENT_NAMES = new Set(['资源发布专家', '资源管理专家'])
const RESOURCE_MANAGER_AGENT_NAME = '资源管理专家'
// Keep publishable bodies below the expert-history clipping boundary.
const PASTE_TO_WORKSPACE_THRESHOLD = 1024
const RESOURCE_COMMAND_WINDOW = 512
const STAGED_RESOURCE_REQUEST_LIMIT = 140

function resourceCommandText(message: string): string {
  if (message.length <= RESOURCE_COMMAND_WINDOW * 2) return message
  return `${message.slice(0, RESOURCE_COMMAND_WINDOW)}\n${message.slice(-RESOURCE_COMMAND_WINDOW)}`
}

function stagedResourceRequestSummary(message: string): string {
  const command = resourceCommandText(message).replace(/\s+/g, ' ').trim()
  if (command.length <= STAGED_RESOURCE_REQUEST_LIMIT) return command

  const tailLength = 48
  const headLength = STAGED_RESOURCE_REQUEST_LIMIT - tailLength - 3
  return `${command.slice(0, headLength).trimEnd()} … ${command.slice(-tailLength).trimStart()}`
}

function stagedResourcePasteMessage(message: string): string {
  return `完整内容已暂存为附带 Markdown 文件。用户原始请求摘要：${stagedResourceRequestSummary(message)}`
}

function shouldStageResourceWorkflowPaste(detail: GroupDetail, message: string, attachmentCount: number): boolean {
  if (attachmentCount > 0 || message.length <= PASTE_TO_WORKSPACE_THRESHOLD) return false
  const agentNames = detail.agent_names || []
  if (!agentNames.some((name) => RESOURCE_WORKFLOW_AGENT_NAMES.has(name))) return false
  const actionPattern = agentNames.includes(RESOURCE_MANAGER_AGENT_NAME)
    ? /发布|共享|上传|保存|公开/
    : /发布|共享|上传|公开/
  return actionPattern.test(resourceCommandText(message))
}

async function stageResourcePublisherPaste(workspaceId: string, content: string): Promise<{ path: string; name: string }> {
  const name = `pasted-markdown-${Date.now()}.md`
  const response = await apiRequest(`/sessions/${encodeURIComponent(workspaceId)}/workspace/files`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ filename: name, content }),
  })
  const payload = await response.json().catch(() => null)
  if (!response.ok || payload?.status !== 'ok') {
    throw new Error(String(payload?.detail || `长文本暂存失败 (${response.status})`))
  }
  const path = String(payload?.data?.path || '').trim()
  if (!path) throw new Error('长文本暂存失败：服务未返回工作区路径。')
  return { path, name: path.split('/').pop() || name }
}

export function useGroupComposerActions(args: {
  selectedGroupSessionId: () => string | null
  groupDetail: Ref<GroupDetail | null>
  groupDisplayMessages: Ref<GroupMessage[]>
  groupDiscussionGoal: Ref<string | null>
  groupTargetAgentName: Ref<string | null>
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
    setStreamingPhase: (phase, sessionId) => {
      args.patchGroupStreamState(sessionId || args.selectedGroupSessionId() || '', { phase })
    },
    appendHostError: (content) => {
      const createdAt = currentStorageTimestamp()
      args.groupDisplayMessages.value = [
        ...args.groupDisplayMessages.value,
        { message_id: `msg-${Date.now()}`, speaker: { type: 'host', agent_name: '系统主持人' }, message: { content }, created_at: createdAt } as GroupMessage,
      ]
    },
    updateAutoSwitchHint: args.updateAutoSwitchHint,
    showStreamingRoutePlaceholder: args.showStreamingRoutePlaceholder,
    consumeStreamingStatusContent: args.consumeStreamingStatusContent,
    handleStreamMessageEvent: args.handleStreamMessageEvent,
    handleStreamEndEvent: args.handleStreamEndEvent,
  })

  function builtMessage(): string {
    return buildGroupDraftMessage(args.groupDiscussionGoal.value || '')
  }

  function requestAttachments(): Array<{ type: 'workspace_file'; path: string; name?: string }> {
    return (args.attachedFiles.value || []).map((file) => ({
      type: 'workspace_file',
      path: file.path,
      name: file.name,
    }))
  }

  function requestTargetAgentName(nextSpeaker = ''): string | null {
    const selected = String(args.groupTargetAgentName.value || '').trim()
    if (selected) return selected
    const next = String(nextSpeaker || '').trim()
    return next && next !== 'host' ? next : null
  }

  async function confirmGroupNext(nextSpeaker: string) {
    const detail = args.groupDetail.value
    const id = detail?.id
    if (!detail || !id || args.groupStreaming.value) return
    args.clearAutoSwitchHint()
    args.groupWaitingForUser.value = false
    args.groupSuggestedNextSpeaker.value = null
    const { runToken, abort } = args.beginGroupStream(id, 'routing')
    const body: {
      message_id: string
      message?: string
      attachments?: Array<{ type: 'workspace_file'; path: string; name?: string }>
      target_agent_name?: string
    } = { message_id: createMessageId() }
    const base = builtMessage()
    const targetAgentName = requestTargetAgentName(nextSpeaker)
    args.lastSentDraft.value = {
      goal: String(args.groupDiscussionGoal.value || ''),
      targetAgentName,
      files: [...(args.attachedFiles.value || [])],
    }
    const hasFiles = args.attachedFiles.value.length > 0
    try {
      const msg = base
      if (msg) body.message = msg
      if (hasFiles) body.attachments = requestAttachments()
      if (targetAgentName) body.target_agent_name = targetAgentName
      args.groupTargetAgentName.value = null
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
    const targetAgentName = requestTargetAgentName()
    if (!detail || args.groupStreaming.value || (!base && !hasFiles && !targetAgentName)) return
    args.clearAutoSwitchHint()
    let msg = base
    let attachments = requestAttachments()
    try {
      if (shouldStageResourceWorkflowPaste(detail, base, attachments.length)) {
        const staged = await stageResourcePublisherPaste(detail.id, base)
        attachments = [...attachments, { type: 'workspace_file', path: staged.path, name: staged.name }]
        msg = stagedResourcePasteMessage(base)
      }
    } catch (error) {
      console.error('暂存长文本失败', error)
      await appAlert({
        title: '发送失败',
        message: error instanceof Error ? error.message : '长文本暂存失败，请稍后重试。',
        variant: 'danger',
      })
      return
    }
    args.lastSentDraft.value = {
      goal: String(args.groupDiscussionGoal.value || ''),
      targetAgentName,
      files: attachments.map((file) => ({ path: file.path, name: file.name })),
    }
    args.groupDiscussionGoal.value = ''
    args.groupTargetAgentName.value = null
    const { runToken, abort } = args.beginGroupStream(detail.id, 'routing')
    try {
      const messageId = createMessageId()
      const createdAt = currentStorageTimestamp()
      const messageBody: GroupMessage['message'] = { content: msg }
      if (attachments.length) messageBody.attachments = attachments
      if (targetAgentName) messageBody.target_agent_name = targetAgentName
      const userMsg: GroupMessage = {
        message_id: messageId,
        speaker: { type: 'user' },
        message: messageBody,
        created_at: createdAt,
      } as GroupMessage
      args.groupDisplayMessages.value = [...args.groupDisplayMessages.value, userMsg]
      args.scrollGroupToBottom()
      const body: {
        message_id: string
        message?: string
        attachments?: Array<{ type: 'workspace_file'; path: string; name?: string }>
        target_agent_name?: string
      } = {
        message_id: messageId,
        message: msg,
      }
      if (attachments.length) body.attachments = attachments
      if (targetAgentName) body.target_agent_name = targetAgentName
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
