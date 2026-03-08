<template>
  <div class="workspace-right-content">
    <!-- 单聊 -->
    <div v-if="showSingleChat" class="workspace-right-inner">
      <ChatView
        session-id="single-default"
        session-title="单聊"
      />
    </div>

    <!-- 群聊：内联消息列表+发送+讨论目标/成员/工作区入口 -->
    <div v-else-if="groupDetail" class="workspace-right-inner workspace-group-root">
      <div :key="'group-' + (groupDetail?.id ?? '')" class="workspace-group-wrap flex flex-col min-h-0">
        <header class="workspace-group-header flex-shrink-0 px-4 py-2 bg-card border-b border-border flex items-center justify-between gap-3">
          <span class="text-sm font-medium text-primary truncate min-w-0">群聊：{{ groupDetail.title || '未命名' }}</span>
          <div class="flex items-center gap-2 flex-shrink-0">
            <button
              type="button"
              :class="['px-2.5 py-1.5 text-xs font-medium rounded-lg border transition-colors', showGroupWorkspace ? 'border-accent bg-accent-subtle text-accent-subtle-text' : 'border-input-border text-muted hover:bg-list-hover']"
              @click="showGroupWorkspace = !showGroupWorkspace"
            >
              工作区
            </button>
            <div class="relative">
              <button
                type="button"
                class="px-2.5 py-1.5 text-xs font-medium rounded-lg border border-input-border text-muted hover:bg-list-hover"
                @click="showGroupMembers = !showGroupMembers"
              >
                {{ groupDetail.dha_ids?.length ?? 0 }} 个成员
              </button>
              <div v-if="showGroupMembers" class="absolute right-0 top-full mt-1 py-2 px-3 rounded-lg border border-border bg-card shadow-lg z-10 min-w-[160px]">
                <p class="text-xs text-muted mb-1.5">成员</p>
                <ul class="text-sm text-primary space-y-1">
                  <li v-for="id in (groupDetail.dha_ids || [])" :key="id">{{ (groupDetail.dha_map || {})[id]?.name || id }}</li>
                </ul>
              </div>
            </div>
          </div>
        </header>
        <div class="flex-1 min-h-0 flex overflow-hidden">
          <div class="flex-1 min-h-0 flex flex-col overflow-hidden">
            <div v-if="groupDiscussionGoal !== null" class="flex-shrink-0 px-4 py-2 bg-card border-b border-border space-y-1.5">
              <div>
                <label class="text-xs text-muted block mb-1">讨论目标</label>
                <input
                  v-model="groupDiscussionGoal"
                  type="text"
                  class="w-full rounded border border-input-border bg-input px-3 py-1.5 text-sm text-primary"
                  placeholder="可选：填写本场讨论目标"
                />
              </div>
              <p v-if="groupRecentSummary" class="text-xs text-muted line-clamp-2">{{ groupRecentSummary }}</p>
            </div>
            <div ref="groupMessagesRef" class="flex-1 overflow-y-auto px-4 py-4 space-y-3 text-primary">
              <template v-for="(msg, i) in groupDisplayMessages" :key="msg.message_id || i">
                <div :class="['flex', msg.role === 'user' ? 'justify-end' : 'justify-start']">
                  <div
                    :class="[
                      'max-w-2xl rounded-lg px-3 py-2 text-sm whitespace-pre-wrap break-words',
                      msg.role === 'user'
                        ? 'bg-accent text-accent-contrast'
                        : msg.role === 'host'
                          ? 'bg-list-hover text-muted italic text-center'
                          : 'bg-card border border-border'
                    ]"
                  >
                    <div v-if="msg.role !== 'user' && msg.role !== 'host'" class="mb-1 flex items-center gap-2 flex-wrap">
                      <span class="font-medium text-muted">{{ (groupDetail.dha_map || {})[msg.dha_id || '']?.name }}</span>
                      <span v-if="(msg as { timestamp?: string }).timestamp" class="text-[11px] text-muted">{{ formatGroupMsgTime((msg as { timestamp?: string }).timestamp) }}</span>
                    </div>
                    <span>{{ msg.content || '' }}</span>
                    <details v-if="msg.role === 'host' && (msg as { next_prompt?: string }).next_prompt" class="mt-2 text-xs border border-border rounded bg-list-hover">
                      <summary class="px-2 py-1 cursor-pointer text-muted">下一发言人提示词</summary>
                      <pre class="p-2 m-0 whitespace-pre-wrap break-words text-primary">{{ (msg as { next_prompt?: string }).next_prompt }}</pre>
                    </details>
                  </div>
                </div>
              </template>
              <p v-if="!groupDisplayMessages.length" class="text-muted text-sm">暂无消息，在下方输入并发送。</p>
            </div>
            <div class="flex-shrink-0 p-3 border-t border-border bg-card">
              <p v-if="groupStreaming" class="text-xs text-muted mb-2">{{ groupStreamingPhase }}</p>
              <div class="flex gap-2">
                <textarea
                  v-model="groupInputText"
                  class="flex-1 min-h-[80px] rounded-lg border border-input-border bg-input px-3 py-2 text-primary placeholder-muted resize-y text-sm"
                  placeholder="输入消息… (⌘+Enter 发送)"
                  :disabled="groupStreaming"
                  @keydown.enter.meta="sendGroupMessage"
                />
                <button
                  type="button"
                  class="self-end px-4 py-2 rounded-lg bg-accent text-accent-contrast text-sm font-medium disabled:opacity-50"
                  :disabled="groupStreaming || !groupInputText.trim()"
                  @click="sendGroupMessage"
                >
                  {{ groupStreaming ? '发送中…' : '发送' }}
                </button>
              </div>
            </div>
          </div>
          <div v-if="showGroupWorkspace" class="w-72 flex-shrink-0 border-l border-border bg-card overflow-hidden flex flex-col">
            <div class="p-3 border-b border-border flex items-center justify-between gap-2">
              <p class="text-sm font-medium text-primary truncate min-w-0">工作区</p>
              <button
                v-if="groupWorkspacePath"
                type="button"
                class="text-xs text-accent hover:underline flex-shrink-0"
                @click="groupWorkspacePath = groupWorkspacePath.replace(/\/[^/]+\/?$/, ''); loadGroupWorkspace()"
              >
                上级
              </button>
            </div>
            <div class="flex-1 overflow-y-auto p-2">
              <p v-if="groupWorkspaceLoading" class="text-xs text-muted">加载中…</p>
              <p v-else-if="groupWorkspaceError" class="text-xs text-danger">{{ groupWorkspaceError }}</p>
              <ul v-else class="space-y-0.5">
                <li v-for="e in groupWorkspaceEntries" :key="e.path" class="flex items-center gap-2 text-sm">
                  <span v-if="e.is_dir" class="cursor-pointer text-accent hover:underline truncate min-w-0" @click="groupWorkspacePath = groupWorkspacePath ? groupWorkspacePath + '/' + e.name : e.name; loadGroupWorkspace()">{{ e.name }}/</span>
                  <a v-else :href="groupWorkspaceDownloadUrl(e.path)" target="_blank" rel="noopener" class="text-primary hover:underline truncate min-w-0">{{ e.name }}</a>
                </li>
                <li v-if="!groupWorkspaceEntries.length && !groupWorkspaceLoading" class="text-xs text-muted">空</li>
              </ul>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 有选中 id 但尚未加载出 groupDetail：加载中 / 错误 / 兜底 -->
    <div v-else-if="selectedGroupSessionId" class="workspace-right-inner workspace-group-root">
      <div v-if="groupLoading && !groupDetail" class="workspace-state workspace-state-loading">
        <div class="workspace-state-dots"><span /><span /><span /></div>
        <p class="workspace-state-text">加载会话中…</p>
      </div>
      <div v-else-if="groupError" class="workspace-state workspace-state-error">
        <p class="workspace-state-title">无法加载会话</p>
        <p class="workspace-state-text">{{ groupError }}</p>
        <button type="button" class="workspace-state-btn" @click="loadGroupDetail">重试</button>
      </div>
      <div v-else class="workspace-state workspace-state-loading">
        <div class="workspace-state-dots"><span /><span /><span /></div>
        <p class="workspace-state-text">加载中…</p>
      </div>
    </div>

    <!-- 未选会话：空态 -->
    <div v-else class="workspace-state workspace-state-empty">
      <div class="workspace-empty-icon" aria-hidden="true">
        <svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
          <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
        </svg>
      </div>
      <h2 class="workspace-empty-title">选择会话开始协作</h2>
      <p class="workspace-empty-desc">
        在左侧选择已有会话，或点击「新建会话」创建单聊（0 个 DHA）或群聊（选择 DHA）。
      </p>
      <p class="workspace-empty-hint">
        会话内可使用工作区、邀请 DHA 等能力。
      </p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, nextTick, computed } from 'vue'
