import { nextTick, ref, watch, type Ref } from 'vue'
import MarkdownIt from 'markdown-it'
import { apiRequest } from '@/api/base'
import { appAlert, appConfirm, appPrompt } from '@/composables/useAppDialog'
import { useAuthenticatedMessageImages } from './useAuthenticatedMessageImages'
import {
  agentBodyContent,
  renderMarkdownHtml,
  renderSnippetMarkdownHtml,
} from '../workspaceMessageUtils'

export type GroupMessage = {
  message_id?: string
  role: string
  agent_id?: string
  content: string
  _streaming?: boolean
  [key: string]: unknown
}

type GroupMessageDetail = {
  id?: string
  messages?: GroupMessage[]
  agent_map?: Record<string, { name?: string }>
}

type MsgExt = {
  timestamp?: string
  event_type?: string
  agent_id?: string
  content?: string
}

export function useGroupMessageList(args: {
  groupDetail: Ref<GroupMessageDetail | null>
  showGroupWorkspace: Ref<boolean>
  loadGroupWorkspace: () => Promise<void> | void
  loadGroupDetail: () => Promise<void> | void
}) {
  const { groupDetail, showGroupWorkspace, loadGroupWorkspace, loadGroupDetail } = args

  const groupMessagesRef = ref<HTMLElement | null>(null)
  const groupDisplayMessages = ref<GroupMessage[]>([])
  const mdRef = ref<{ render: (s: string) => string } | null>(new MarkdownIt({ breaks: true }))
  const { scheduleHydrateAuthImages } = useAuthenticatedMessageImages(groupMessagesRef)
  let renderedSessionId = ''

  function renderMarkdown(text: string) {
    return renderMarkdownHtml(mdRef.value, text)
  }

  function renderSnippetMarkdown(text: string): string {
    return renderSnippetMarkdownHtml(renderMarkdown(text))
  }

  function stripDiscussionGoalForDisplay(content: string): string {
    const raw = (content ?? '').trim()
    if (!raw) return ''
    const fileRefMatches = Array.from(raw.matchAll(/【文件引用：([^】]+)】/g))
    const fileExpandedBlockRegex = /(?:^|\n)\[文件:\s*[^\]]+\][\s\S]*?(?=\n【文件引用：|\n【给下一 (?:Agent|DHA) 的提示】|$)/g
    const prefix = '【讨论目标】'
    const withoutGoalPrefix = raw.startsWith(prefix)
      ? raw.slice(prefix.length).replace(/^\s*\n?/, '').trim()
      : raw
    const cleaned = withoutGoalPrefix
      .replace(/(?:^|\n{2,})【给下一 (?:Agent|DHA) 的提示】[\s\S]*?(?=\n{2,}【文件引用：|$)/g, '')
      .replace(/(?:^|\n)【文件引用：[^】]+】/g, '')
      .replace(/(?:^|\n)【文件内容已解析】/g, '')
      .replace(fileExpandedBlockRegex, '')
      .replace(/\n{3,}/g, '\n\n')
      .replace(/^\s+|\s+$/g, '')
    if (!cleaned && fileRefMatches.length) {
      const refs = fileRefMatches
        .map((match) => {
          const payload = String(match[1] || '').trim()
          if (!payload) return ''
          const parts = payload.split('｜').map((item) => item.trim()).filter(Boolean)
          const path = parts.length >= 2 ? parts[1] : parts[0]
          return path ? `【文件引用：${path}】` : ''
        })
        .filter(Boolean)
      if (refs.length) return refs.join('\n')
    }
    return cleaned
  }

  function formatUserBubbleForDisplay(content: string): string {
    let text = stripDiscussionGoalForDisplay(content || '')
    text = text.replace(/\n{3,}/g, '\n\n')
    return text.trimEnd()
  }

  function isShortSingleLine(text: string): string | null {
    const trimmed = (text || '').trim()
    if (!trimmed || trimmed.includes('\n')) return null
    return trimmed.length <= 12 ? 'group-chat-plain-text-nowrap' : null
  }

  function extractUserFileReferenceNames(content: string): string[] {
    if (!content) return []
    const matches = Array.from(String(content).matchAll(/【文件引用：([^】]+)】/g))
    const names = matches
      .map((match) => {
        const payload = String(match?.[1] || '').trim()
        if (!payload) return ''
        const parts = payload.split('｜').map((item) => item.trim()).filter(Boolean)
        if (!parts.length) return ''
        return parts[0] || parts[parts.length - 1] || ''
      })
      .filter(Boolean)
    return [...new Set(names)]
  }

  function formatGroupMsgTime(ts?: string) {
    if (!ts) return ''
    try {
      const date = new Date(ts)
      return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
    } catch {
      return ts
    }
  }

  function defaultAgentFilename(msg: MsgExt): string {
    const name = (groupDetail.value?.agent_map || {})[msg.agent_id || '']?.name || 'agent'
    const ts = new Date().toISOString().slice(0, 19).replace('T', '').replace(/[-:]/g, '').slice(0, 12)
    return `agent-${name}-${ts}.md`
  }

  async function saveAgentMessageToFile(msg: MsgExt) {
    const id = groupDetail.value?.id
    const content = (msg.content || '').trim()
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
      const response = await apiRequest(`/workspaces/${encodeURIComponent(id)}/files`, {
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
    const content = agentBodyContent(msg.content || '')
    if (!content) return
    try {
      await navigator.clipboard.writeText(content)
    } catch {
      await appAlert({ title: '复制失败', message: '复制失败，请检查浏览器剪贴板权限', variant: 'danger' })
    }
  }

  async function deleteGroupMessage(msg: { message_id?: string; role?: string }) {
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

  function isMemberJoinedMessage(msg: GroupMessage): boolean {
    const eventType = (msg as MsgExt).event_type
    return msg.role === 'host' && (eventType === 'member_joined' || eventType === 'member_left')
  }

  watch(
    () => [groupDetail.value?.id, groupDetail.value?.messages] as const,
    ([sessionId, messages]) => {
      const nextSessionId = String(sessionId || '')
      const sessionChanged = nextSessionId !== renderedSessionId
      renderedSessionId = nextSessionId
      const shouldFollow = sessionChanged || isNearGroupBottom()
      const nextMessages = Array.isArray(messages) ? [...messages] : []
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
    formatUserBubbleForDisplay,
    isShortSingleLine,
    extractUserFileReferenceNames,
    formatGroupMsgTime,
    saveAgentMessageToFile,
    copyAgentMessageToClipboard,
    deleteGroupMessage,
    scrollGroupToBottom,
    isNearGroupBottom,
    scrollLatestAssistantRowToLowerMiddle,
    scrollGroupAssistantMessageIntoView,
    isMemberJoinedMessage,
  }
}
