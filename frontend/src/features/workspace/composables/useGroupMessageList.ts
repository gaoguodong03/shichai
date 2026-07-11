import { nextTick, onBeforeUnmount, ref, watch, type Ref } from 'vue'
import MarkdownIt from 'markdown-it'
import { apiRequest } from '@/api/base'
import { fetchMessageExecutionLogs, type MessageExecutionLogSummary } from '@/api/chat'
import { appAlert, appConfirm, appPrompt } from '@/composables/useAppDialog'
import { useAuthenticatedMessageImages } from './useAuthenticatedMessageImages'
import {
  agentBodyContent,
  renderMarkdownHtml,
  renderSnippetMarkdownHtml,
} from '../workspaceMessageUtils'
import { formatGroupMsgFullTime, formatGroupMsgTime } from '../messageTimeFormat'

export type GroupMessage = {
  message_id?: string
  speaker: {
    type: 'user' | 'host' | 'expert'
    agent_name?: string
    skill?: string
  }
  message?: {
    content?: string
    attachments?: Array<{ type: 'workspace_file'; path: string; name?: string }>
    target_agent_name?: string | null
  }
  created_at?: string
  _streaming?: boolean
  _streamingStatus?: boolean
}

type GroupMessageDetail = {
  id?: string
  messages?: GroupMessage[]
  agent_map?: Record<string, { name?: string }>
}

type MsgExt = {
  speaker?: { type?: string; agent_name?: string; skill?: string }
  created_at?: string
  message?: {
    content?: string
    attachments?: Array<{ type?: string; path?: string; name?: string }>
  }
}