import ChatView from './ChatView.vue'

const props = defineProps<{
  showSingleChat: boolean
  selectedGroupSessionId: string | null
  dhaInstances: { dha_id: string; name: string; role?: string }[]
}>()

const emit = defineEmits<{
  (e: 'message-sent'): void
  (e: 'speak-mode-changed'): void
  (e: 'dha-added'): void
}>()

type GroupDetail = {
  id: string
  title: string
  messages: { message_id?: string; role: string; dha_id?: string; content: string }[]
  dha_map: Record<string, { name?: string; role?: string }>
  dha_ids: string[]
  leader_dha_id?: string
  speak_mode?: string
}

const groupDetail = ref<GroupDetail | null>(null)
const groupLoading = ref(false)
const groupError = ref<string | null>(null)
const groupDisplayMessages = ref<GroupDetail['messages']>([])
const groupInputText = ref('')
const groupStreaming = ref(false)
const groupStreamingPhase = ref('')
const groupMessagesRef = ref<HTMLElement | null>(null)
const groupDiscussionGoal = ref<string | null>(null)
const showGroupWorkspace = ref(false)
const showGroupMembers = ref(false)
const groupWorkspacePath = ref('')
const groupWorkspaceEntries = ref<{ name: string; path: string; is_dir: boolean }[]>([])
const groupWorkspaceLoading = ref(false)
const groupWorkspaceError = ref('')