export function useGroupMessageList(args: {
  groupDetail: Ref<GroupMessageDetail | null>
  showGroupWorkspace: Ref<boolean>
  loadGroupWorkspace: () => Promise<void> | void
  loadGroupDetail: () => Promise<void> | void
  onSessionForked: (sessionId: string) => void | Promise<void>
  onSessionRolledBack: () => void | Promise<void>
}) {
  const {
    groupDetail,
    showGroupWorkspace,
    loadGroupWorkspace,
    loadGroupDetail,
    onSessionForked,
    onSessionRolledBack,
  } = args

  const groupMessagesRef = ref<HTMLElement | null>(null)
  const groupDisplayMessages = ref<GroupMessage[]>([])
  const mdRef = ref<{ render: (s: string) => string } | null>(new MarkdownIt({ breaks: true }))
  const { scheduleHydrateAuthImages } = useAuthenticatedMessageImages(groupMessagesRef)
  let renderedSessionId = ''

  type SessionCheckpoint = {
    checkpoint_id: string
    last_message_id?: string
    created_at?: string
    trigger?: string
  }

  const sessionCheckpoints = ref<SessionCheckpoint[]>([])
  const sessionCheckpointsLoading = ref(false)
  const messageStateActionKey = ref('')
  const copiedMessageActionKey = ref('')
  const messageExecutionLogs = ref<Record<string, MessageExecutionLogSummary[]>>({})
  const messageExecutionLogsLoading = ref<Record<string, boolean>>({})
  const expandedExecutionLogMessageId = ref('')
  const expandedExecutionLogKey = ref('')
  let checkpointFetchSeq = 0
  let copiedMessageTimer: ReturnType<typeof window.setTimeout> | null = null

  async function loadSessionCheckpoints() {
    const id = (groupDetail.value?.id || '').trim()
    if (!id) {
      sessionCheckpoints.value = []
      return
    }
    const seq = ++checkpointFetchSeq
    sessionCheckpointsLoading.value = true
    try {
      const response = await apiRequest(`/sessions/${encodeURIComponent(id)}/snapshots`)
      const payload = await response.json().catch(() => null)
      if (seq !== checkpointFetchSeq) return
      sessionCheckpoints.value = response.ok && payload?.status === 'ok' && Array.isArray(payload?.data?.checkpoints)
        ? payload.data.checkpoints
        : []
    } catch {
      if (seq === checkpointFetchSeq) sessionCheckpoints.value = []
    } finally {
      if (seq === checkpointFetchSeq) sessionCheckpointsLoading.value = false
    }
  }

  function resolveCheckpointForMessage(msg: GroupMessage): string | null {
    const checkpoints = sessionCheckpoints.value
    if (!checkpoints.length) return null

    const messageId = (msg.message_id || '').trim()
    if (messageId) {
      let byLastMessageId: string | null = null
      for (const cp of checkpoints) {
        if (cp.last_message_id === messageId) byLastMessageId = cp.checkpoint_id
      }
      if (byLastMessageId) return byLastMessageId
    }
    return null
  }

  function canMessageStateAction(msg: GroupMessage, displayIndex?: number): boolean {
    void displayIndex
    if ((msg as GroupMessage)._streaming) return false
    if (messageStateActionKey.value) return false
    if (sessionCheckpointsLoading.value) return false
    return Boolean((msg.message_id || '').trim())
  }

  function messageStateActionBusy(msg: GroupMessage): boolean {
    const key = msg.message_id || ''
    return Boolean(key && messageStateActionKey.value === key)
  }

  async function forkMessageState(msg: GroupMessage, displayIndex?: number) {
    const sessionId = (groupDetail.value?.id || '').trim()
    const messageId = (msg.message_id || '').trim()
    void displayIndex
    const checkpointId = resolveCheckpointForMessage(msg)
    if (!sessionId || !messageId || messageStateActionKey.value) return
    const ok = await appConfirm({
      title: '分叉会话',
      message: '将此刻的工作区和聊天状态复制成一个新的会话分支。',
      confirmText: '分叉',
      variant: 'info',
    })
    if (!ok) return
    messageStateActionKey.value = messageId
    try {
      const response = await apiRequest(`/sessions/${encodeURIComponent(sessionId)}/clone`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          checkpoint_id: checkpointId || undefined,
          message_id: messageId,
        }),
      })
      const payload = await response.json().catch(() => null)
      if (!response.ok || payload?.status !== 'ok' || !payload?.data?.session_id) {
        await appAlert({ title: '分叉失败', message: payload?.detail || '分叉失败', variant: 'danger' })
        return
      }
      await onSessionForked(String(payload.data.session_id))
    } catch {
      await appAlert({ title: '分叉失败', message: '分叉失败，请检查网络', variant: 'danger' })
    } finally {
      messageStateActionKey.value = ''
    }
  }

  async function rollbackMessageState(msg: GroupMessage, displayIndex?: number) {
    const sessionId = (groupDetail.value?.id || '').trim()
    const messageId = (msg.message_id || '').trim()
    if (!sessionId || messageStateActionKey.value) return
    if (!messageId) return
    const ok = await appConfirm({
      title: '回溯会话',
      message: '确定回溯到该条发言对应的状态吗？此后的状态将被删除。',
      confirmText: '回溯',
      variant: 'warning',
    })
    if (!ok) return
    messageStateActionKey.value = messageId || `idx-${displayIndex ?? -1}`
    try {
      const response = await apiRequest(`/sessions/${encodeURIComponent(sessionId)}/rollback`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message_id: messageId || undefined,
        }),
      })
      const payload = await response.json().catch(() => null)
      if (!response.ok || payload?.status !== 'ok') {
        await appAlert({ title: '回溯失败', message: payload?.detail || '回溯失败', variant: 'danger' })
        return
      }
      await onSessionRolledBack()
      const messages = groupDetail.value?.messages
      groupDisplayMessages.value = Array.isArray(messages) ? messages.map(toDisplayMessage) : []
      await loadSessionCheckpoints()
    } catch {
      await appAlert({ title: '回溯失败', message: '回溯失败，请检查网络', variant: 'danger' })
    } finally {
      messageStateActionKey.value = ''
    }
  }

  function renderMarkdown(text: string) {
    return renderMarkdownHtml(mdRef.value, text)
  }

  function renderSnippetMarkdown(text: string): string {
    return renderSnippetMarkdownHtml(renderMarkdown(text))
  }

  function isShortSingleLine(text: string): string | null {
    const trimmed = (text || '').trim()
    if (!trimmed || trimmed.includes('\n')) return null
    return trimmed.length <= 12 ? 'group-chat-plain-text-nowrap' : null
  }

  function userAttachmentNames(msg: MsgExt): string[] {
    const attachments = Array.isArray(msg?.message?.attachments) ? msg.message.attachments : []
    const names = attachments
      .map((item) => String(item?.name || item?.path || '').trim())
      .filter(Boolean)
    return [...new Set(names)]
  }

  function messageActionContent(msg: MsgExt): string {
    const content = messageContent(msg)
    return messageSpeakerType(msg) === 'user' ? content : agentBodyContent(content)
  }

  function messageCopyActionKey(msg: MsgExt): string {
    const messageId = typeof (msg as { message_id?: unknown }).message_id === 'string'
      ? (msg as { message_id?: string }).message_id
      : ''
    return messageId || `${messageSpeakerType(msg) || 'message'}:${messageActionContent(msg)}`
  }

  function markMessageCopied(msg: MsgExt) {
    copiedMessageActionKey.value = messageCopyActionKey(msg)
    if (copiedMessageTimer) window.clearTimeout(copiedMessageTimer)
    copiedMessageTimer = window.setTimeout(() => {
      if (copiedMessageActionKey.value === messageCopyActionKey(msg)) copiedMessageActionKey.value = ''
      copiedMessageTimer = null
    }, 1600)
  }

  function isMessageCopied(msg: MsgExt) {
    return copiedMessageActionKey.value === messageCopyActionKey(msg)
  }

  function defaultAgentFilename(msg: MsgExt): string {
    const agentName = messageAgentName(msg)
    const name = messageSpeakerType(msg) === 'user'
      ? 'user'
      : ((groupDetail.value?.agent_map || {})[agentName || '']?.name || 'agent')
    const ts = new Date().toISOString().slice(0, 19).replace('T', '').replace(/[-:]/g, '').slice(0, 12)
    return `agent-${name}-${ts}.md`
  }

  async function saveAgentMessageToFile(msg: MsgExt) {
    const id = groupDetail.value?.id
    const content = messageActionContent(msg).trim()
    if (!id || !content) return
    const defaultName = defaultAgentFilename(msg)
    const promptValue = await appPrompt({
      title: '保存为工作区文件',
      message: '请输入文件名。',
      defaultValue: defaultName,
      required: true,
    })
    if (promptValue === null) return
    const filename = promptValue.trim() || defaultName
    if (!filename) return
    try {
      const response = await apiRequest(`/sessions/${encodeURIComponent(id)}/workspace/files`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filename, content }),
      })
      const payload = await response.json().catch(() => null)
      if (response.ok && payload?.status === 'ok') {
        showGroupWorkspace.value = true
        await loadGroupWorkspace()
      } else {
        await appAlert({ title: '保存失败', message: payload?.detail || '保存失败', variant: 'danger' })
      }
    } catch {
      await appAlert({ title: '保存失败', message: '保存失败', variant: 'danger' })
    }
  }

  async function copyAgentMessageToClipboard(msg: MsgExt) {
    const content = messageActionContent(msg)
    if (!content) return
    try {
      await navigator.clipboard.writeText(content)
      markMessageCopied(msg)
    } catch {
      await appAlert({ title: '复制失败', message: '复制失败，请检查浏览器剪贴板权限', variant: 'danger' })
    }
  }

  onBeforeUnmount(() => {
    if (copiedMessageTimer) window.clearTimeout(copiedMessageTimer)
  })

  async function deleteGroupMessage(msg: { message_id?: string }) {
    const id = groupDetail.value?.id
    const messageId = msg?.message_id
    if (!id || !messageId) return
    const ok = await appConfirm({
      title: '删除发言',
      message: '确定从会话中彻底删除该条发言？删除后下一轮专家将不再看到这条内容。',
      variant: 'danger',
      confirmText: '删除',
    })
    if (!ok) return
    try {
      const response = await apiRequest(`/sessions/${encodeURIComponent(id)}/messages/${encodeURIComponent(messageId)}`, {
        method: 'DELETE',
      })
      const payload = await response.json().catch(() => null)
      if (response.ok && payload?.status === 'ok') {
        await loadGroupDetail()
      } else {
        await appAlert({ title: '删除失败', message: payload?.detail || '删除失败', variant: 'danger' })
      }
    } catch {
      await appAlert({ title: '删除失败', message: '删除失败', variant: 'danger' })
    }
  }

  function messageExecutionLogRows(msg: { message_id?: string }) {
    const messageId = String(msg?.message_id || '').trim()
    return messageId ? (messageExecutionLogs.value[messageId] || []) : []
  }

  function canShowMessageExecutionLogs(msg: MsgExt & { message_id?: string }) {
    const type = messageSpeakerType(msg)
    return (type === 'expert' || type === 'host') && Boolean(String(msg?.message_id || '').trim())
  }

  function isMessageExecutionLogsLoading(msg: { message_id?: string }) {
    const messageId = String(msg?.message_id || '').trim()
    return Boolean(messageId && messageExecutionLogsLoading.value[messageId])
  }

  function isMessageExecutionLogsOpen(msg: { message_id?: string }) {
    return expandedExecutionLogMessageId.value === String(msg?.message_id || '').trim()
  }

  function executionLogKey(msg: { message_id?: string }, index: number) {
    return `${String(msg?.message_id || '').trim()}-execution-log-${index}`
  }

  function toggleExecutionLogDetail(msg: { message_id?: string }, index: number) {
    const key = executionLogKey(msg, index)
    expandedExecutionLogKey.value = expandedExecutionLogKey.value === key ? '' : key
  }

  function isExecutionLogDetailOpen(msg: { message_id?: string }, index: number) {
    return expandedExecutionLogKey.value === executionLogKey(msg, index)
  }

  async function toggleMessageExecutionLogs(msg: MsgExt & { message_id?: string }) {
    const sessionId = String(groupDetail.value?.id || '').trim()
    const messageId = String(msg?.message_id || '').trim()
    if (!sessionId || !messageId) return
    if (expandedExecutionLogMessageId.value === messageId) {
      expandedExecutionLogMessageId.value = ''
      expandedExecutionLogKey.value = ''
      return
    }
    expandedExecutionLogMessageId.value = messageId
    expandedExecutionLogKey.value = ''
    if (messageExecutionLogs.value[messageId]) return
    messageExecutionLogsLoading.value = { ...messageExecutionLogsLoading.value, [messageId]: true }
    try {
      const response = await fetchMessageExecutionLogs(sessionId, messageId)
      messageExecutionLogs.value = {
        ...messageExecutionLogs.value,
        [messageId]: Array.isArray(response.data?.logs) ? response.data.logs : [],
      }
    } catch {
      messageExecutionLogs.value = { ...messageExecutionLogs.value, [messageId]: [] }
      await appAlert({ title: '日志加载失败', message: '工具日志加载失败', variant: 'danger' })
    } finally {
      messageExecutionLogsLoading.value = { ...messageExecutionLogsLoading.value, [messageId]: false }
    }
  }

  function scrollGroupToBottom() {
    nextTick(() => {
      const el = groupMessagesRef.value
      if (el) el.scrollTop = el.scrollHeight
    })
  }

  function isNearGroupBottom(threshold = 100): boolean {
    const el = groupMessagesRef.value
    if (!el) return true
    const distance = el.scrollHeight - el.scrollTop - el.clientHeight
    return distance <= threshold
  }

  function scrollGroupToBottomIfNear(threshold = 100) {
    if (!isNearGroupBottom(threshold)) return
    nextTick(() => {
      const el = groupMessagesRef.value
      if (!el) return
      el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
    })
  }

  function scrollGroupRowToLowerMiddle(row: HTMLElement) {
    nextTick(() => {
      const scroller = groupMessagesRef.value
      if (!scroller) return
      const desiredViewportRatio = 0.68
      const desiredTop = row.offsetTop - scroller.clientHeight * desiredViewportRatio + row.clientHeight * 0.5
      const maxTop = Math.max(0, scroller.scrollHeight - scroller.clientHeight)
      const nextTop = Math.max(0, Math.min(desiredTop, maxTop))
      scroller.scrollTo({ top: nextTop, behavior: 'smooth' })
    })
  }

  function scrollLatestAssistantRowToLowerMiddle() {
    nextTick(() => {
      const scroller = groupMessagesRef.value
      if (!scroller) return
      const rows = Array.from(scroller.querySelectorAll('.group-chat-msg-row-other')) as HTMLElement[]
      const last = rows[rows.length - 1]
      if (!last) return
      scrollGroupRowToLowerMiddle(last)
    })
  }

  function scrollGroupAssistantMessageIntoView(data: Record<string, unknown>) {
    const messageId = typeof data.message_id === 'string' ? data.message_id.trim() : ''
    nextTick(() => {
      const scroller = groupMessagesRef.value
      if (!scroller) return
      if (messageId) {
        const el = scroller.querySelector(`[data-message-id="${CSS.escape(messageId)}"]`) as HTMLElement | null
        if (el) {
          scrollGroupRowToLowerMiddle(el)
          return
        }
      }
      scrollLatestAssistantRowToLowerMiddle()
    })
  }

  function messageSpeakerType(msg: MsgExt): string {
    return String(msg?.speaker?.type || '').trim()
  }

  function messageAgentName(msg: MsgExt): string {
    return String(msg?.speaker?.agent_name || '').trim()
  }

  function messageSkill(msg: MsgExt): string {
    return String(msg?.speaker?.skill || '').trim()
  }

  function messageCreatedAt(msg: MsgExt): string {
    return String(msg?.created_at || '').trim()
  }

  function messageContent(msg: MsgExt): string {
    return String(msg?.message?.content ?? '').trim()
  }

  function toDisplayMessage(msg: GroupMessage): GroupMessage {
    return {
      ...msg,
      message: {
        ...(msg.message || {}),
        content: messageContent(msg),
      },
    }
  }

  watch(
    () => groupDetail.value?.id,
    (sessionId) => {
      if (sessionId) loadSessionCheckpoints()
      else sessionCheckpoints.value = []
    },
    { immediate: true },
  )

  watch(
    () => groupDetail.value?.messages?.length,
    (len, prev) => {
      if (len !== prev && groupDetail.value?.id) loadSessionCheckpoints()
    },
  )

  watch(
    () => [groupDetail.value?.id, groupDetail.value?.messages] as const,
    ([sessionId, messages]) => {
      const nextSessionId = String(sessionId || '')
      const sessionChanged = nextSessionId !== renderedSessionId
      renderedSessionId = nextSessionId
      const shouldFollow = sessionChanged || isNearGroupBottom()
      const nextMessages = Array.isArray(messages) ? messages.map(toDisplayMessage) : []
      groupDisplayMessages.value = nextMessages
      nextTick(() => {
        scheduleHydrateAuthImages()
        if (sessionChanged) {
          scrollGroupToBottom()
        } else if (shouldFollow) {
          scrollGroupToBottomIfNear()
        }
      })
    },
    { immediate: true },
  )

  return {
    groupMessagesRef,
    groupDisplayMessages,
    scheduleHydrateAuthImages,
    renderMarkdown,
    renderSnippetMarkdown,
    messageSpeakerType,
    messageAgentName,
    messageSkill,
    messageCreatedAt,
    messageContent,
    isShortSingleLine,
    userAttachmentNames,
    formatGroupMsgTime,
    formatGroupMsgFullTime,
    saveAgentMessageToFile,
    copyAgentMessageToClipboard,
    isMessageCopied,
    deleteGroupMessage,
    messageExecutionLogs,
    messageExecutionLogRows,
    canShowMessageExecutionLogs,
    isMessageExecutionLogsLoading,
    isMessageExecutionLogsOpen,
    expandedExecutionLogKey,
    executionLogKey,
    toggleExecutionLogDetail,
    isExecutionLogDetailOpen,
    toggleMessageExecutionLogs,
    forkMessageState,
    rollbackMessageState,
    canMessageStateAction,
    messageStateActionBusy,
    scrollGroupToBottom,
    isNearGroupBottom,
    scrollLatestAssistantRowToLowerMiddle,
    scrollGroupAssistantMessageIntoView,
  }
}