const groupMemberNames = computed(() => {
  const d = groupDetail.value
  if (!d?.dha_ids?.length || !d.dha_map) return ''
  return d.dha_ids.map((id) => d.dha_map![id]?.name || id).join('、')
})

const groupRecentSummary = computed(() => {
  const msgs = groupDisplayMessages.value.slice(-4)
  if (!msgs.length) return ''
  const d = groupDetail.value
  const parts = msgs.map((m) => {
    if (m.role === 'user') return `【用户】${(m.content || '').slice(0, 40)}`
    if (m.role === 'host') return `【主持人】`
    const name = d?.dha_map?.[m.dha_id || '']?.name || m.dha_id || 'DHA'
    return `【${name}】${(m.content || '').slice(0, 40)}`
  })
  return parts.join(' ')
})

watch(
  () => groupDetail.value?.messages,
  (messages) => {
    groupDisplayMessages.value = Array.isArray(messages) ? [...messages] : []
    const firstUser = groupDisplayMessages.value.find((m) => m.role === 'user')
    groupDiscussionGoal.value = firstUser?.content?.trim() ?? null
  },
  { immediate: true }
)

watch(
  () => [showGroupWorkspace.value, groupDetail.value?.id] as const,
  ([show, id]) => {
    if (show && id) {
      groupWorkspacePath.value = ''
      loadGroupWorkspace()
    }
  }
)

function formatGroupMsgTime(ts?: string) {
  if (!ts) return ''
  try {
    const d = new Date(ts)
    return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
  } catch {
    return ts
  }
}

async function loadGroupWorkspace() {
  const id = groupDetail.value?.id
  if (!id) return
  groupWorkspaceLoading.value = true
  groupWorkspaceError.value = ''
  try {
    const path = groupWorkspacePath.value ? `?path=${encodeURIComponent(groupWorkspacePath.value)}` : ''
    const r = await fetch(`/api/workspaces/${encodeURIComponent(id)}/files${path}`)
    const j = await r.json().catch(() => null)
    if (j?.status === 'ok' && Array.isArray(j?.data?.entries)) {
      groupWorkspaceEntries.value = j.data.entries.map((e: { name: string; path: string; is_dir?: boolean }) => ({
        name: e.name,
        path: e.path,
        is_dir: !!e.is_dir,
      }))
    } else {
      groupWorkspaceEntries.value = []
      groupWorkspaceError.value = j?.detail || '加载失败'
    }
  } catch {
    groupWorkspaceError.value = '网络错误'
    groupWorkspaceEntries.value = []
  } finally {
    groupWorkspaceLoading.value = false
  }
}

function groupWorkspaceDownloadUrl(filePath: string) {
  const id = groupDetail.value?.id
  if (!id) return '#'
  return `/api/workspaces/${encodeURIComponent(id)}/files/download?path=${encodeURIComponent(filePath)}`
}

function scrollGroupToBottom() {
  nextTick(() => {
    const el = groupMessagesRef.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

async function sendGroupMessage() {
  const detail = groupDetail.value
  const msg = groupInputText.value.trim()
  if (!detail || groupStreaming.value || !msg) return
  groupInputText.value = ''
  groupStreaming.value = true
  groupStreamingPhase.value = '正在准备…'
  const userMsg = { message_id: `msg-${Date.now()}`, role: 'user' as const, content: msg }
  groupDisplayMessages.value = [...groupDisplayMessages.value, userMsg]
  scrollGroupToBottom()
  try {
    const r = await fetch(`/api/group-sessions/${encodeURIComponent(detail.id)}/chat/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: msg }),
    })
    if (!r.ok) throw new Error(r.statusText)
    emit('message-sent')
    const reader = r.body?.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    if (reader) {
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const parts = buffer.split('\n\n')
        buffer = parts.pop() || ''
        for (const block of parts) {
          if (!block.startsWith('event: ')) continue
          const dataStr = block.includes('\ndata: ') ? block.split('\ndata: ').slice(1).join('\ndata: ').trim() : ''
          const eventType = block.slice(0, block.indexOf('\n')).replace('event: ', '').trim()
          if (eventType === 'message' && dataStr) {
            groupStreamingPhase.value = '正在生成回复…'
            try {
              const data = JSON.parse(dataStr)
              if (data && (data.role === 'assistant' || data.role === 'user' || data.role === 'host')) {
                groupDisplayMessages.value = [...groupDisplayMessages.value, data]
                scrollGroupToBottom()
              }
            } catch (_) {}
          }
        }
      }
    }
    emit('message-sent')
  } catch (e) {
    console.error('群聊发送失败', e)
  } finally {
    groupStreaming.value = false
    groupStreamingPhase.value = ''
  }
}

/** 标准化为 GroupDetail，保证 messages/dha_map/dha_ids 必为数组/对象 */
function normalizeGroupDetail(raw: Record<string, unknown>, fallbackId: string): GroupDetail {
  const id = String(raw.id ?? fallbackId)
  const messages = Array.isArray(raw.messages) ? raw.messages as GroupDetail['messages'] : []
  const dha_map = (raw.dha_map && typeof raw.dha_map === 'object') ? (raw.dha_map as GroupDetail['dha_map']) : {}
  const dha_ids = Array.isArray(raw.dha_ids) ? (raw.dha_ids as string[]) : []
  return {
    id,
    title: String(raw.title ?? '群聊'),
    messages,
    dha_map,
    dha_ids,
    leader_dha_id: String(raw.leader_dha_id ?? ''),
    speak_mode: String((raw.speak_mode ?? raw.speak_node) ?? 'auto'),
  }
}

function parseGroupResponse(id: string, body: unknown): GroupDetail | null {
  if (body == null) return null
  if (Array.isArray(body)) {
    return normalizeGroupDetail({ id, title: '群聊', messages: body, dha_ids: [], dha_map: {} }, id)
  }
  if (typeof body !== 'object') return null
  const o = body as Record<string, unknown>
  // 后端标准返回：{ status: "ok", data: { id, title, messages, dha_map, dha_ids, ... } }
  if (o.status === 'ok' && o.data != null && typeof o.data === 'object') {
    return normalizeGroupDetail(o.data as Record<string, unknown>, id)
  }
  // 兼容直接返回会话对象（无 status/data 包裹）
  if (o.id != null && (Array.isArray(o.messages) || o.messages === undefined)) {
    return normalizeGroupDetail(o, id)
  }
  return null
}

async function loadGroupDetail() {
  const id = props.selectedGroupSessionId
  if (!id) return
  groupLoading.value = true
  groupError.value = null
  try {
    const r = await fetch(`/api/group-sessions/${encodeURIComponent(id)}`)
    const body = await r.json().catch(() => null)
    const parsed = parseGroupResponse(id, body)
    // 仅当当前选中的仍是本次请求的 id 时才更新，避免竞态覆盖
    if (props.selectedGroupSessionId !== id) return
    if (parsed) {
      groupDetail.value = parsed
    } else {
      groupDetail.value = null
      groupError.value = !r.ok
        ? (r.status === 404 ? '会话不存在' : (body && typeof body === 'object' && 'detail' in body ? String((body as { detail?: string }).detail) : `请求失败 ${r.status}`))
        : (body && typeof body === 'object' && 'detail' in body ? String((body as { detail?: string }).detail) : '返回格式异常')
    }
  } catch {
    if (props.selectedGroupSessionId === id) {
      groupDetail.value = null
      groupError.value = '网络错误，请确认后端已启动（默认端口 8000）'
    }
  } finally {
    groupLoading.value = false
  }
}

watch(
  () => props.selectedGroupSessionId,
  (id) => {
    if (id) {
      groupError.value = null
      loadGroupDetail()
    }
  },
  { immediate: true }
)


defineExpose({ refresh: loadGroupDetail })
</script>

<style scoped>
.workspace-right-content {
  flex: 1 1 0%;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: var(--color-page);
  color: var(--color-text);
}

.workspace-right-inner {
  flex: 1 1 0%;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* 群聊整块根节点（有选中 id 时）：保证占满且子节点可计算高度 */
.workspace-group-root {
  flex: 1 1 0%;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* 群聊内容外层：强制最小高度 */
.workspace-group-wrap {
  flex: 1 1 0%;
  min-height: 70vh;
  min-width: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.workspace-group-chat-inner {
  flex: 1 1 0%;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.workspace-group-chat-inner .workspace-group-chat,
.workspace-group-chat-inner .group-chat-simple {
  flex: 1 1 0%;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* 统一状态区：加载 / 错误 / 空态 */
.workspace-state {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 1.5rem;
  text-align: center;
}

.workspace-state-loading {
  gap: 0.75rem;
}

.workspace-state-dots {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.35rem;
}

.workspace-state-dots span {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--color-loading-dot, var(--color-text-muted));
  animation: workspace-dot 1.2s ease-in-out infinite both;
}

.workspace-state-dots span:nth-child(1) { animation-delay: 0s; }
.workspace-state-dots span:nth-child(2) { animation-delay: 0.2s; }
.workspace-state-dots span:nth-child(3) { animation-delay: 0.4s; }

@keyframes workspace-dot {
  0%, 80%, 100% { opacity: 0.4; transform: scale(0.85); }
  40% { opacity: 1; transform: scale(1); }
}

.workspace-state-text {
  margin: 0;
  font-size: 0.9375rem;
  color: var(--color-text-muted);
}

.workspace-state-error {
  gap: 0.5rem;
}

.workspace-state-title {
  margin: 0;
  font-size: 1rem;
  font-weight: 600;
  color: var(--color-text);
}

.workspace-state-btn {
  margin-top: 0.5rem;
  padding: 0.5rem 1rem;
  font-size: 0.875rem;
  border-radius: 8px;
  border: 1px solid var(--color-border);
  background: var(--color-card);
  color: var(--color-accent);
  cursor: pointer;
  transition: background-color 0.15s, color 0.15s;
}

.workspace-state-btn:hover {
  background: var(--color-list-hover);
  color: var(--color-accent-hover, var(--color-accent));
}

/* 空态 */
.workspace-state-empty {
  gap: 0.75rem;
  max-width: 28rem;
  margin: 0 auto;
}

.workspace-empty-icon {
  color: var(--color-text-muted);
  opacity: 0.7;
}

.workspace-empty-title {
  margin: 0;
  font-size: 1.25rem;
  font-weight: 600;
  color: var(--color-text);
}

.workspace-empty-desc,
.workspace-empty-hint {
  margin: 0;
  font-size: 0.9375rem;
  line-height: 1.5;
  color: var(--color-text-muted);
}

.workspace-empty-hint {
  font-size: 0.8125rem;
  opacity: 0.9;
}
</style>
