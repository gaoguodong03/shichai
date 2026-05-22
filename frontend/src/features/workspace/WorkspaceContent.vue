<template>
  <div class="workspace-right-content">
    <!-- 会话（带主持人，可选专家）：讨论目标/提示词、skill/系统调用展示、主题变量 -->
    <div v-if="groupDetail" class="workspace-right-inner workspace-group-root group-chat-theme">
      <div :key="'group-' + (groupDetail?.id ?? '')" class="workspace-group-wrap flex flex-col min-h-0">
        <GroupChatHeader />
        <div class="flex-1 min-h-0 flex overflow-visible">
          <div class="group-chat-main flex-1 min-h-0 flex flex-col overflow-visible">
            <div class="group-chat-main-row">
              <div class="group-chat-main-right">
                <GroupChatMessages />
                <GroupChatComposer />
              </div>
            </div>
          </div>
          <GroupWorkspacePanel />
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
        <button type="button" class="workspace-state-btn" @click="() => loadGroupDetail()">重试</button>
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
        在左侧选择已有会话，或点击「新建会话」创建新会话（默认仅主持人，可在会话内邀请专家）。
      </p>
      <p class="workspace-empty-hint">
        会话内可使用工作区、邀请专家等能力。
      </p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, nextTick, computed, onMounted, onUnmounted } from 'vue'
import hostLogoUrl from '@/assets/49logo.png'
import GroupChatHeader from './components/group-chat/GroupChatHeader.vue'
import GroupChatMessages from './components/group-chat/GroupChatMessages.vue'
import GroupChatComposer from './components/group-chat/GroupChatComposer.vue'
import GroupWorkspacePanel from './components/group-chat/GroupWorkspacePanel.vue'
import { provideGroupChatWorkspaceContext } from './components/group-chat/groupChatWorkspaceContext'
import { createGroupChatStreamRunner } from './composables/useGroupChatStreamRunner'
import { streamSessionEvents } from '@/api/chat'
import { uploadWorkspaceFile } from './workspaceUpload'
import {
  dhaBodyContent,
  formatToolPopover,
  getToolRawResults,
  renderMarkdownHtml,
  renderSnippetMarkdownHtml,
  sanitizeWorkspaceDownloadUrl,
  toolRawMeta,
} from './workspaceMessageUtils'

/** 与后端群聊虚拟主持人 agent_id 一致 */
const VIRTUAL_SCENE_HOST_ID = 'agent-scene-host'

interface MsgExt {
  timestamp?: string
  skill_id?: string
  expert_route_debug?: Record<string, unknown>
  skill_route_debug?: Record<string, unknown>
  tool_raw_results?: string[]
  next_prompt?: string
  suggested_order?: string[]
  event_type?: string
  joined_agent_ids?: string[]
  left_agent_ids?: string[]
}

const props = defineProps<{
  selectedGroupSessionId: string | null
  dhaInstances: { agent_id: string; name: string; role?: string; avatar_url?: string; skill_ids?: string[]; file_capability_labels?: string[]; file_capabilities?: Record<string, boolean>; url_capability?: boolean }[]
  /** 用于气泡上 skill 标签：将内部 skill_id 解析为 SKILL 中的展示名 */
  skills?: { id: string; name: string }[]
  middleColumnOpen?: boolean
}>()

const emit = defineEmits<{
  (e: 'message-sent'): void
  (e: 'dha-added'): void
  (e: 'scenario-new-session', sessionId: string): void
  (e: 'middle-column-open-request'): void
  (e: 'middle-column-toggle'): void
}>()

type GroupDetail = {
  id: string
  title: string
  messages: { message_id?: string; role: string; agent_id?: string; content: string }[]
  agent_map: Record<string, { name?: string; role?: string; avatar_url?: string; file_capability_labels?: string[]; file_capabilities?: Record<string, boolean>; url_capability?: boolean }>
  agent_ids: string[]
  leader_agent_id?: string
  runtime_state?: { running?: boolean; agent_id?: string; skill_id?: string; phase?: string; started_at?: string }
  /** recruitment：可推荐邀请；scene：名单固定，不展示招募条 */
  orchestration_profile?: string
}

type GroupStreamRuntime = {
  streaming: boolean
  phase: string
  abort: AbortController | null
  runToken: number
  agentId?: string
  skillId?: string
  restored?: boolean
}

const groupDetail = ref<GroupDetail | null>(null)
const DEFAULT_HOST_DISPLAY_NAME = '四九'
const hostDisplayName = ref(DEFAULT_HOST_DISPLAY_NAME)
const groupLoading = ref(false)
const groupError = ref<string | null>(null)
const groupDisplayMessages = ref<GroupMessage[]>([])
const groupNextPrompt = ref('')
const groupStreamStates = ref<Record<string, GroupStreamRuntime>>({})
const currentGroupStreamState = computed(() => {
  const id = props.selectedGroupSessionId || ''
  return id ? groupStreamStates.value[id] || null : null
})
const groupStreaming = computed(() => Boolean(currentGroupStreamState.value?.streaming))
const groupStreamingPhase = computed(() => currentGroupStreamState.value?.phase || '')
const groupMessagesRef = ref<HTMLElement | null>(null)
const groupDiscussionGoal = ref<string | null>(null)
const showGroupWorkspace = ref(false)
const groupWorkspacePath = ref('')
const groupWorkspaceEntries = ref<{ name: string; path: string; is_dir: boolean }[]>([])
const groupWorkspaceLoading = ref(false)
const groupWorkspaceError = ref('')
const groupWorkspacePreviewPath = ref('')
const groupWorkspacePreviewName = ref('')
const groupWorkspacePreviewContent = ref('')
const groupWorkspacePreviewImageUrl = ref('')
const groupWorkspacePreviewLoading = ref(false)
const groupWorkspacePreviewEditing = ref(false)
const groupWorkspacePreviewEditContent = ref('')
const groupWorkspaceUploadInputRef = ref<HTMLInputElement | null>(null)
const groupWorkspaceUploading = ref(false)
const groupWorkspaceUploadingName = ref('')
const groupWorkspaceUploadProgress = ref<number | null>(null)
const groupWorkspaceWidth = ref(360)
const groupWorkspaceListWidth = ref(192)
// 工作区预览区默认收起，初始总宽度略窄，仅文件列表为主
const groupWorkspacePreviewCollapsed = ref(true)
/** 工作区图片预览用 blob: URL，切换/关闭时 revoke */
let groupWorkspacePreviewObjectUrl: string | null = null

function revokeGroupWorkspacePreviewBlob() {
  if (groupWorkspacePreviewObjectUrl) {
    try {
      URL.revokeObjectURL(groupWorkspacePreviewObjectUrl)
    } catch {
      // ignore
    }
    groupWorkspacePreviewObjectUrl = null
  }
}

function clearGroupWorkspacePreviewState() {
  revokeGroupWorkspacePreviewBlob()
  groupWorkspacePreviewPath.value = ''
  groupWorkspacePreviewName.value = ''
  groupWorkspacePreviewContent.value = ''
  groupWorkspacePreviewImageUrl.value = ''
  groupWorkspacePreviewEditing.value = false
}

function groupWorkspaceGoRoot() {
  clearGroupWorkspacePreviewState()
  groupWorkspacePath.value = ''
  loadGroupWorkspace()
}

function groupWorkspaceEnterDir(e: { name: string; path: string; is_dir: boolean }) {
  clearGroupWorkspacePreviewState()
  groupWorkspacePath.value = groupWorkspacePath.value ? `${groupWorkspacePath.value}/${e.name}` : e.name
  loadGroupWorkspace()
}

let workspaceResizeStartX = 0
let workspaceResizeStartWidth = 360
let workspaceInnerResizeStartX = 0
let workspaceInnerResizeStartWidth = 192
const isResizingWorkspace = ref(false)
const isResizingWorkspaceInner = ref(false)
const lastExpandedWorkspaceWidth = ref(672)

const USER_PREF_UPDATED_EVENT_NAME = 'dha-user-pref-updated'
/** 与 MainView persistScenarioPresets 成功时派发一致，用于刷新快捷场景列表（工作区组件可能未卸载） */
const SESSION_PRESETS_UPDATED_EVENT_NAME = 'dha-session-presets-updated'
const HOST_NAME_UPDATED_EVENT_NAME = 'dha-host-display-name-updated'
const USER_STORAGE_KEY = 'dha_user'
const WORKSPACE_OPEN_STORAGE_KEY = 'dha_user_pref_workspace_open_v1'
const TOC_WORKSPACE_OPEN_STORAGE_KEY = 'dha_user_pref_toc_workspace_open_v1'
const RESTORED_RUNTIME_POLL_INTERVAL_MS = 2500
let restoredRuntimePollTimer: ReturnType<typeof setTimeout> | null = null
let restoredRuntimePollSessionId = ''
let groupSessionEventsAbort: AbortController | null = null
let groupSessionEventsSessionId = ''
let groupSessionEventsConnected = false
let groupSessionPushRefreshTimer: ReturnType<typeof setTimeout> | null = null

function loadWorkspaceOpenDefault(): boolean {
  try {
    const raw = localStorage.getItem(WORKSPACE_OPEN_STORAGE_KEY)
    if (raw === 'true') return true
    if (raw === 'false') return false
  } catch {
    // ignore
  }
  return false
}

function persistBoolToLocalStorage(storageKey: string, value: boolean) {
  try {
    localStorage.setItem(storageKey, value ? 'true' : 'false')
  } catch {
    // ignore
  }
}

function loadTocWorkspaceOpenDefault(): boolean {
  try {
    const raw = localStorage.getItem(TOC_WORKSPACE_OPEN_STORAGE_KEY)
    if (raw === 'true') return true
    if (raw === 'false') return false
  } catch {
    // ignore
  }
  // 默认保持旧行为：不开启归档侧边目录
  return false
}

const sessionMetaPopoverOpen = ref(loadTocWorkspaceOpenDefault())
const sessionMetaPopoverRootRef = ref<HTMLElement | null>(null)
const sessionTitleDraft = ref('')
const titleSaving = ref(false)
// 让“工作区”按钮默认状态也受用户喜好影响
showGroupWorkspace.value = loadWorkspaceOpenDefault()
// TOC 当前高亮条目（key 与 archiveItems.item.key 一致）
const tocActiveKey = ref<string>('')

function toSnippet(content: string, limit = 20) {
  const s = (content || '')
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
  if (!s) return '（空）'
  return s.length > limit ? s.slice(0, limit) + '…' : s
}

const archiveItems = computed(() => {
  const d = groupDetail.value
  const map = d?.agent_map || {}
  return (groupDisplayMessages.value || [])
    .map((m, idx) => ({ m, idx }))
    .filter(({ m }) => m.role === 'assistant' && !!m.agent_id) // 只要专家，不要主持人/用户
    .map(({ m, idx }) => {
      const did = (m.agent_id || '').trim()
      const name = (map[did]?.name || did || '专家').trim()
      return {
        key: (m.message_id || `idx-${idx}`) + '-' + did,
        agent_id: did,
        name,
        message_id: (m.message_id || `idx-${idx}`) as string,
        snippet: toSnippet(String(m.content || ''), 50),
      }
    })
})

const groupFileCapabilitySummary = computed(() => {
  const detail = groupDetail.value
  const out = { read: false, edit: false, write: false, rename: false, mkdir: false, list_dir: false, url: false }
  if (!detail?.agent_map) return out
  for (const agentId of detail.agent_ids || []) {
    const caps = detail.agent_map?.[agentId]?.file_capabilities || {}
    out.read = out.read || !!caps.read
    out.edit = out.edit || !!caps.edit
    out.write = out.write || !!caps.write
    out.rename = out.rename || !!caps.rename
    out.mkdir = out.mkdir || !!caps.mkdir
    out.list_dir = out.list_dir || !!caps.list_dir
    out.url = out.url || !!detail.agent_map?.[agentId]?.url_capability
  }
  return out
})

function scrollToMessage(messageId: string) {
  const el = groupMessagesRef.value?.querySelector?.(`[data-message-id="${CSS.escape(messageId)}"]`) as HTMLElement | null
  if (el) {
    el.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }
}

function toggleSessionMetaPopover() {
  sessionMetaPopoverOpen.value = !sessionMetaPopoverOpen.value
  if (sessionMetaPopoverOpen.value) {
    sessionTitleDraft.value = groupDetail.value?.title || ''
  }
  persistBoolToLocalStorage(TOC_WORKSPACE_OPEN_STORAGE_KEY, sessionMetaPopoverOpen.value)
  window.dispatchEvent(
    new CustomEvent(USER_PREF_UPDATED_EVENT_NAME, {
      detail: { key: TOC_WORKSPACE_OPEN_STORAGE_KEY, value: sessionMetaPopoverOpen.value },
    })
  )
}

function onDocClickCloseSessionMeta(e: MouseEvent) {
  const root = sessionMetaPopoverRootRef.value
  if (root && !root.contains(e.target as Node)) {
    sessionMetaPopoverOpen.value = false
  }
}

let sessionMetaOutsideTimer: ReturnType<typeof setTimeout> | null = null
function bindSessionMetaOutsideClick() {
  unbindSessionMetaOutsideClick()
  sessionMetaOutsideTimer = setTimeout(() => {
    sessionMetaOutsideTimer = null
    document.addEventListener('click', onDocClickCloseSessionMeta)
  }, 0)
}
function unbindSessionMetaOutsideClick() {
  if (sessionMetaOutsideTimer) {
    clearTimeout(sessionMetaOutsideTimer)
    sessionMetaOutsideTimer = null
  }
  document.removeEventListener('click', onDocClickCloseSessionMeta)
}

async function saveSessionTitle() {
  const id = groupDetail.value?.id
  if (!id) return
  const t = (sessionTitleDraft.value || '').trim()
  if (!t) return
  titleSaving.value = true
  try {
    const r = await fetch(`/api/sessions/${encodeURIComponent(id)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: t }),
    })
    const j = await r.json().catch(() => ({}))
    if ((j as { status?: string }).status === 'ok') {
      if (groupDetail.value) groupDetail.value = { ...groupDetail.value, title: t }
      emit('message-sent')
    } else {
      alert((j as { detail?: string }).detail || '保存标题失败')
    }
  } catch {
    alert('保存标题失败，请检查网络')
  } finally {
    titleSaving.value = false
  }
}

function jumpToSessionTopic(messageId: string) {
  scrollToMessage(messageId)
  sessionMetaPopoverOpen.value = false
  unbindSessionMetaOutsideClick()
}

function toggleGroupWorkspaceOpen() {
  showGroupWorkspace.value = !showGroupWorkspace.value
  persistBoolToLocalStorage(WORKSPACE_OPEN_STORAGE_KEY, showGroupWorkspace.value)
  window.dispatchEvent(
    new CustomEvent(USER_PREF_UPDATED_EVENT_NAME, {
      detail: { key: WORKSPACE_OPEN_STORAGE_KEY, value: showGroupWorkspace.value },
    })
  )
}

type TocSpyEntry = { key: string; el: HTMLElement }
let tocSpyEntries: TocSpyEntry[] = []
let tocSpyScrollEl: HTMLElement | null = null
let tocSpyScrollHandler: ((e: Event) => void) | null = null
let tocSpyRaf = 0

function stopTocScrollSpy() {
  if (tocSpyScrollEl && tocSpyScrollHandler) {
    tocSpyScrollEl.removeEventListener('scroll', tocSpyScrollHandler)
  }
  tocSpyScrollEl = null
  tocSpyScrollHandler = null
  if (tocSpyRaf) cancelAnimationFrame(tocSpyRaf)
  tocSpyRaf = 0
}

function rebuildTocSpyEntries() {
  const sc = groupMessagesRef.value
  if (!sc) return
  const items = (archiveItems.value || []).map((it) => {
    const el = sc.querySelector(`[data-message-id="${CSS.escape(it.message_id)}"]`) as HTMLElement | null
    return el ? ({ key: it.key, el } as TocSpyEntry) : null
  })
  tocSpyEntries = items.filter(Boolean) as TocSpyEntry[]
  // 按在滚动容器里的位置排序，保证后面“最后匹配”逻辑更稳定
  tocSpyEntries.sort((a, b) => (a.el.offsetTop || 0) - (b.el.offsetTop || 0))
}

function startTocScrollSpy() {
  const sc = groupMessagesRef.value
  if (!sc) return
  tocSpyScrollEl = sc
  const offsetTop = 90

  const handler = () => {
    if (tocSpyRaf) cancelAnimationFrame(tocSpyRaf)
    tocSpyRaf = requestAnimationFrame(() => {
      const scRect = sc.getBoundingClientRect()
      let best: TocSpyEntry | null = null
      for (const entry of tocSpyEntries) {
        const r = entry.el.getBoundingClientRect()
        const relTop = r.top - scRect.top
        if (relTop <= offsetTop) best = entry
      }
      tocActiveKey.value = best?.key || tocSpyEntries[0]?.key || ''
    })
  }

  tocSpyScrollHandler = handler
  sc.addEventListener('scroll', handler, { passive: true })
}

watch(
  () => [sessionMetaPopoverOpen.value, archiveItems.value.map((it) => it.key).join('|')],
  async ([open]) => {
    stopTocScrollSpy()
    tocActiveKey.value = ''
    if (!open) return
    await nextTick()
    rebuildTocSpyEntries()
    if (tocSpyEntries.length) tocActiveKey.value = tocSpyEntries[0].key
    startTocScrollSpy()
  },
)

watch(sessionMetaPopoverOpen, (open) => {
  if (open) {
    bindSessionMetaOutsideClick()
  } else {
    unbindSessionMetaOutsideClick()
  }
})

watch(
  () => groupDetail.value?.title,
  (t) => {
    if (!sessionMetaPopoverOpen.value) sessionTitleDraft.value = t || ''
  },
)

function formatSkillId(skillId?: string) {
  if (!skillId) return ''
  if (skillId === 'default') return '默认'
  const hit = (props.skills || []).find((s) => s.id === skillId)
  const label = (hit?.name || '').trim()
  if (label) return label
  return skillId
}

/** 是否按主持人气泡样式展示（与后端 role=host 一致；旧版曾在有 leader 时存成 assistant） */
function isHostBubbleMessage(msg: GroupMessage): boolean {
  if (msg.role === 'host') return true
  if (msg.role !== 'assistant') return false
  const row = msg as GroupMessage & MsgExt & { agent_id?: string }
  const mid = String(row.agent_id || '').trim()
  if (!mid) return false
  if (mid === VIRTUAL_SCENE_HOST_ID) return true
  const lid = String(groupDetail.value?.leader_agent_id || '').trim()
  if (lid && mid === lid) {
    const sid = row.skill_id
    const label = formatSkillId(sid)
    if (label.includes('主持')) return true
    if (sid && String(sid).toLowerCase().includes('host')) return true
  }
  return false
}

/** 气泡标题行显示名：与专家一致优先用 agent_map；主持人类无映射时用当前主持展示名 */
function bubbleDisplayName(msg: GroupMessage): string {
  const row = msg as GroupMessage & { agent_id?: string }
  const aid = String(row.agent_id || '').trim()
  if (aid) {
    const n = (groupDetail.value?.agent_map || {})[aid]?.name
    if (n && String(n).trim()) return String(n).trim()
  }
  if (isHostBubbleMessage(msg)) return (hostDisplayName.value || DEFAULT_HOST_DISPLAY_NAME).trim()
  return aid || '—'
}

const mdRef = ref<{ render: (s: string) => string } | null>(null)

function renderMarkdown(text: string) {
  return renderMarkdownHtml(mdRef.value, text)
}

function renderSnippetMarkdown(text: string): string {
  return renderSnippetMarkdownHtml(renderMarkdown(text))
}

let authImageHydrateRaf = 0
const authImageObjectUrls: string[] = []

function scheduleHydrateAuthImages() {
  if (authImageHydrateRaf) return
  authImageHydrateRaf = window.requestAnimationFrame(async () => {
    authImageHydrateRaf = 0
    await hydrateAuthImages()
  })
}

async function hydrateAuthImages() {
  const container = groupMessagesRef.value
  if (!container) return

  const imgs = Array.from(container.querySelectorAll<HTMLImageElement>('img[data-dha-auth-src]'))
  for (const img of imgs) {
    if (img.dataset.dhaHydrated === '1') continue
    const rawSrc = sanitizeWorkspaceDownloadUrl(img.getAttribute('data-dha-auth-src') || '')
    if (!rawSrc) continue

    img.dataset.dhaHydrated = '1'
    try {
      const r = await fetch(rawSrc)
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      const blob = await r.blob()
      const objUrl = URL.createObjectURL(blob)
      authImageObjectUrls.push(objUrl)
      img.src = objUrl
    } catch {
      // 不要用裸 /api/... 作为 img.src：浏览器请求不带 Authorization，会 401
      img.alt = `${img.alt || '图片'}（加载失败）`
    }
  }
}

const expandedToolKey = ref<string | null>(null)

const moreMenuRef = ref<HTMLElement | null>(null)

function closeMembersDropdown(e: MouseEvent) {
  const target = e.target as Node
  const el = e.target as HTMLElement
  const isOpeningAddMember = el?.closest?.('.group-chat-add-remove-in-picker')
  if (addMemberRef.value && !addMemberRef.value.contains(target) && !isOpeningAddMember) {
    showAddMember.value = false
  }
  if (moreMenuRef.value && !moreMenuRef.value.contains(target)) showMoreMenu.value = false
  if (!el?.closest?.('.group-chat-tool-tag-wrap')) expandedToolKey.value = null
}

async function confirmGroupNext(
  override: string,
  extra?: { ignoreAutoExpertId?: string; ignoreAutoSkillId?: string },
) {
  const detail = groupDetail.value
  const id = detail?.id
  if (!detail || !id || groupStreaming.value) return
  autoSwitchHint.value = null
  groupWaitingForUser.value = false
  groupSuggestedNextSpeaker.value = null
  const { runToken, abort } = beginGroupStream(id, '正在确认…')
  const body: {
    override_next_speaker?: string
    custom_prompt?: string
    host_takeover_requested?: boolean
    ignore_auto_expert_id?: string
    ignore_auto_skill_id?: string
  } = {}
  if (override && override !== '__auto__') body.override_next_speaker = override
  if (extra?.ignoreAutoExpertId) body.ignore_auto_expert_id = extra.ignoreAutoExpertId
  if (extra?.ignoreAutoSkillId) body.ignore_auto_skill_id = extra.ignoreAutoSkillId
  const base = builtMessage()
  lastSentDraft.value = {
    goal: String(groupDiscussionGoal.value || ''),
    nextPrompt: String(groupNextPrompt.value || ''),
    files: [...(attachedFiles.value || [])],
  }
  const hasFiles = attachedFiles.value.length > 0
  try {
    const msg = hasFiles ? await buildMessageWithFiles(detail, base) : base
    if (msg) body.custom_prompt = msg
    if (msg) body.host_takeover_requested = detectHostTakeoverIntent(msg)
    const shouldEmitMessageSent = await runGroupStream(id, body, abort.signal)
    if (shouldEmitMessageSent) emit('message-sent')
  } catch (e) {
    console.error('确认下一发言人失败', e)
  } finally {
    if (isCurrentGroupRun(id, runToken)) {
      clearStreamingPlaceholders()
      finishGroupStream(id, runToken)
    }
  }
}

async function inviteSingleMember(dhaId: string) {
  const id = groupDetail.value?.id
  if (!id) return
  try {
    const r = await fetch(`/api/sessions/${encodeURIComponent(id)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ add_agent_ids: [dhaId] }),
    })
    const j = await r.json().catch(() => ({}))
    if ((j as { status?: string }).status === 'ok') {
      emit('dha-added')
      await loadGroupDetail()
    } else {
      alert((j as { detail?: string }).detail || '邀请失败')
    }
  } catch {
    alert('邀请失败，请检查网络')
  }
}

async function removeMember(dhaId: string) {
  const id = groupDetail.value?.id
  const leader = (groupDetail.value?.leader_agent_id || '').trim()
  if (dhaId === 'host') return
  if (leader && dhaId === leader) return
  if (!id || !window.confirm('确定将该成员移出群聊？')) return
  try {
    const r = await fetch(`/api/sessions/${encodeURIComponent(id)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ remove_agent_ids: [dhaId] }),
    })
    const j = await r.json().catch(() => ({}))
    if ((j as { status?: string }).status === 'ok') {
      emit('dha-added')
      await loadGroupDetail()
      if (groupNextSpeakerOverride.value === dhaId) groupNextSpeakerOverride.value = ''
    } else {
      alert((j as { detail?: string }).detail || '移出失败')
    }
  } catch {
    alert('移出失败，请检查网络')
  }
}

const insertLocalFileInputRef = ref<HTMLInputElement | null>(null)
const insertLocalFileUploading = ref(false)
const insertLocalFileUploadingName = ref('')
const insertLocalFileUploadProgress = ref<number | null>(null)
function triggerInsertLocalFile() {
  if (insertLocalFileUploading.value) return
  insertLocalFileInputRef.value?.click()
}
async function onInsertLocalFile(ev: Event) {
  const input = ev.target as HTMLInputElement
  const id = groupDetail.value?.id
  if (!id || !input.files?.length || insertLocalFileUploading.value) return
  const file = input.files[0]
  insertLocalFileUploading.value = true
  insertLocalFileUploadingName.value = file.name || '本地文件'
  insertLocalFileUploadProgress.value = null
  try {
    const j = await uploadWorkspaceFile(id, file, groupWorkspacePath.value, ({ percent }) => {
      insertLocalFileUploadProgress.value = percent
    })
    if (j?.status === 'ok' && j?.data?.path) {
      await loadGroupWorkspace()
      const relPath = j.data.path as string
      const name = file.name || relPath.split('/').pop() || relPath
      if (!attachedFiles.value.find((f) => f.path === relPath)) {
        attachedFiles.value.push({ name, path: relPath })
      }
      showInsertFile.value = false
      showInsertFileModal.value = false
    } else {
      alert((j as { detail?: string })?.detail || '上传失败')
    }
  } catch (e) {
    alert(e instanceof Error ? e.message : '上传失败，请检查网络或后端')
  } finally {
    insertLocalFileUploading.value = false
    insertLocalFileUploadingName.value = ''
    insertLocalFileUploadProgress.value = null
    input.value = ''
  }
}

async function openInsertFileModal() {
  insertFileBrowsePath.value = ''
  showInsertFileModal.value = true
  await loadInsertFileEntries()
}

function insertFileEnterDir(e: { name: string; path: string; is_dir: boolean }) {
  if (!e.is_dir) return
  insertFileBrowsePath.value = insertFileBrowsePath.value ? `${insertFileBrowsePath.value}/${e.name}` : e.name
  loadInsertFileEntries()
}

function insertFileGoUp() {
  if (!insertFileBrowsePath.value) return
  const cur = insertFileBrowsePath.value.replace(/\/+$/, '')
  const parent = cur.includes('/') ? cur.slice(0, cur.lastIndexOf('/')) : ''
  insertFileBrowsePath.value = parent
  loadInsertFileEntries()
}

function onUserPrefUpdated(ev: Event) {
  const e = ev as CustomEvent<{ key?: string; value?: unknown }>
  const key = e.detail?.key
  if (key === WORKSPACE_OPEN_STORAGE_KEY) {
    showGroupWorkspace.value = !!e.detail?.value
  }
  if (key === TOC_WORKSPACE_OPEN_STORAGE_KEY) {
    sessionMetaPopoverOpen.value = !!e.detail?.value
  }
}

function onSessionPresetsUpdated() {
  loadShortcutPresets()
}

function onHostDisplayNameUpdated() {
  loadHostDisplayName()
}

onMounted(() => {
  document.addEventListener('click', closeMembersDropdown)
  window.addEventListener(USER_PREF_UPDATED_EVENT_NAME, onUserPrefUpdated as EventListener)
  window.addEventListener(SESSION_PRESETS_UPDATED_EVENT_NAME, onSessionPresetsUpdated)
  window.addEventListener(HOST_NAME_UPDATED_EVENT_NAME, onHostDisplayNameUpdated as EventListener)
  import('markdown-it').then((M) => {
    const Md = M.default as new (opts?: { breaks?: boolean }) => { render: (s: string) => string }
    mdRef.value = new Md({ breaks: true })
  }).catch(() => {})
  loadShortcutPresets()
  loadHostDisplayName()
})
onUnmounted(() => {
  document.removeEventListener('click', closeMembersDropdown)
  unbindSessionMetaOutsideClick()
  clearRestoredRuntimePollTimer()
  closeGroupSessionEventsStream()
  window.removeEventListener(USER_PREF_UPDATED_EVENT_NAME, onUserPrefUpdated as EventListener)
  window.removeEventListener(SESSION_PRESETS_UPDATED_EVENT_NAME, onSessionPresetsUpdated)
  window.removeEventListener(HOST_NAME_UPDATED_EVENT_NAME, onHostDisplayNameUpdated as EventListener)
  stopTocScrollSpy()
  for (const u of authImageObjectUrls) {
    try {
      URL.revokeObjectURL(u)
    } catch {
      // ignore
    }
  }
  authImageObjectUrls.length = 0
  revokeGroupWorkspacePreviewBlob()
})

type ShortcutHostConfig = {
  skill_ids: string[]
  skill_refs?: { id: string; name?: string }[]
  display_name?: string
  system_prompt?: string
  llm_provider_id?: string
  mcp_server_ids?: string[]
}
type ShortcutPreset = {
  id: string
  name: string
  agent_ids: string[]
  leader_agent_id?: string
  host_config?: ShortcutHostConfig
  description?: string
  discussion_goal_example?: string
}
const shortcutPresets = ref<ShortcutPreset[]>([])
const shortcutPresetsLoaded = ref(false)
const SHORTCUT_STORAGE_KEY_BASE = 'dha.group.shortcuts.v1'
const LEGACY_DEFAULT_HOST_SKILL_ID = 'group-host'

function normalizeShortcutHostConfig(hc: ShortcutHostConfig | undefined): ShortcutHostConfig | undefined {
  if (!hc) return undefined
  const skillLookup = Object.fromEntries((props.skills || []).map((s) => [s.id, s.name || s.id]))
  const refs = Array.isArray(hc.skill_refs) ? hc.skill_refs : []
  const refName = (id: string) => {
    const fromCurrent = String(skillLookup[id] || '').trim()
    if (fromCurrent) return fromCurrent
    const hit = refs.find((row) => String(row?.id || '').trim() === id)
    return String(hit?.name || '').trim()
  }
  const skillIds: string[] = []
  const seen = new Set<string>()
  for (const item of Array.isArray(hc.skill_ids) ? hc.skill_ids : []) {
    const id = String(item || '').trim()
    if (!id || seen.has(id)) continue
    const exists = Boolean(skillLookup[id])
    const name = refName(id)
    if (id === LEGACY_DEFAULT_HOST_SKILL_ID && !exists && (!name || name === id)) {
      continue
    }
    skillIds.push(id)
    seen.add(id)
  }
  return {
    ...hc,
    skill_ids: skillIds,
    skill_refs: refs.filter((row) => skillIds.includes(String(row?.id || '').trim())),
  }
}

function getCurrentUserShortcutStorageKey(): string {
  try {
    const username = String(localStorage.getItem(USER_STORAGE_KEY) || '')
      .trim()
      .toLowerCase()
    if (!username) return `${SHORTCUT_STORAGE_KEY_BASE}:anonymous`
    return `${SHORTCUT_STORAGE_KEY_BASE}:${encodeURIComponent(username)}`
  } catch {
    return `${SHORTCUT_STORAGE_KEY_BASE}:anonymous`
  }
}
function normalizeShortcutPresets(input: unknown): ShortcutPreset[] {
  if (!Array.isArray(input)) return []
  const out: ShortcutPreset[] = []
  const seen = new Set<string>()
  for (const item of input) {
    const raw = item as Partial<ShortcutPreset>
    const id = String(raw?.id || '').trim()
    const name = String(raw?.name || '').trim()
    const dhaIds = Array.isArray(raw?.agent_ids)
      ? Array.from(new Set(raw.agent_ids.map((x) => String(x || '').trim()).filter(Boolean)))
      : []
    if (!id || !name || !dhaIds.length || seen.has(id)) continue
    seen.add(id)
    const lid = String(raw?.leader_agent_id || '').trim()
    const hc = normalizeShortcutHostConfig(raw?.host_config as ShortcutHostConfig | undefined)
    out.push({
      id,
      name,
      agent_ids: dhaIds,
      leader_agent_id: hc ? VIRTUAL_SCENE_HOST_ID : lid || dhaIds[0] || '',
      host_config: hc,
      description: String(raw?.description || '').trim(),
      discussion_goal_example: String(raw?.discussion_goal_example || '').trim(),
    })
  }
  return out
}
function defaultShortcutPresets(): ShortcutPreset[] {
  // 新账号不再根据专家名自动注入「调研/博客」等场景，避免首屏即写入服务端 session_presets
  return []
}
async function loadServerShortcutPresets(): Promise<ShortcutPreset[]> {
  try {
    const r = await fetch('/api/settings/session-presets')
    const j = await r.json().catch(() => ({}))
    const list = (j as { data?: { presets?: unknown } })?.data?.presets
    return normalizeShortcutPresets(list)
  } catch {
    return []
  }
}
async function loadShortcutPresets() {
  shortcutPresetsLoaded.value = false
  const serverPresets = await loadServerShortcutPresets()
  if (serverPresets.length) {
    // 后端有配置时以其为准，避免本地旧缓存把已删除项带回来
    shortcutPresets.value = serverPresets
    saveShortcutPresets(false)
    shortcutPresetsLoaded.value = true
    return
  }
  try {
    const storageKey = getCurrentUserShortcutStorageKey()
    let raw = localStorage.getItem(storageKey)
    if (!raw) {
      // 兼容历史全局 key：首次读取后迁移到当前账号命名空间。
      raw = localStorage.getItem(SHORTCUT_STORAGE_KEY_BASE)
      if (raw) localStorage.setItem(storageKey, raw)
    }
    if (!raw) {
      shortcutPresets.value = defaultShortcutPresets()
      saveShortcutPresets(false)
      shortcutPresetsLoaded.value = true
      return
    }
    const parsed = JSON.parse(raw)
    const normalized = normalizeShortcutPresets(parsed)
    if (normalized.length) {
      shortcutPresets.value = normalized
    } else {
      shortcutPresets.value = defaultShortcutPresets()
    }
    // 读取时立即回写一次，修复历史脏数据，避免下次重开丢失
    saveShortcutPresets(false)
  } catch {
    shortcutPresets.value = defaultShortcutPresets()
    saveShortcutPresets(false)
  }
  shortcutPresetsLoaded.value = true
}
function saveShortcutPresets(syncRemote = true) {
  const payload = shortcutPresets.value.map((p) => {
    const row: Record<string, unknown> = {
      id: p.id,
      name: p.name,
      agent_ids: p.agent_ids,
      description: p.description || '',
      discussion_goal_example: p.discussion_goal_example || '',
    }
    if (p.host_config) {
      row.host_config = p.host_config
      row.leader_agent_id = VIRTUAL_SCENE_HOST_ID
    } else {
      row.leader_agent_id = p.leader_agent_id || p.agent_ids[0] || ''
    }
    return row
  })
  try {
    localStorage.setItem(getCurrentUserShortcutStorageKey(), JSON.stringify(payload))
  } catch {}
  if (!syncRemote) return
  fetch('/api/settings/session-presets', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ presets: payload }),
  }).catch(() => {})
}
function deleteShortcutPreset(id: string) {
  shortcutPresets.value = shortcutPresets.value.filter((p) => p.id !== id)
  if (editingShortcutId.value === id) {
    editingShortcutId.value = ''
    newShortcutName.value = ''
    newShortcutDhaIds.value = []
  }
  saveShortcutPresets()
}
/** 供父组件在导入场景包后拉起新会话（与快捷场景「新建会话」同一套逻辑） */
async function createSessionFromScenarioPreset(p: ShortcutPreset): Promise<string | null> {
  const availableAgentIds = new Set(
    (props.dhaInstances || [])
      .map((x) => String(x?.agent_id || '').trim())
      .filter(Boolean),
  )
  const targetExperts = Array.from(new Set((p.agent_ids || []).filter((x) => !!x))).filter((id) =>
    availableAgentIds.has(id),
  )
  if (!targetExperts.length) {
    window.alert('该场景中的专家在当前账号下不可用，请先编辑场景后重试')
    return null
  }
  if (targetExperts.length < (p.agent_ids || []).length) {
    window.alert('已自动跳过当前账号下不可用的专家')
  }
  const title = (p.name || '').trim() || '新对话'
  const body: Record<string, unknown> = {
    title,
    agent_ids: targetExperts,
  }
  if (p.host_config) {
    body.host_config = p.host_config
    body.leader_agent_id = VIRTUAL_SCENE_HOST_ID
  } else {
    const lid = (p.leader_agent_id || p.agent_ids[0] || '').trim()
    if (lid && availableAgentIds.has(lid)) {
      body.leader_agent_id = lid
    } else if (targetExperts[0]) {
      body.leader_agent_id = targetExperts[0]
    }
  }
  try {
    const r = await fetch('/api/sessions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    const j = (await r.json().catch(() => ({}))) as { status?: string; data?: { id?: string }; detail?: string }
    if (j.status !== 'ok' || !j.data?.id) {
      window.alert(typeof j.detail === 'string' ? j.detail : '创建会话失败')
      return null
    }
    const newId = j.data.id
    emit('scenario-new-session', newId)
    return newId
  } catch {
    window.alert('创建会话失败，请检查网络')
    return null
  }
}

async function applyShortcutPreset(id: string) {
  const p = shortcutPresets.value.find((x) => x.id === id)
  if (!p) return
  const newId = await createSessionFromScenarioPreset(p)
  if (!newId) return
  saveShortcutPresets()
  showShortcutEditor.value = false
  showShortcutEditorModal.value = false
}

watch(
  () => props.dhaInstances,
  () => {
    if (!shortcutPresets.value.length) shortcutPresets.value = defaultShortcutPresets()
  },
  { immediate: true },
)

watch(
  () => shortcutPresets.value,
  () => {
    if (!shortcutPresetsLoaded.value) return
    saveShortcutPresets(true)
  },
  { deep: true },
)

const DHA_AVATAR_COLORS = [
  'var(--color-dha-box-1)',
  'var(--color-dha-box-2)',
  'var(--color-dha-box-3)',
  'var(--color-dha-box-4)',
  'var(--color-dha-box-5)',
  'var(--color-dha-box-6)',
  'var(--color-dha-box-7)',
  'var(--color-dha-box-0)',
]

function dhaIndex(dhaId?: string): number {
  const ids = groupDetail.value?.agent_ids || []
  const i = ids.indexOf(dhaId || '')
  return i >= 0 ? i % DHA_AVATAR_COLORS.length : 0
}

function dhaAvatarColor(index: number): string {
  return DHA_AVATAR_COLORS[index % DHA_AVATAR_COLORS.length]
}

function dhaAvatarChar(dhaId?: string): string {
  const name = groupDetail.value?.agent_map?.[dhaId || '']?.name || dhaId || '?'
  return name.slice(0, 1).toUpperCase()
}

/** 专家头像 URL：优先当前页专家列表，其次群聊详情里的 agent_map（含后端下发的 avatar_url） */
function expertAvatarUrl(dhaId?: string): string | null {
  if (!dhaId) return null
  const fromList = (props.dhaInstances || []).find((x) => x.agent_id === dhaId)?.avatar_url
  const u1 = fromList && String(fromList).trim()
  if (u1) return u1
  const fromMap = groupDetail.value?.agent_map?.[dhaId]?.avatar_url
  const u2 = fromMap && String(fromMap).trim()
  return u2 || null
}

const groupWaitingForUser = ref(false)
const groupSuggestedNextSpeaker = ref<string | null>(null)
const groupSuggestedAddDhaIds = ref<string[]>([]) // 主持人推荐的待邀请 DHA（0 成员时，可一位或多位）
const suggestedInviteLoading = ref(false)
const autoSwitchHint = ref<{ sessionId: string; expertId?: string; expertName?: string; skillId?: string; skillName?: string } | null>(null)
const autoSwitchIgnoreLoading = ref(false)
const lastSentDraft = ref<{ goal: string; nextPrompt: string; files: { name: string; path: string }[] } | null>(null)
const lastRoute = ref<{ sessionId: string; expertId: string; skillId: string } | null>(null)
const currentAutoSwitchHint = computed(() => {
  const h = autoSwitchHint.value
  if (!h) return null
  return h.sessionId === props.selectedGroupSessionId ? h : null
})
const autoSwitchHintText = computed(() => {
  const h = currentAutoSwitchHint.value
  if (!h) return ''
  const expert = (h.expertName || '').trim()
  if (!expert) return ''
  return `${hostDisplayName.value || DEFAULT_HOST_DISPLAY_NAME}已帮您切换专家：${expert}`
})
function patchGroupStreamState(sessionId: string, patch: Partial<GroupStreamRuntime>) {
  if (!sessionId) return
  const prev = groupStreamStates.value[sessionId] || { streaming: false, phase: '', abort: null, runToken: 0 }
  groupStreamStates.value = {
    ...groupStreamStates.value,
    [sessionId]: { ...prev, ...patch },
  }
}

function beginGroupStream(sessionId: string, phase: string): { runToken: number; abort: AbortController } {
  const prev = groupStreamStates.value[sessionId] || { streaming: false, phase: '', abort: null, runToken: 0 }
  const abort = new AbortController()
  const runToken = Number(prev.runToken || 0) + 1
  patchGroupStreamState(sessionId, { streaming: true, phase, abort, runToken, restored: false })
  return { runToken, abort }
}

function isCurrentGroupRun(sessionId: string, runToken: number): boolean {
  return Number(groupStreamStates.value[sessionId]?.runToken || 0) === Number(runToken)
}

function finishGroupStream(sessionId: string, runToken: number, phase = '') {
  if (!isCurrentGroupRun(sessionId, runToken)) return
  if (restoredRuntimePollSessionId === sessionId) clearRestoredRuntimePollTimer()
  patchGroupStreamState(sessionId, { streaming: false, phase, abort: null, agentId: '', skillId: '', restored: false })
}

function abortGroupStream(sessionId: string) {
  const st = groupStreamStates.value[sessionId]
  if (!st) return
  if (restoredRuntimePollSessionId === sessionId) clearRestoredRuntimePollTimer()
  try {
    st.abort?.abort()
  } catch {
    // ignore
  }
  patchGroupStreamState(sessionId, {
    streaming: false,
    phase: '已停止',
    abort: null,
    runToken: Number(st.runToken || 0) + 1,
    agentId: '',
    skillId: '',
    restored: false,
  })
}

function clearRestoredRuntimePollTimer() {
  if (restoredRuntimePollTimer) {
    clearTimeout(restoredRuntimePollTimer)
    restoredRuntimePollTimer = null
  }
  restoredRuntimePollSessionId = ''
}

function scheduleRestoredRuntimePoll(sessionId: string) {
  if (!sessionId || props.selectedGroupSessionId !== sessionId) return
  if (groupSessionEventsConnected && groupSessionEventsSessionId === sessionId) return
  if (restoredRuntimePollTimer && restoredRuntimePollSessionId === sessionId) return
  clearRestoredRuntimePollTimer()
  restoredRuntimePollSessionId = sessionId
  restoredRuntimePollTimer = setTimeout(() => {
    restoredRuntimePollTimer = null
    void pollRestoredRuntimeState(sessionId)
  }, RESTORED_RUNTIME_POLL_INTERVAL_MS)
}

async function pollRestoredRuntimeState(sessionId: string) {
  if (!sessionId || props.selectedGroupSessionId !== sessionId) return
  const st = groupStreamStates.value[sessionId]
  if (!st?.restored || st.abort) {
    clearRestoredRuntimePollTimer()
    return
  }
  await loadGroupDetail({ silent: true })
  const next = groupStreamStates.value[sessionId]
  if (props.selectedGroupSessionId === sessionId && next?.restored && next.streaming && !next.abort) {
    scheduleRestoredRuntimePoll(sessionId)
  }
}

function clearGroupSessionPushRefreshTimer() {
  if (groupSessionPushRefreshTimer) {
    clearTimeout(groupSessionPushRefreshTimer)
    groupSessionPushRefreshTimer = null
  }
}

function scheduleGroupSessionPushRefresh(sessionId: string) {
  if (!sessionId || props.selectedGroupSessionId !== sessionId) return
  clearGroupSessionPushRefreshTimer()
  groupSessionPushRefreshTimer = setTimeout(() => {
    groupSessionPushRefreshTimer = null
    if (props.selectedGroupSessionId !== sessionId) return
    const st = groupStreamStates.value[sessionId]
    if (st?.streaming && st.abort) return
    void loadGroupDetail({ silent: true })
  }, 150)
}

function closeGroupSessionEventsStream() {
  clearGroupSessionPushRefreshTimer()
  const abort = groupSessionEventsAbort
  groupSessionEventsAbort = null
  groupSessionEventsSessionId = ''
  groupSessionEventsConnected = false
  try {
    abort?.abort()
  } catch {
    // ignore
  }
}

function openGroupSessionEventsStream(sessionId: string) {
  if (!sessionId) {
    closeGroupSessionEventsStream()
    return
  }
  if (groupSessionEventsAbort && groupSessionEventsSessionId === sessionId) return
  closeGroupSessionEventsStream()
  const abort = new AbortController()
  groupSessionEventsAbort = abort
  groupSessionEventsSessionId = sessionId
  const handlePushClosed = (error?: unknown) => {
    if (abort.signal.aborted || props.selectedGroupSessionId !== sessionId) return
    if (error) console.warn('会话事件推送连接失败，暂时使用恢复态轮询兜底', error)
    groupSessionEventsConnected = false
    const st = groupStreamStates.value[sessionId]
    if (st?.restored && st.streaming && !st.abort) scheduleRestoredRuntimePoll(sessionId)
  }
  void streamSessionEvents(
    sessionId,
    {
      onUpdate: () => {
        if (abort.signal.aborted || props.selectedGroupSessionId !== sessionId) return
        groupSessionEventsConnected = true
        if (restoredRuntimePollSessionId === sessionId) clearRestoredRuntimePollTimer()
        scheduleGroupSessionPushRefresh(sessionId)
      },
      onError: (error) => {
        if (abort.signal.aborted || props.selectedGroupSessionId !== sessionId) return
        console.warn('会话事件推送中断，暂时使用恢复态轮询兜底', error)
        groupSessionEventsConnected = false
        const st = groupStreamStates.value[sessionId]
        if (st?.restored && st.streaming && !st.abort) scheduleRestoredRuntimePoll(sessionId)
      },
    },
    abort.signal,
  ).then(() => handlePushClosed()).catch((error) => handlePushClosed(error))
}

const currentGroupStreaming = computed(() => Boolean(currentGroupStreamState.value?.streaming))
const otherSessionStreaming = computed(() => false)
const currentGroupStreamingPhase = computed(() => currentGroupStreaming.value ? groupStreamingPhase.value : '')
const groupTurnLimitReached = ref(false) // 当达到后端 DHA 轮次上限时，为 true，用于给用户提示
const groupOrchestrationPhase = ref('')
const groupInterruptReason = ref('')
const groupResumeTargetDhaId = ref<string | null>(null)
const groupRequiredUserFields = ref<Array<Record<string, unknown>>>([])
const groupNextSpeakerOverride = ref<string>('')
const showAddMember = ref(false)
const showAddMemberModal = ref(false)
const showMoreMenu = ref(false)
const showNextPromptField = ref(false) // 更多 -> 显示下一 DHA 提示词，默认隐藏
function onShowNextPromptFieldChangeByClick() {
  showNextPromptField.value = !showNextPromptField.value
  if (showNextPromptField.value) showMoreMenu.value = false
}
const showShortcutEditor = ref(false)
const showShortcutEditorModal = ref(false)
const shortcutEditorRef = ref<HTMLElement | null>(null)
const shortcutPresetSearch = ref('')
const editingShortcutId = ref('')
const newShortcutName = ref('')
const newShortcutDhaIds = ref<string[]>([])
const shortcutExpertSearch = ref('')
const showInsertFile = ref(false)
const showInsertFileModal = ref(false)
const insertFileRef = ref<HTMLElement | null>(null)
const insertFileBrowsePath = ref('')
const insertFileEntries = ref<{ name: string; path: string; is_dir: boolean }[]>([])
const insertFileLoading = ref(false)
type AttachedFile = { name: string; path: string }
const attachedFiles = ref<AttachedFile[]>([])

function toAgentStyleId(raw: string | null | undefined): string {
  const sid = String(raw || '').trim()
  if (!sid) return ''
  if (sid.startsWith('agent-')) return sid
  return `agent-${sid}`
}

function buildExpertAliasMap(): Map<string, string> {
  const out = new Map<string, string>()
  for (const d of (props.dhaInstances || [])) {
    const id = String(d.agent_id || '').trim()
    if (!id) continue
    out.set(id, id)
    const agentId = toAgentStyleId(id)
    if (agentId) out.set(agentId, id)
  }
  return out
}

function extractSuggestedAddIds(payload: Record<string, unknown> | null | undefined): string[] {
  if (!payload) return []
  const agentIds = payload.suggested_add_agent_ids as string[] | undefined
  if (Array.isArray(agentIds) && agentIds.length) return agentIds
  const singleAgentId = payload.suggested_add_agent_id as string | undefined
  if (typeof singleAgentId === 'string' && singleAgentId.trim()) return [singleAgentId.trim()]
  return []
}

function extractAutoInvitedIds(payload: Record<string, unknown> | null | undefined): string[] {
  if (!payload) return []
  const agentIds = payload.auto_invited_agent_ids as string[] | undefined
  if (Array.isArray(agentIds) && agentIds.length) return agentIds
  return []
}

function isExpertAssistantMessagePayload(payload: Record<string, unknown> | null | undefined): boolean {
  if (!payload) return false
  if (payload.role !== 'assistant') return false
  const agentId = String(payload.agent_id || '').trim()
  const skillId = String(payload.skill_id || '').trim()
  // 主持人消息通常不含 skill_id；专家发言会带 skill_id。
  return Boolean(agentId && skillId)
}

function updateAutoSwitchHint(payload: Record<string, unknown>, sessionId = props.selectedGroupSessionId || '') {
  if (!payload || !sessionId) return
  const routedExpertId = String(payload.agent_id || '').trim()
  const routedSkillId = String(payload.skill_id || '').trim()
  if (!routedExpertId && !routedSkillId) return

  // 基线：优先使用上一次 route；若没有（例如刷新页面后首条 route），则从已展示的最后一条 assistant 消息推断。
  const prevFromMessages = (() => {
    const list = groupDisplayMessages.value || []
    for (let i = list.length - 1; i >= 0; i--) {
      const m = list[i] as GroupMessage & { agent_id?: string; skill_id?: string }
      if (m?.role === 'assistant' && m.agent_id && (m as Record<string, unknown>).skill_id) {
        return { expertId: String(m.agent_id || ''), skillId: String((m as Record<string, unknown>).skill_id || '') }
      }
    }
    return null
  })()
  const routeInThisSession = lastRoute.value?.sessionId === sessionId ? lastRoute.value : null
  const prev = routeInThisSession || prevFromMessages
  const changedExpert = Boolean(routedExpertId && prev?.expertId && routedExpertId !== prev.expertId)
  const changedSkill = Boolean(routedSkillId && prev?.skillId && routedSkillId !== prev.skillId)
  // 若完全没有基线，则只记录不提示；否则只要发生切换就提示。
  if (!prev) {
    lastRoute.value = { sessionId, expertId: routedExpertId, skillId: routedSkillId }
    patchGroupStreamState(sessionId, { agentId: routedExpertId, skillId: routedSkillId })
    autoSwitchHint.value = null
    return
  }
  lastRoute.value = { sessionId, expertId: routedExpertId || prev.expertId, skillId: routedSkillId || prev.skillId }
  patchGroupStreamState(sessionId, { agentId: routedExpertId || prev.expertId, skillId: routedSkillId || prev.skillId })
  if (!changedExpert && !changedSkill) return

  const map = groupDetail.value?.agent_map || {}
  const finalExpertId = routedExpertId
  const finalSkillId = routedSkillId
  const expertName = finalExpertId ? (map[finalExpertId]?.name || finalExpertId) : ''
  const skillName = finalSkillId ? formatSkillId(finalSkillId) : ''
  autoSwitchHint.value = {
    sessionId,
    expertId: changedExpert ? finalExpertId : '',
    expertName: changedExpert ? expertName : '',
    skillId: changedSkill ? finalSkillId : '',
    skillName: changedSkill ? skillName : '',
  }
}

function applyOrchestrationEndMeta(endData: Record<string, unknown>) {
  const phase = typeof endData.phase === 'string' ? endData.phase.trim() : ''
  groupOrchestrationPhase.value = phase
  const reason = typeof endData.interrupt_reason === 'string' ? endData.interrupt_reason.trim() : ''
  groupInterruptReason.value = reason
  const resumeDha = typeof endData.resume_target_agent_id === 'string' ? endData.resume_target_agent_id.trim() : ''
  groupResumeTargetDhaId.value = resumeDha || null
  const required = endData.required_user_fields
  groupRequiredUserFields.value = Array.isArray(required) ? (required as Array<Record<string, unknown>>) : []
}

const orchestrationInterruptHint = computed(() => {
  const reason = (groupInterruptReason.value || '').trim()
  if (!reason) return ''
  if (reason === 'need_user_input') return '需要你补充信息后继续'
  if (reason === 'need_more_context') return '需要补充上下文后继续'
  if (reason === 'need_recruit_expert') return '建议先邀请新专家后继续'
  if (reason === 'tool_unavailable') return '工具不可用，建议确认后重试或换方案'
  if (reason === 'timeout_or_budget_exceeded') return '已达轮次/预算限制，建议确认后继续'
  if (reason === 'policy_or_security') return '触发安全/策略限制，需你确认'
  if (reason === 'conflict_detected') return '决策冲突，已回落为等待确认'
  return `中断原因：${reason}`
})

function removePromptFileReference(file: AttachedFile) {
  const targets = new Set(
    [file.name, file.path, file.path.split('/').pop()]
      .map((x) => String(x || '').trim())
      .filter(Boolean),
  )
  if (!targets.size || !groupNextPrompt.value) return
  const lines = String(groupNextPrompt.value).split(/\r?\n/)
  let changed = false
  const kept = lines.filter((line) => {
    const match = line.trim().match(/^【文件引用：(.+)】$/)
    if (!match) return true
    const parts = match[1].split('｜').map((x) => x.trim()).filter(Boolean)
    if (!parts.some((part) => targets.has(part))) return true
    changed = true
    return false
  })
  if (changed) {
    groupNextPrompt.value = kept.join('\n').replace(/\n{3,}/g, '\n\n').trim()
  }
}

function removeAttachedFile(path: string) {
  const removed = attachedFiles.value.find((f) => f.path === path)
  attachedFiles.value = attachedFiles.value.filter((f) => f.path !== path)
  if (removed) removePromptFileReference(removed)
}
const addMemberRef = ref<HTMLElement | null>(null)

const invitableDhas = computed(() => {
  const inGroup = new Set(groupDetail.value?.agent_ids || [])
  return (props.dhaInstances || []).filter((d) => !inGroup.has(d.agent_id))
})

const filteredShortcutExperts = computed(() => {
  const q = (shortcutExpertSearch.value || '').trim().toLowerCase()
  const all = props.dhaInstances || []
  if (!q) return all
  return all.filter((d) => {
    const name = (d.name || '').toLowerCase()
    const id = (d.agent_id || '').toLowerCase()
    return name.includes(q) || id.includes(q)
  })
})

const leaderDhaId = computed(() => (groupDetail.value?.leader_agent_id || '').trim())
// 后端如果没显式返回 leader_agent_id，也要让 UI 有“主持人”这个常驻成员。
const leaderDisplayId = computed(() => leaderDhaId.value || 'host')
const orderedMemberIds = computed(() => {
  const ids = [...(groupDetail.value?.agent_ids || [])]
  const leader = leaderDisplayId.value
  const rest = ids.filter((x) => x !== leader)
  return [leader, ...rest]
})

/** 主持人推荐的 DHA 的展示名（来自资源中心实例列表，多位用顿号连接） */
const pendingSuggestedAddDhaIds = computed(() => {
  if (String(groupDetail.value?.orchestration_profile || '').toLowerCase() === 'scene') {
    return []
  }
  const aliasMap = buildExpertAliasMap()
  const inGroup = new Set((groupDetail.value?.agent_ids || []).map((id) => toAgentStyleId(id)))
  const normalized = (groupSuggestedAddDhaIds.value || [])
    .map((id) => aliasMap.get(String(id || '').trim()) || '')
    .filter(Boolean)
  return [...new Set(normalized)].filter((id) => !inGroup.has(toAgentStyleId(id)))
})

const pendingSuggestedDhaItems = computed(() =>
  pendingSuggestedAddDhaIds.value.map((id) => ({ id, name: suggestedDhaDisplayName(id) })),
)

function suggestedDhaDisplayName(id: string): string {
  const aliasMap = buildExpertAliasMap()
  const canonicalId = aliasMap.get(String(id || '').trim()) || id
  return (props.dhaInstances || []).find((x) => x.agent_id === canonicalId)?.name
    || groupDetail.value?.agent_map?.[canonicalId]?.name
    || groupDetail.value?.agent_map?.[id]?.name
    || canonicalId
}

function shortcutPresetExpertNamesText(preset: ShortcutPreset): string {
  const map = groupDetail.value?.agent_map || {}
  const names = (preset.agent_ids || [])
    .map((id) => (props.dhaInstances || []).find((x) => x.agent_id === id)?.name || map[id]?.name || id)
    .filter(Boolean)
  return names.join('、')
}

const filteredShortcutPresets = computed(() => {
  const q = (shortcutPresetSearch.value || '').trim().toLowerCase()
  const list = shortcutPresets.value || []
  if (!q) return list
  return list.filter((p) => {
    const name = (p.name || '').toLowerCase()
    const experts = shortcutPresetExpertNamesText(p).toLowerCase()
    return name.includes(q) || experts.includes(q)
  })
})

async function loadHostDisplayName() {
  try {
    const r = await fetch('/api/settings/host-profile')
    const j = await r.json().catch(() => ({}))
    const next = String((j as { data?: { display_name?: string } })?.data?.display_name || '').trim()
    hostDisplayName.value = next || DEFAULT_HOST_DISPLAY_NAME
  } catch {
    hostDisplayName.value = DEFAULT_HOST_DISPLAY_NAME
  }
}

async function inviteSuggestedDha() {
  const ids = pendingSuggestedAddDhaIds.value
  const groupId = groupDetail.value?.id
  if (!ids.length || !groupId) return
  suggestedInviteLoading.value = true
  try {
    const r = await fetch(`/api/sessions/${encodeURIComponent(groupId)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ add_agent_ids: ids }),
    })
    const j = await r.json().catch(() => ({}))
    if ((j as { status?: string }).status === 'ok') {
      groupSuggestedAddDhaIds.value = []
      // 邀请动作本身不应把发送按钮切到“确认并继续”。
      // 邀请后由用户直接继续输入并发送即可。
      groupWaitingForUser.value = false
      groupSuggestedNextSpeaker.value = null
      emit('dha-added')
      await loadGroupDetail()
    } else {
      alert((j as { detail?: string }).detail || '邀请失败')
    }
  } catch {
    alert('邀请失败，请检查网络')
  } finally {
    suggestedInviteLoading.value = false
  }
}

async function inviteOneSuggestedDha(dhaId: string) {
  const groupId = groupDetail.value?.id
  if (!groupId || !dhaId) return
  suggestedInviteLoading.value = true
  try {
    const r = await fetch(`/api/sessions/${encodeURIComponent(groupId)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ add_agent_ids: [dhaId] }),
    })
    const j = await r.json().catch(() => ({}))
    if ((j as { status?: string }).status === 'ok') {
      groupSuggestedAddDhaIds.value = groupSuggestedAddDhaIds.value.filter((id) => id !== dhaId)
      // 邀请单个建议专家后保持“发送”态，避免多一次空确认点击。
      groupWaitingForUser.value = false
      groupSuggestedNextSpeaker.value = null
      emit('dha-added')
      await loadGroupDetail()
    } else {
      alert((j as { detail?: string }).detail || '邀请失败')
    }
  } catch {
    alert('邀请失败，请检查网络')
  } finally {
    suggestedInviteLoading.value = false
  }
}

async function ignoreAutoSwitchAndPause() {
  if (!currentAutoSwitchHint.value) return
  autoSwitchIgnoreLoading.value = true
  try {
    try {
      if (props.selectedGroupSessionId) abortGroupStream(props.selectedGroupSessionId)
    } catch (_) {}
    if (props.selectedGroupSessionId) patchGroupStreamState(props.selectedGroupSessionId, { phase: '已暂停：请编辑后重新发送' })
    groupWaitingForUser.value = false
    groupSuggestedNextSpeaker.value = null
    clearStreamingPlaceholders()
    autoSwitchHint.value = null
    const d = lastSentDraft.value
    if (d) {
      groupDiscussionGoal.value = d.goal
      groupNextPrompt.value = d.nextPrompt
      attachedFiles.value = [...(d.files || [])]
    }
    nextTick(() => {
      try {
        goalTextareaRef.value?.focus()
      } catch (_) {}
    })
  } finally {
    autoSwitchIgnoreLoading.value = false
  }
}

/** 跳过成员进出场等系统条，取最后一条实质消息（用于无 suggested_next_speaker 时的推断） */
function lastNonSystemGroupMessageForToolbar(): GroupMessage | null {
  const list = groupDisplayMessages.value || []
  for (let i = list.length - 1; i >= 0; i--) {
    const m = list[i] as GroupMessage & { event_type?: string }
    const et = m.event_type
    if (m.role === 'host' && (et === 'member_joined' || et === 'member_left')) continue
    return m as GroupMessage
  }
  return null
}

/** 输入区旁「发言焦点」：流式中=正在输出者；空闲时=服务端建议的下一位（含 user/host/end），避免误显示上一轮专家或 ids[0] 抖动 */
const effectiveNextSpeaker = computed(() => {
  const override = (groupNextSpeakerOverride.value || '').trim()
  const suggested = groupSuggestedNextSpeaker.value
  const active = activeStreamingDhaId.value
  const ids = orderedMemberIds.value

  if (override) {
    if (override === 'user' || override === 'end') return override
    if (override === 'host' || ids.includes(override)) return override
  }

  if (groupStreaming.value) {
    if (active && (active === 'host' || ids.includes(active))) return active
    return ''
  }

  if (suggested != null && String(suggested).trim() !== '') {
    const s = String(suggested).trim().toLowerCase()
    if (s === 'user' || s === 'end') return s
    if (s === 'host') return 'host'
    if (ids.includes(suggested)) return suggested
  }

  // 无服务端建议时：根据最后一条可见消息推断（兼容历史会话/旧 end 载荷未带 suggested 的情况）
  const lastMsg = lastNonSystemGroupMessageForToolbar()
  if (lastMsg?.role === 'host') {
    return 'user'
  }
  if (lastMsg?.role === 'user' && !currentGroupStreaming.value) {
    const lid = (leaderDisplayId.value || '').trim()
    if (lid === 'host' || !lid) return 'host'
    if (ids.includes(lid)) return lid
    return 'host'
  }

  // 空闲态且无服务端建议：默认回到主持人（四九），避免一直显示上一轮专家造成误导。
  const lid = (leaderDisplayId.value || '').trim()
  if (!lid || lid === 'host') return 'host'
  if (ids.includes(lid)) return lid
  return 'host'
})

/** 暂停态「下一位」文案：保留 user/end 的语义。 */
const nextSpeakerLabelText = computed(() => {
  const eff = effectiveNextSpeaker.value
  const ids = orderedMemberIds.value
  if (!eff) return (hostDisplayName.value || DEFAULT_HOST_DISPLAY_NAME).trim() || '四九'
  if (eff === 'user') return '你'
  if (eff === 'end') return '已结束'
  if (eff === 'host') return (hostDisplayName.value || DEFAULT_HOST_DISPLAY_NAME).trim() || '四九'
  if (ids.includes(eff)) return displayGroupSpeakerName(eff)
  return (hostDisplayName.value || DEFAULT_HOST_DISPLAY_NAME).trim() || '四九'
})

function isToolbarRoleValid(id: string): boolean {
  if (!id) return false
  if (id === 'host') return true
  return orderedMemberIds.value.includes(id)
}

function toolbarLeaderFallbackId(): string {
  const lid = (leaderDisplayId.value || '').trim()
  if (!lid || lid === 'host') return 'host'
  if (orderedMemberIds.value.includes(lid)) return lid
  return 'host'
}

/** @ 提及：输入 @ 后显示的候选（主持人 + 当前群内专家），按输入过滤 */
const showAtDropdown = ref(false)
const atSource = ref<'goal' | 'nextPrompt'>('goal')
const atFilter = ref('')
const atInsertStart = ref(0)
const atSelectionEnd = ref(0)
const atSelectedIndex = ref(0)
const goalTextareaRef = ref<HTMLTextAreaElement | null>(null)
const nextPromptTextareaRef = ref<HTMLTextAreaElement | null>(null)

const atMentionOptions = computed(() => {
  const host = { type: 'host' as const, id: 'host', label: hostDisplayName.value || DEFAULT_HOST_DISPLAY_NAME }
  const d = groupDetail.value
  const ids = d?.agent_ids || []
  const map = d?.agent_map || {}
  const experts = ids.map((id) => ({ type: 'dha' as const, id, label: map[id]?.name || id }))
  const list = [host, ...experts]
  const q = (atFilter.value || '').trim().toLowerCase()
  if (!q) return list
  return list.filter((o) => (o.label || '').toLowerCase().includes(q) || (o.id || '').toLowerCase().includes(q))
})

function openAtDropdown(source: 'goal' | 'nextPrompt', value: string, insertStart: number, selectionEnd: number) {
  atSource.value = source
  atInsertStart.value = insertStart
  atSelectionEnd.value = selectionEnd
  atFilter.value = value.slice(insertStart + 1, selectionEnd)
  atSelectedIndex.value = 0
  showAtDropdown.value = true
}

/** 空格或标点视为已 @ 完，不再匹配候选 */
const AT_END_REG = /[\s，。、；：！？,.\-;:!?（）【】《》""''\[\]{}]/

function onAtInput(source: 'goal' | 'nextPrompt', e: Event) {
  const el = e.target as HTMLTextAreaElement
  const value = el.value
  const start = el.selectionStart ?? 0
  const end = el.selectionEnd ?? start
  const lastAt = value.lastIndexOf('@', end - 1)
  if (lastAt === -1 || (lastAt > 0 && /[\w\u4e00-\u9fa5]/.test(value[lastAt - 1]))) {
    showAtDropdown.value = false
    return
  }
  const segment = value.slice(lastAt + 1, end)
  if (segment && AT_END_REG.test(segment)) {
    showAtDropdown.value = false
    return
  }
  openAtDropdown(source, value, lastAt, end)
}

function selectMention(opt: { type: 'host' | 'dha'; id: string; label: string }) {
  const insertText =
    opt.type === 'host' ? `@${hostDisplayName.value || DEFAULT_HOST_DISPLAY_NAME} ` : `@${opt.label} `
  if (atSource.value === 'goal') {
    const raw = (groupDiscussionGoal.value ?? '') as string
    const before = raw.slice(0, atInsertStart.value)
    const after = raw.slice(atSelectionEnd.value)
    groupDiscussionGoal.value = before + insertText + after
    showAtDropdown.value = false
    nextTick(() => {
      goalTextareaRef.value?.focus()
      const newPos = atInsertStart.value + insertText.length
      goalTextareaRef.value?.setSelectionRange(newPos, newPos)
    })
  } else {
    const raw = groupNextPrompt.value
    const before = raw.slice(0, atInsertStart.value)
    const after = raw.slice(atSelectionEnd.value)
    groupNextPrompt.value = before + insertText + after
    showAtDropdown.value = false
    nextTick(() => {
      nextPromptTextareaRef.value?.focus()
      const newPos = atInsertStart.value + insertText.length
      nextPromptTextareaRef.value?.setSelectionRange(newPos, newPos)
    })
  }
}

function onAtKeydown(_source: 'goal' | 'nextPrompt', e: KeyboardEvent) {
  if (!showAtDropdown.value || atMentionOptions.value.length === 0) return
  if (e.key === 'ArrowDown') {
    e.preventDefault()
    atSelectedIndex.value = (atSelectedIndex.value + 1) % atMentionOptions.value.length
    return
  }
  if (e.key === 'ArrowUp') {
    e.preventDefault()
    atSelectedIndex.value = (atSelectedIndex.value - 1 + atMentionOptions.value.length) % atMentionOptions.value.length
    return
  }
  if (e.key === 'Escape') {
    showAtDropdown.value = false
  }
}

const groupInputIsComposing = ref(false)

function onGroupCompositionStart() {
  groupInputIsComposing.value = true
}

function onGroupCompositionEnd() {
  // 某些输入法会在 compositionend 后紧跟一次 enter keydown；
  // 这里放到下一个 tick 再关闭标记，避免误发送。
  setTimeout(() => {
    groupInputIsComposing.value = false
  }, 0)
}

function onGroupInputEnter(e: KeyboardEvent) {
  // 输入法联想/上屏中按回车：不发送
  // 部分浏览器会在 keydown 上带 isComposing 标志
  if ((e as any)?.isComposing || groupInputIsComposing.value) {
    return
  }
  if (showAtDropdown.value && atMentionOptions.value[atSelectedIndex.value]) {
    selectMention(atMentionOptions.value[atSelectedIndex.value])
    return
  }
  sendGroupMessage()
}

function closeAtDropdownOnBlur() {
  setTimeout(() => {
    showAtDropdown.value = false
  }, 150)
}

/** 有讨论目标、提示词或文件引用即可发送 */
const canSend = computed(
  () =>
    !!(
      (groupDiscussionGoal.value || '').trim() ||
      (groupNextPrompt.value || '').trim() ||
      attachedFiles.value.length
    ),
)

/** 展示时去掉「【讨论目标】」前缀，不在前端显示 */
function stripDiscussionGoalForDisplay(content: string): string {
  const raw = (content ?? '').trim()
  if (!raw) return ''
  const fileRefMatches = Array.from(raw.matchAll(/【文件引用：([^】]+)】/g))
  const fileExpandedBlockRegex = /(?:^|\n)\[文件:\s*[^\]]+\][\s\S]*?(?=\n【文件引用：|\n【给下一 DHA 的提示】|$)/g
  const prefix = '【讨论目标】'
  const withoutGoalPrefix = raw.startsWith(prefix)
    ? raw.slice(prefix.length).replace(/^\s*\n?/, '').trim()
    : raw
  // 用户消息展示中，隐藏系统注入片段，避免把文件标签/解析痕迹展示给用户。
  const cleaned = withoutGoalPrefix
    .replace(/(?:^|\n{2,})【给下一 DHA 的提示】[\s\S]*?(?=\n{2,}【文件引用：|$)/g, '')
    // 隐藏文件引用标签（如：【文件引用：test.md｜notes/test.md】）
    .replace(/(?:^|\n)【文件引用：[^】]+】/g, '')
    // 隐藏“文件内容已解析”提示行
    .replace(/(?:^|\n)【文件内容已解析】/g, '')
    // 隐藏展开痕迹与展开正文（如：[文件: notes/test.md] + 后续解析内容）
    .replace(fileExpandedBlockRegex, '')
    // 折叠多余空行
    .replace(/\n{3,}/g, '\n\n')
    .replace(/^\s+|\s+$/g, '')
  if (!cleaned && fileRefMatches.length) {
    const refs = fileRefMatches
      .map((m) => {
        const payload = String(m[1] || '').trim()
        if (!payload) return ''
        const parts = payload.split('｜').map((x) => x.trim()).filter(Boolean)
        // 优先显示真实路径（竖线后半段），其次退回原值
        const path = parts.length >= 2 ? parts[1] : parts[0]
        return path ? `【文件引用：${path}】` : ''
      })
      .filter(Boolean)
    if (refs.length) return refs.join('\n')
  }
  return cleaned
}

/** 压缩空行并把所有换行替换为空格，用于用户/主持人纯文本展示 */
/** 用户气泡：保留 Shift+Enter 换行；仅做讨论目标剥离与轻微整理 */
function formatUserBubbleForDisplay(content: string): string {
  let s = stripDiscussionGoalForDisplay(content || '')
  s = s.replace(/\n{3,}/g, '\n\n')
  return s.trimEnd()
}

/** 判断是否是“短单行”文案（无换行），短句强制单行不换行 */
function isShortSingleLine(text: string): string | null {
  const t = (text || '').trim()
  if (!t || t.includes('\n')) return null
  return t.length <= 12 ? 'group-chat-plain-text-nowrap' : null
}

/** 提取用户消息中的文件引用名（用于标签展示） */
function extractUserFileReferenceNames(content: string): string[] {
  if (!content) return []
  const matches = Array.from(String(content).matchAll(/【文件引用：([^】]+)】/g))
  const names = matches
    .map((m) => {
      const payload = String(m?.[1] || '').trim()
      if (!payload) return ''
      const parts = payload.split('｜').map((x) => x.trim()).filter(Boolean)
      if (!parts.length) return ''
      return parts[0] || parts[parts.length - 1] || ''
    })
    .filter(Boolean)
  return [...new Set(names)]
}

/** 从主持人消息正文中解析 dha-xxx id（兜底：后端未带 suggested_add_agent_ids 时仍能显示邀请条） */
function parseAgentIdsFromHostContent(content: string | null | undefined): string[] {
  if (!content) return []
  const matches = content.match(/agent-[a-zA-Z0-9\-]+/gi) || []
  return [...new Set(matches)]
}

function resolveSuggestedIdsFromPayload(payload: Record<string, unknown> | null | undefined): string[] {
  if (!payload) return []
  // 场景协作：名单固定，不信任后端/正文里的招募字段，避免误显「建议邀请」条
  if (String(groupDetail.value?.orchestration_profile || '').toLowerCase() === 'scene') {
    return []
  }
  const direct = extractSuggestedAddIds(payload)
  const aliasMap = buildExpertAliasMap()
  const inGroup = new Set((groupDetail.value?.agent_ids || []).map((id) => toAgentStyleId(id)))
  const normalize = (ids: string[]) => {
    const uniq = [...new Set((ids || [])
      .map((id) => aliasMap.get(String(id || '').trim()) || '')
      .filter((id) => !!id && !inGroup.has(toAgentStyleId(id))))]
    return uniq.slice(0, 3)
  }
  if (direct.length) return normalize(direct)

  const role = String(payload.role || '')
  const content = String(payload.content || '')
  if (!content || (role !== 'host' && role !== 'assistant')) return []
  if (!/(建议邀请|邀请以下|推荐.*加入|补充.*专家|加入讨论)/.test(content)) return []
  return normalize(parseAgentIdsFromHostContent(content))
}

watch(
  () => groupDetail.value?.messages,
  (messages) => {
    const shouldFollow = isNearGroupBottom()
    groupDisplayMessages.value = Array.isArray(messages) ? [...messages] : []
    // 从历史/刷新加载后需重新水合受保护下载地址的图片（仅流式结束回调不够）
    nextTick(() => {
      scheduleHydrateAuthImages()
      if (shouldFollow) scrollGroupToBottomIfNear()
    })
    // 不再从历史首条用户消息回填输入框，避免发送后又被自动填充回来
    // 0 成员时：若最后一条主持人消息没有 suggested_add_agent_ids，从正文解析 dha-xxx 以显示「同意并邀请」条
    const dhaIds = groupDetail.value?.agent_ids ?? []
    if (dhaIds.length === 0 && Array.isArray(messages) && messages.length) {
      const lastHost = [...messages].reverse().find((m: { role?: string }) => m.role === 'host')
      const lastMsg = lastHost as {
        suggested_add_agent_ids?: string[]
        suggested_add_agent_id?: string
        content?: string
      } | undefined
      if (lastMsg) {
        const suggestedIds = extractSuggestedAddIds(lastMsg as Record<string, unknown>)
        if (suggestedIds.length) {
          groupSuggestedAddDhaIds.value = resolveSuggestedIdsFromPayload(lastMsg as Record<string, unknown>)
        } else if (lastMsg.content) {
          const aliasMap = buildExpertAliasMap()
          const parsed = parseAgentIdsFromHostContent(lastMsg.content)
            .map((id) => aliasMap.get(id) || '')
            .filter(Boolean)
          if (parsed.length) groupSuggestedAddDhaIds.value = parsed
        }
      }
    }
  },
  { immediate: true }
)

// 切换会话时，清空上一场的「下一 DHA 提示词」、文件引用等状态，避免串场
watch(
  () => props.selectedGroupSessionId,
  () => {
    groupDiscussionGoal.value = null
    groupNextPrompt.value = ''
    attachedFiles.value = []
    groupWaitingForUser.value = false
    groupTurnLimitReached.value = false
    groupSuggestedNextSpeaker.value = null
    groupSuggestedAddDhaIds.value = []
    groupNextSpeakerOverride.value = ''
    clearGroupWorkspacePreviewState()
    groupWorkspacePath.value = ''
  }
)

watch(
  () => [showGroupWorkspace.value, groupDetail.value?.id] as const,
  ([show, id]) => {
    if (show && id) {
      groupWorkspacePath.value = ''
      clearGroupWorkspacePreviewState()
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

function goGroupWorkspaceUp() {
  if (!groupWorkspacePath.value) return
  const cur = groupWorkspacePath.value.replace(/\/+$/, '')
  const parent = cur.includes('/') ? cur.slice(0, cur.lastIndexOf('/')) : ''
  clearGroupWorkspacePreviewState()
  groupWorkspacePath.value = parent
  loadGroupWorkspace()
}

function groupWorkspaceDownloadUrl(filePath: string) {
  const id = groupDetail.value?.id
  if (!id) return '#'
  return `/api/workspaces/${encodeURIComponent(id)}/files/download?path=${encodeURIComponent(filePath)}`
}

async function downloadGroupWorkspaceFile(e: { name: string; path: string; is_dir?: boolean }) {
  if (!e?.path || e.is_dir) return
  const url = groupWorkspaceDownloadUrl(e.path)
  if (!url || url === '#') return

  try {
    const r = await fetch(url)
    if (!r.ok) throw new Error(`HTTP ${r.status}`)

    const blob = await r.blob()
    const objUrl = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = objUrl
    a.download = e.name || e.path.split('/').pop() || 'download'
    a.rel = 'noopener'
    a.style.display = 'none'
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(objUrl)
  } catch {
    alert('下载失败，请检查网络或登录状态')
  }
}

async function createGroupWorkspaceDir() {
  const id = groupDetail.value?.id
  if (!id) return
  const name = window.prompt('新建文件夹名称', '新文件夹')?.trim()
  if (!name) return
  try {
    const pathParam = groupWorkspacePath.value ? `?path=${encodeURIComponent(groupWorkspacePath.value)}` : ''
    const r = await fetch(`/api/workspaces/${encodeURIComponent(id)}/files/mkdir${pathParam}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ dirname: name }),
    })
    const j = await r.json().catch(() => ({}))
    if (j?.status === 'ok') {
      await loadGroupWorkspace()
    } else {
      alert((j as { detail?: string }).detail || '新建文件夹失败')
    }
  } catch {
    alert('新建文件夹失败，请检查网络或后端')
  }
}

async function createGroupWorkspaceFile() {
  const id = groupDetail.value?.id
  if (!id) return
  const defaultName = groupWorkspacePath.value ? 'note.md' : 'novel-workflow-tasks.md'
  const name = window.prompt('新建文件名（相对当前目录，如 novel-workflow-tasks.md）', defaultName)?.trim()
  if (!name) return
  try {
    const pathParam = groupWorkspacePath.value ? `?path=${encodeURIComponent(groupWorkspacePath.value)}` : ''
    const r = await fetch(`/api/workspaces/${encodeURIComponent(id)}/files${pathParam}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ filename: name, content: '' }),
    })
    const j = await r.json().catch(() => ({}))
    if (j?.status === 'ok') {
      await loadGroupWorkspace()
    } else {
      alert((j as { detail?: string }).detail || '新建文件失败')
    }
  } catch {
    alert('新建文件失败，请检查网络或后端')
  }
}

async function onGroupWorkspaceUpload(ev: Event) {
  const input = ev.target as HTMLInputElement
  const id = groupDetail.value?.id
  if (!id || !input.files?.length || groupWorkspaceUploading.value) return
  const file = input.files[0]
  groupWorkspaceUploading.value = true
  groupWorkspaceUploadingName.value = file.name || '本地文件'
  groupWorkspaceUploadProgress.value = null
  try {
    const j = await uploadWorkspaceFile(id, file, groupWorkspacePath.value, ({ percent }) => {
      groupWorkspaceUploadProgress.value = percent
    })
    if (j?.status === 'ok') {
      await loadGroupWorkspace()
    } else {
      alert((j as { detail?: string }).detail || '上传失败')
    }
  } catch (e) {
    alert(e instanceof Error ? e.message : '上传失败，请检查网络或后端')
  } finally {
    groupWorkspaceUploading.value = false
    groupWorkspaceUploadingName.value = ''
    groupWorkspaceUploadProgress.value = null
    input.value = ''
  }
}

async function renameGroupWorkspaceEntry(e: { name: string; path: string; is_dir: boolean }) {
  if (e.is_dir) return
  const id = groupDetail.value?.id
  if (!id) return
  const name = window.prompt('重命名为', e.name)?.trim()
  if (name == null || name === '' || name === e.name) return
  try {
    const r = await fetch(`/api/workspaces/${encodeURIComponent(id)}/files/rename?path=${encodeURIComponent(e.path)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ new_name: name }),
    })
    const j = await r.json().catch(() => ({}))
    if (j?.status === 'ok') {
      if (groupWorkspacePreviewPath.value === e.path) {
        clearGroupWorkspacePreviewState()
      }
      await loadGroupWorkspace()
    } else {
      alert((j as { detail?: string }).detail || '重命名失败')
    }
  } catch {
    alert('重命名失败，请检查网络或后端')
  }
}

async function deleteGroupWorkspaceEntry(e: { name: string; path: string; is_dir: boolean }) {
  const id = groupDetail.value?.id
  if (!id) return
  const label = e.is_dir ? `目录「${e.name}」` : `文件「${e.name}」`
  const msg = e.is_dir
    ? '确定要删除该空目录吗？非空目录请先清空内容。'
    : `确定要删除 ${label} 吗？此操作不可恢复。`
  if (!window.confirm(msg)) return
  try {
    const r = await fetch(`/api/workspaces/${encodeURIComponent(id)}/files/content?path=${encodeURIComponent(e.path)}`, {
      method: 'DELETE',
    })
    const j = await r.json().catch(() => ({}))
    if (j?.status === 'ok') {
      if (groupWorkspacePreviewPath.value === e.path) {
        clearGroupWorkspacePreviewState()
      }
      await loadGroupWorkspace()
    } else {
      alert((j as { detail?: string }).detail || '删除失败')
    }
  } catch {
    alert('删除失败，请检查网络或后端')
  }
}

const TEXT_EXT = ['.md', '.txt', '.json', '.jsonl', '.py', '.js', '.ts', '.vue', '.html', '.css', '.yaml', '.yml', '.xml', '.csv', '.log', '.docx']
const IMAGE_EXT = ['.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp', '.svg']
function isTextFile(name: string) {
  const ext = name.includes('.') ? name.slice(name.lastIndexOf('.')).toLowerCase() : ''
  return TEXT_EXT.includes(ext)
}
function isImageFile(name: string) {
  const ext = name.includes('.') ? name.slice(name.lastIndexOf('.')).toLowerCase() : ''
  return IMAGE_EXT.includes(ext)
}

const groupWorkspacePreviewIsImage = computed(() => isImageFile(groupWorkspacePreviewName.value))

function startWorkspacePreviewEdit() {
  groupWorkspacePreviewEditContent.value = groupWorkspacePreviewContent.value
  groupWorkspacePreviewEditing.value = true
}

function cancelWorkspacePreviewEdit() {
  groupWorkspacePreviewEditing.value = false
}

async function saveWorkspacePreviewEdit() {
  const id = groupDetail.value?.id
  if (!id || !groupWorkspacePreviewPath.value) return
  try {
    const r = await fetch(`/api/workspaces/${encodeURIComponent(id)}/files/content?path=${encodeURIComponent(groupWorkspacePreviewPath.value)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content: groupWorkspacePreviewEditContent.value }),
    })
    const j = await r.json().catch(() => ({}))
    if ((j as { status?: string }).status === 'ok') {
      groupWorkspacePreviewContent.value = groupWorkspacePreviewEditContent.value
      groupWorkspacePreviewEditing.value = false
    } else {
      alert((j as { detail?: string }).detail || '保存失败')
    }
  } catch {
    alert('保存失败，请检查网络或后端')
  }
}

async function previewWorkspaceFile(e: { name: string; path: string }) {
  // 若当前为收起状态，自动展开预览并恢复上次宽度
  if (groupWorkspacePreviewCollapsed.value) {
    groupWorkspacePreviewCollapsed.value = false
    groupWorkspaceWidth.value = lastExpandedWorkspaceWidth.value || 672
  }
  revokeGroupWorkspacePreviewBlob()
  groupWorkspacePreviewPath.value = e.path
  groupWorkspacePreviewName.value = e.name
  groupWorkspacePreviewContent.value = ''
  groupWorkspacePreviewImageUrl.value = ''
  groupWorkspacePreviewEditing.value = false
  if (isImageFile(e.name)) {
    groupWorkspacePreviewLoading.value = true
    try {
      const url = groupWorkspaceDownloadUrl(e.path)
      const r = await fetch(url)
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      const blob = await r.blob()
      const objUrl = URL.createObjectURL(blob)
      groupWorkspacePreviewObjectUrl = objUrl
      groupWorkspacePreviewImageUrl.value = objUrl
    } catch {
      groupWorkspacePreviewContent.value = '[ 图片预览失败，请使用上方「下载」查看 ]'
      groupWorkspacePreviewImageUrl.value = ''
    } finally {
      groupWorkspacePreviewLoading.value = false
    }
    return
  }
  if (!isTextFile(e.name)) {
    groupWorkspacePreviewContent.value = '[ 非文本文件，请点击「下载」查看 ]'
    return
  }
  groupWorkspacePreviewLoading.value = true
  try {
    const url = groupWorkspaceDownloadUrl(e.path)
    const r = await fetch(url)
    const text = await r.text()
    groupWorkspacePreviewContent.value = text || '(空)'
  } catch {
    groupWorkspacePreviewContent.value = '[ 加载失败 ]'
  } finally {
    groupWorkspacePreviewLoading.value = false
  }
}

async function loadInsertFileEntries() {
  const id = groupDetail.value?.id
  if (!id) {
    insertFileEntries.value = []
    return
  }
  insertFileLoading.value = true
  insertFileEntries.value = []
  try {
    const path = insertFileBrowsePath.value ? `?path=${encodeURIComponent(insertFileBrowsePath.value)}` : ''
    const r = await fetch(`/api/workspaces/${encodeURIComponent(id)}/files${path}`)
    const j = await r.json().catch(() => null)
    const raw = (j?.status === 'ok' && Array.isArray(j?.data?.entries)) ? j.data.entries : []
    const mapped = (raw as { name: string; path: string; is_dir?: boolean }[])
      .map((e) => ({
        name: e.name,
        path: e.path,
        is_dir: !!e.is_dir,
      }))
    mapped.sort((a, b) => {
      if (a.is_dir !== b.is_dir) return a.is_dir ? -1 : 1
      return a.name.localeCompare(b.name)
    })
    insertFileEntries.value = mapped
  } finally {
    insertFileLoading.value = false
  }
}

async function insertFileContent(e: { name: string; path: string }) {
  // 仅记录文件引用，不直接把内容插入到输入框
  if (!attachedFiles.value.find((f) => f.path === e.path)) {
    attachedFiles.value.push({ name: e.name, path: e.path })
  }
  showInsertFile.value = false
  showInsertFileModal.value = false
}

function defaultDhaFilename(msg: MsgExt & { agent_id?: string }): string {
  const name = (groupDetail.value?.agent_map || {})[msg.agent_id || '']?.name || 'dha'
  const ts = new Date().toISOString().slice(0, 19).replace(/[-:T]/g, '').slice(0, 12)
  return `dha-${name}-${ts}.md`
}

async function saveDhaMessageToFile(msg: MsgExt & { content?: string; agent_id?: string }) {
  const id = groupDetail.value?.id
  const content = (msg.content || '').trim()
  if (!id || !content) return
  const defaultName = defaultDhaFilename(msg)
  const filename = window.prompt('保存为工作区文件', defaultName)?.trim() || defaultName
  if (!filename) return
  try {
    const r = await fetch(`/api/workspaces/${encodeURIComponent(id)}/files`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ filename, content }),
    })
    const j = await r.json().catch(() => null)
    if (r.ok && j?.status === 'ok') {
      showGroupWorkspace.value = true
      loadGroupWorkspace()
    } else {
      alert(j?.detail || '保存失败')
    }
  } catch {
    alert('保存失败')
  }
}

async function deleteGroupMessage(msg: { message_id?: string; role?: string }) {
  const id = groupDetail.value?.id
  const messageId = msg?.message_id
  if (!id || !messageId) return
  if (!window.confirm('确定从会话中彻底删除该条发言？删除后下一轮专家将不再看到这条内容。')) return
  try {
    const r = await fetch(`/api/sessions/${encodeURIComponent(id)}/messages/${encodeURIComponent(messageId)}`, {
      method: 'DELETE',
    })
    const j = await r.json().catch(() => null)
    if (r.ok && j?.status === 'ok') {
      await loadGroupDetail()
    } else {
      alert(j?.detail || '删除失败')
    }
  } catch {
    alert('删除失败')
  }
}

function onGroupWorkspaceResizeMouseDown(e: MouseEvent) {
  e.preventDefault()
  isResizingWorkspace.value = true
  workspaceResizeStartX = e.clientX
  workspaceResizeStartWidth = groupWorkspaceWidth.value
  window.addEventListener('mousemove', onGroupWorkspaceResizeMouseMove)
  window.addEventListener('mouseup', onGroupWorkspaceResizeMouseUp)
}

function onGroupWorkspaceResizeMouseMove(e: MouseEvent) {
  if (!isResizingWorkspace.value) return
  const delta = workspaceResizeStartX - e.clientX
  // 最小值与 toggleWorkspacePreview() 保持一致，否则首次拖动会被强行跳到更大的宽度
  const next = Math.min(840, Math.max(320, workspaceResizeStartWidth + delta))
  groupWorkspaceWidth.value = next
}

function onGroupWorkspaceResizeMouseUp() {
  if (!isResizingWorkspace.value) return
  isResizingWorkspace.value = false
  window.removeEventListener('mousemove', onGroupWorkspaceResizeMouseMove)
  window.removeEventListener('mouseup', onGroupWorkspaceResizeMouseUp)
}

function onWorkspaceInnerResizeMouseDown(e: MouseEvent) {
  e.preventDefault()
  if (groupWorkspacePreviewCollapsed.value) return
  isResizingWorkspaceInner.value = true
  workspaceInnerResizeStartX = e.clientX
  workspaceInnerResizeStartWidth = groupWorkspaceListWidth.value
  window.addEventListener('mousemove', onWorkspaceInnerResizeMouseMove)
  window.addEventListener('mouseup', onWorkspaceInnerResizeMouseUp)
}

function onWorkspaceInnerResizeMouseMove(e: MouseEvent) {
  if (!isResizingWorkspaceInner.value) return
  const delta = e.clientX - workspaceInnerResizeStartX
  const next = Math.min(320, Math.max(140, workspaceInnerResizeStartWidth + delta))
  groupWorkspaceListWidth.value = next
}

function onWorkspaceInnerResizeMouseUp() {
  if (!isResizingWorkspaceInner.value) return
  isResizingWorkspaceInner.value = false
  window.removeEventListener('mousemove', onWorkspaceInnerResizeMouseMove)
  window.removeEventListener('mouseup', onWorkspaceInnerResizeMouseUp)
}

function toggleWorkspacePreview() {
  if (!groupWorkspacePreviewCollapsed.value) {
    // 从展开切换为收起：记录当前宽度，并把工作区缩到仅文件列表宽度，释放更多空间给对话区
    lastExpandedWorkspaceWidth.value = groupWorkspaceWidth.value
    groupWorkspaceWidth.value = Math.max(320, groupWorkspaceListWidth.value + 40)
    groupWorkspacePreviewCollapsed.value = true
  } else {
    // 从收起切回展开：恢复之前的工作区宽度
    groupWorkspacePreviewCollapsed.value = false
    groupWorkspaceWidth.value = lastExpandedWorkspaceWidth.value || 672
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

/** 将目标消息放到容器中下区域，便于持续观察流式输出 */
function scrollGroupRowToLowerMiddle(row: HTMLElement) {
  nextTick(() => {
    const sc = groupMessagesRef.value
    if (!sc) return
    const desiredViewportRatio = 0.68
    const desiredTop = row.offsetTop - sc.clientHeight * desiredViewportRatio + row.clientHeight * 0.5
    const maxTop = Math.max(0, sc.scrollHeight - sc.clientHeight)
    const nextTop = Math.max(0, Math.min(desiredTop, maxTop))
    sc.scrollTo({ top: nextTop, behavior: 'smooth' })
  })
}

function scrollLatestAssistantRowToLowerMiddle() {
  nextTick(() => {
    const sc = groupMessagesRef.value
    if (!sc) return
    const rows = Array.from(sc.querySelectorAll('.group-chat-msg-row-other')) as HTMLElement[]
    const last = rows[rows.length - 1]
    if (!last) return
    scrollGroupRowToLowerMiddle(last)
  })
}

/** 专家/主持人等 assistant 消息落地后滚入可视区（优先按 message_id 定位，否则滚容器底部） */
function scrollGroupAssistantMessageIntoView(data: Record<string, unknown>) {
  const mid = typeof data.message_id === 'string' ? data.message_id.trim() : ''
  nextTick(() => {
    const sc = groupMessagesRef.value
    if (!sc) return
    if (mid) {
      const el = sc.querySelector(`[data-message-id="${CSS.escape(mid)}"]`) as HTMLElement | null
      if (el) {
        scrollGroupRowToLowerMiddle(el)
        return
      }
    }
    scrollLatestAssistantRowToLowerMiddle()
  })
}

type GroupMessage = GroupDetail['messages'][number] & { _streaming?: boolean }

/** 成员加入/移出等一行系统提示（不占头像栏、居中灰条） */
function isMemberJoinedMessage(msg: GroupMessage): boolean {
  const ext = msg as GroupMessage & MsgExt
  const et = ext.event_type
  return msg.role === 'host' && (et === 'member_joined' || et === 'member_left')
}

/** 当前处于流式占位状态的“正在输出”的专家（最后一条 _streaming 置为 true 的 assistant） */
const activeStreamingMessage = computed<GroupMessage | null>(() => {
  const list = groupDisplayMessages.value || []
  for (let i = list.length - 1; i >= 0; i--) {
    const m = list[i] as GroupMessage
    if (m?.role === 'assistant' && m?._streaming) return m
  }
  return null
})

const currentActiveStreamingMessage = computed<GroupMessage | null>(() => currentGroupStreaming.value ? activeStreamingMessage.value : null)
const activeStreamingDhaId = computed(() => (
  currentActiveStreamingMessage.value?.agent_id
  || currentGroupStreamState.value?.agentId
  || (lastRoute.value?.sessionId === props.selectedGroupSessionId ? lastRoute.value?.expertId || '' : '')
))

function displayGroupSpeakerName(agentId: string): string {
  const id = (agentId || '').trim()
  if (!id) return ''
  if (id === 'host') return hostDisplayName.value || DEFAULT_HOST_DISPLAY_NAME
  // 1) 资源中心实例列表（最稳定，含中文名）
  const fromInstances = (props.dhaInstances || []).find((x) => x.agent_id === id)?.name
  if (fromInstances && fromInstances.trim()) return fromInstances.trim()
  // 2) 群聊详情 agent_map（后端下发）
  const fromMap = (groupDetail.value?.agent_map || {})[id]?.name
  if (fromMap && fromMap.trim()) return fromMap.trim()
  // 3) 最后兜底：避免直接暴露 agent-xxxx（用户体感像“编号闪烁”）
  if (/^agent-[0-9a-f]{6,}$/i.test(id)) return '专家'
  return id
}

const activeStreamingSpeakerName = computed(() => {
  const id = activeStreamingDhaId.value
  if (!id) return ''
  return displayGroupSpeakerName(id)
})

/**
 * 工具栏「当前焦点角色」：
 * - 流式中：当前执行者（active -> lastRoute）
 * - 空闲中：下一位；若为 user，则显示待续跑专家（无则主持人）
 */
const focusRoleForToolbar = computed(() => {
  if (groupStreaming.value) {
    const a = activeStreamingDhaId.value
    if (a) return a
    const rid = (lastRoute.value?.sessionId === props.selectedGroupSessionId ? lastRoute.value?.expertId || '' : '').trim()
    if (isToolbarRoleValid(rid)) return rid
    return 'host'
  }

  const eff = effectiveNextSpeaker.value
  if (eff === 'user') {
    const resume = (groupResumeTargetDhaId.value || '').trim()
    if (isToolbarRoleValid(resume)) return resume
    return toolbarLeaderFallbackId()
  }
  if (isToolbarRoleValid(eff)) return eff
  return 'host'
})

const focusRoleNameForToolbar = computed(() => {
  const id = focusRoleForToolbar.value
  if (id) {
    const n = displayGroupSpeakerName(id).trim()
    if (n) return n
  }
  return (hostDisplayName.value || DEFAULT_HOST_DISPLAY_NAME).trim() || '四九'
})

const focusRoleShowHostAvatar = computed(() => {
  const id = focusRoleForToolbar.value
  if (!id) return true
  if (id === 'host') return true
  const lid = (leaderDisplayId.value || '').trim()
  return Boolean(lid && lid !== 'host' && id === lid)
})

/** 兼容模板中的既有命名 */
const toolbarDisplaySpeakerId = computed(() => focusRoleForToolbar.value)
const toolbarDisplayShowHostAvatar = computed(() => focusRoleShowHostAvatar.value)
const toolbarDisplayLabelText = computed(() => {
  const n = focusRoleNameForToolbar.value.trim()
  return n || (hostDisplayName.value || DEFAULT_HOST_DISPLAY_NAME).trim() || '四九'
})

/** 流式脉冲点：基于已到达的内容长度滚动切换 */
const streamingPulse = computed(() => {
  const len = currentActiveStreamingMessage.value?.content?.length || 0
  const bucket = Math.floor(len / 20) % 4
  return ['', '.', '..', '...'][bucket] || ''
})

/** 流式展示：追加一条 content chunk 到当前专家占位消息，或新建占位 */
function appendStreamingContent(dhaId: string, text: string) {
  const list = [...groupDisplayMessages.value]
  const last = list[list.length - 1] as (GroupMessage & { _streaming?: boolean }) | undefined
  const appendToExisting =
    last?.role === 'assistant' && last?.agent_id === dhaId && (last as { _streaming?: boolean })._streaming
  if (appendToExisting) {
    const next: GroupDetail['messages'] = [...list.slice(0, -1), { ...last, content: (last.content || '') + text } as GroupMessage]
    groupDisplayMessages.value = next
  } else {
    // 确保同一时间只有一个“正在输出”的占位消息（只影响 UI 指示）
    const cleared = list.map((m) => ((m as GroupMessage)._streaming ? ({ ...(m as GroupMessage), _streaming: false } as GroupMessage) : m))
    groupDisplayMessages.value = [...cleared, { role: 'assistant', agent_id: dhaId, content: text, _streaming: true } as unknown as GroupMessage]
    scrollLatestAssistantRowToLowerMiddle()
  }
  scrollLatestAssistantRowToLowerMiddle()
  // markdown v-html 渲染完成后，用 fetch+blob 显示受保护图片
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

function consumeStreamingStatusContent(data: { text?: string; agent_id?: string; meta?: { phase?: string } }, sessionId = props.selectedGroupSessionId || ''): boolean {
  const phase = String(data?.meta?.phase || '').trim()
  if (!phase) return false
  if (phase === 'file_resolving' || phase === 'preparing') {
    patchGroupStreamState(sessionId, { phase: '正在处理文件引用…' })
    return true
  }
  if (phase === 'file_resolved' || phase === 'file_parsed') {
    patchGroupStreamState(sessionId, { phase: '文件引用已处理' })
    return true
  }
  if (phase === 'tool_running' || phase === 'tool_pending') {
    patchGroupStreamState(sessionId, { phase: '技能任务运行中，完成后会继续回复…' })
    return true
  }
  if (phase === 'agent_waiting') {
    patchGroupStreamState(sessionId, { phase: '仍在等待技能任务完成…' })
    return true
  }
  return false
}

function handleStreamMessageEvent(data: Record<string, unknown>, state: { sawExpertAssistantMessageThisRun: boolean }, sessionId = props.selectedGroupSessionId || '') {
  if (sessionId && props.selectedGroupSessionId !== sessionId) return
  patchGroupStreamState(sessionId, { phase: '正在生成回复…' })
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
      groupSuggestedAddDhaIds.value = []
      emit('dha-added')
      loadGroupDetail()
    }
    const suggestedIds = resolveSuggestedIdsFromPayload(data)
    if (suggestedIds.length) {
      groupSuggestedAddDhaIds.value = suggestedIds
      clearStreamingPlaceholders()
      patchGroupStreamState(sessionId, { phase: '等待你确认邀请…' })
    }
  }
}

function handleStreamEndEvent(endData: Record<string, unknown>, state: { sawExpertAssistantMessageThisRun: boolean }, sessionId = props.selectedGroupSessionId || '') {
  if (sessionId && props.selectedGroupSessionId !== sessionId) return
  applyOrchestrationEndMeta(endData)
  if (endData.waiting_for_user) {
    groupTurnLimitReached.value = !!endData.turns_limit_reached
    groupWaitingForUser.value = !!endData.turns_limit_reached
    groupSuggestedNextSpeaker.value = endData.suggested_next_speaker != null
      ? String(endData.suggested_next_speaker)
      : null
    if (extractAutoInvitedIds(endData).length) {
      groupSuggestedAddDhaIds.value = []
      emit('dha-added')
      loadGroupDetail()
    }
    const suggestedIds = resolveSuggestedIdsFromPayload(endData)
    if (suggestedIds.length) {
      groupSuggestedAddDhaIds.value = suggestedIds
      clearStreamingPlaceholders()
      patchGroupStreamState(sessionId, { phase: '等待你确认邀请…' })
    }
    if (endData.next_prompt) {
      groupNextPrompt.value = String(endData.next_prompt || '').trim()
    }
    if (endData.suggested_next_speaker === 'user' || endData.discussion_ended) {
      attachedFiles.value = []
    }
    if (groupTurnLimitReached.value) {
      window.alert('已自动暂停：本次任务中专家已连续运行 32 轮。\n\n如需继续，请检查并必要时编辑「下一专家提示词」，然后点击「确认并继续」。')
    }
    if (!endData.turns_limit_reached) {
      const suggestedNext = endData.suggested_next_speaker
      if (suggestedNext && suggestedNext !== 'user') {
        nextTick(() => confirmGroupNext(String(suggestedNext)))
      }
    }
  }
  if (endData.discussion_ended) {
    attachedFiles.value = []
  }
  if (state.sawExpertAssistantMessageThisRun) {
    autoSwitchHint.value = null
  }
}

const runGroupStream = createGroupChatStreamRunner({
  isSelectedSession: (sessionId) => props.selectedGroupSessionId === sessionId,
  setStreamingPhase: (text, sessionId) => { patchGroupStreamState(sessionId || props.selectedGroupSessionId || '', { phase: text }) },
  appendHostError: (content) => {
    groupDisplayMessages.value = [
      ...groupDisplayMessages.value,
      { message_id: `msg-${Date.now()}`, role: 'host', content } as unknown as GroupMessage,
    ]
  },
  updateAutoSwitchHint,
  consumeStreamingStatusContent,
  appendStreamingContent,
  handleStreamMessageEvent,
  handleStreamEndEvent,
})

function createClientMessageId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return `cm-${crypto.randomUUID()}`
  }
  return `cm-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

/** 按提示词工程拼接：目标与给下一 DHA 的指令；不再在前端添加「【讨论目标】」前缀 */
function builtMessage(): string {
  // 保留用户通过 Shift+Enter 输入的换行，只做轻度规范化
  const rawGoal = groupDiscussionGoal.value || ''
  const goal = rawGoal
    .replace(/\r\n/g, '\n')
    .replace(/\r/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim()
  const prompt = (groupNextPrompt.value || '').trim()
  if (!goal && !prompt) return ''
  const parts: string[] = []
  if (goal) parts.push(goal)
  if (prompt) parts.push(`【给下一 DHA 的提示】\n${prompt}`)
  return parts.join('\n\n')
}

/** 发送前将所有文件引用展开为实际内容，并与当前输入拼接（群聊中不再展开，只保留标签，由 DHA 自己通过 filesystem_* 读取） */
async function buildMessageWithFiles(_detail: GroupDetail, base: string): Promise<string> {
  const fileRefs = attachedFiles.value.length
    ? '\n\n' + attachedFiles.value.map((f) => `【文件引用：${f.name}｜${f.path}】`).join('\n')
    : ''
  // 群聊场景：不在用户侧展开文件内容，只把可读标签附到发送文本中，
  // 由 DHA 通过 filesystem_* 工具按 path 主动读取。
  return `${base}${fileRefs}`.trim()
}

async function sendGroupMessage() {
  const detail = groupDetail.value
  if (!detail) return
  const rawInput = String(groupDiscussionGoal.value || '')
  const directive = parseAtSpeakerDirective(rawInput, detail)
  const hostTakeoverRequested = detectHostTakeoverIntent(rawInput)
  if (directive.override_next_speaker) groupNextSpeakerOverride.value = directive.override_next_speaker
  const base = builtMessage()
  const hasFiles = attachedFiles.value.length > 0
  if (!detail || groupStreaming.value || (!base && !hasFiles)) return
  autoSwitchHint.value = null
  lastSentDraft.value = {
    goal: String(groupDiscussionGoal.value || ''),
    nextPrompt: String(groupNextPrompt.value || ''),
    files: [...(attachedFiles.value || [])],
  }
  // 发送后输入框必须清空：前端不保留历史内容
  groupDiscussionGoal.value = ''
  groupNextPrompt.value = ''
  const { runToken, abort } = beginGroupStream(detail.id, '正在分配专家…')
  try {
    const msg = await buildMessageWithFiles(detail, base)
    const userMsg = { message_id: `msg-${Date.now()}`, role: 'user' as const, content: msg }
    groupDisplayMessages.value = [...groupDisplayMessages.value, userMsg]
    // 不再从首条用户消息回填讨论目标，避免重新把历史文本写回输入框
    scrollGroupToBottom()
    const body: Record<string, unknown> = {
      message: msg,
      client_message_id: createClientMessageId(),
      host_takeover_requested: hostTakeoverRequested,
    }
    if (groupNextSpeakerOverride.value) body.override_next_speaker = groupNextSpeakerOverride.value
    // 不在流开始时 emit，避免父组件提前 refresh 覆盖当前流式展示
    const shouldEmitMessageSent = await runGroupStream(detail.id, body, abort.signal)
    if (shouldEmitMessageSent) emit('message-sent')
  } catch (e) {
    console.error('群聊发送失败', e)
  } finally {
    if (isCurrentGroupRun(detail.id, runToken)) {
      clearStreamingPlaceholders()
      groupNextSpeakerOverride.value = ''
      finishGroupStream(detail.id, runToken)
    }
  }
}

function parseAtSpeakerDirective(raw: string, detail: GroupDetail): { override_next_speaker: string; cleaned_goal: string } {
  const s = (raw || '').trimStart()
  if (!s.startsWith('@')) return { override_next_speaker: '', cleaned_goal: raw }
  const firstLine = s.split('\n')[0] || ''
  const m = firstLine.match(/^@([^\s]+)\s+/)
  if (!m) return { override_next_speaker: '', cleaned_goal: raw }
  const token = (m[1] || '').trim()
  const rest = s.slice(m[0].length)
  if (!token) return { override_next_speaker: '', cleaned_goal: raw }

  if (token === '主持人' || token === (hostDisplayName.value || DEFAULT_HOST_DISPLAY_NAME)) {
    // @主持人 用于触发“主持人按需接管”，不做 override，也不从用户输入中移除该标记。
    return { override_next_speaker: '', cleaned_goal: raw }
  }
  if (token === '下一位') {
    const next = effectiveNextSpeaker.value
    return { override_next_speaker: next || '', cleaned_goal: rest }
  }
  const map = detail.agent_map || {}
  const hit = Object.entries(map).find(([, v]) => (v?.name || '').trim() === token)
  if (hit) return { override_next_speaker: hit[0], cleaned_goal: rest }
  const maybeId = token
  if ((detail.agent_ids || []).includes(maybeId)) return { override_next_speaker: maybeId, cleaned_goal: rest }
  return { override_next_speaker: '', cleaned_goal: raw }
}

function detectHostTakeoverIntent(raw: string): boolean {
  const text = (raw || '').trim()
  if (!text) return false
  if (text.includes('@主持人') || text.includes('@四九')) return true
  const hostName = (hostDisplayName.value || DEFAULT_HOST_DISPLAY_NAME || '').trim()
  const aliases = ['主持人', '四九']
  if (hostName && !aliases.includes(hostName)) aliases.push(hostName)
  const aliasPattern = aliases
    .map((x) => x.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
    .join('|')
  const summonPatterns = [
    new RegExp(`(请|让|由|麻烦|需要)?\\s*(${aliasPattern})\\s*(来|接管|安排|协调|分配|调度|负责|处理|决策)`, 'i'),
    new RegExp(`(请|让|由|麻烦|需要)\\s*(${aliasPattern})`, 'i'),
  ]
  return summonPatterns.some((re) => re.test(text))
}

async function stopGroupStream() {
  const id = props.selectedGroupSessionId || ''
  if (!id) return
  abortGroupStream(id)
  try {
    await fetch(`/api/sessions/${encodeURIComponent(id)}/chat/stop`, { method: 'POST' })
  } catch {
    // 本地先停止 UI；后端失败时下一次请求会重新同步状态。
  }
  clearStreamingPlaceholders()
}

/** 标准化为 GroupDetail，保证 messages/agent_map/agent_ids 必为数组/对象 */
function normalizeGroupDetail(raw: Record<string, unknown>, fallbackId: string): GroupDetail {
  const id = String(raw.id ?? fallbackId)
  const messages = Array.isArray(raw.messages) ? raw.messages as GroupDetail['messages'] : []
  const agent_map = (raw.agent_map && typeof raw.agent_map === 'object') ? (raw.agent_map as GroupDetail['agent_map']) : {}
  const agent_ids = Array.isArray(raw.agent_ids) ? (raw.agent_ids as string[]) : []
  const orch = String(raw.orchestration_profile ?? '').trim().toLowerCase()
  const runtime_state = (raw.runtime_state && typeof raw.runtime_state === 'object')
    ? (raw.runtime_state as GroupDetail['runtime_state'])
    : undefined
  return {
    id,
    title: String(raw.title ?? '群聊'),
    messages,
    agent_map,
    agent_ids,
    leader_agent_id: String(raw.leader_agent_id ?? ''),
    runtime_state,
    orchestration_profile: orch === 'scene' || orch === 'recruitment' ? orch : undefined,
  }
}

function hydrateRuntimeStateFromServer(detail: GroupDetail) {
  const rt = detail.runtime_state
  const st = groupStreamStates.value[detail.id]
  if (!rt?.running) {
    if (restoredRuntimePollSessionId === detail.id) clearRestoredRuntimePollTimer()
    if (st?.restored) patchGroupStreamState(detail.id, { streaming: false, phase: '', abort: null, agentId: '', skillId: '', restored: false })
    return
  }
  const phase = String(rt.phase || '').trim()
  const agentId = String(rt.agent_id || '').trim()
  const skillId = String(rt.skill_id || '').trim()
  const hasLocalAbort = Boolean(st?.streaming && st.abort)
  patchGroupStreamState(detail.id, {
    streaming: true,
    phase: phase === 'tool_running' ? '技能任务运行中，完成后会继续回复…' : '仍在等待技能任务完成…',
    abort: hasLocalAbort ? st?.abort || null : null,
    runToken: Number(groupStreamStates.value[detail.id]?.runToken || 0),
    agentId,
    skillId,
    restored: !hasLocalAbort,
  })
  if (agentId || skillId) {
    lastRoute.value = { sessionId: detail.id, expertId: agentId, skillId }
  }
  if (!hasLocalAbort) scheduleRestoredRuntimePoll(detail.id)
}

function parseGroupResponse(id: string, body: unknown): GroupDetail | null {
  if (body == null) return null
  if (Array.isArray(body)) {
    return normalizeGroupDetail({ id, title: '群聊', messages: body, agent_ids: [], agent_map: {} }, id)
  }
  if (typeof body !== 'object') return null
  const o = body as Record<string, unknown>
  // 后端标准返回：{ status: "ok", data: { id, title, messages, agent_map, agent_ids, ... } }
  if (o.status === 'ok' && o.data != null && typeof o.data === 'object') {
    return normalizeGroupDetail(o.data as Record<string, unknown>, id)
  }
  // 兼容直接返回会话对象（无 status/data 包裹）
  if (o.id != null && (Array.isArray(o.messages) || o.messages === undefined)) {
    return normalizeGroupDetail(o, id)
  }
  return null
}

async function loadGroupDetail(options: { silent?: boolean } = {}) {
  const id = props.selectedGroupSessionId
  if (!id) return
  const silent = !!options.silent
  if (!silent) {
    groupLoading.value = true
    groupError.value = null
  }
  try {
    const r = await fetch(`/api/sessions/${encodeURIComponent(id)}`)
    const body = await r.json().catch(() => null)
    const parsed = parseGroupResponse(id, body)
    // 仅当当前选中的仍是本次请求的 id 时才更新，避免竞态覆盖
    if (props.selectedGroupSessionId !== id) return
    if (parsed) {
      groupDetail.value = parsed
      hydrateRuntimeStateFromServer(parsed)
    } else {
      if (silent) return
      groupDetail.value = null
      groupError.value = !r.ok
        ? (r.status === 404 ? '会话不存在' : (body && typeof body === 'object' && 'detail' in body ? String((body as { detail?: string }).detail) : `请求失败 ${r.status}`))
        : (body && typeof body === 'object' && 'detail' in body ? String((body as { detail?: string }).detail) : '返回格式异常')
    }
  } catch {
    if (!silent && props.selectedGroupSessionId === id) {
      groupDetail.value = null
      groupError.value = '网络错误，请确认后端已启动（默认端口 8000）'
    }
  } finally {
    if (!silent) groupLoading.value = false
  }
}

watch(
  () => props.selectedGroupSessionId,
  (id) => {
    clearRestoredRuntimePollTimer()
    sessionMetaPopoverOpen.value = false
    unbindSessionMetaOutsideClick()
    if (id) {
      openGroupSessionEventsStream(id)
      groupError.value = null
      groupWaitingForUser.value = false
      groupSuggestedNextSpeaker.value = null
      groupSuggestedAddDhaIds.value = []
      loadGroupDetail()
    } else {
      closeGroupSessionEventsStream()
    }
  },
  { immediate: true }
)


provideGroupChatWorkspaceContext({
  props,
  emit,
  groupDetail,
  sessionMetaPopoverRootRef,
  sessionMetaPopoverOpen,
  toggleSessionMetaPopover,
  sessionTitleDraft,
  saveSessionTitle,
  titleSaving,
  archiveItems,
  tocActiveKey,
  jumpToSessionTopic,
  renderSnippetMarkdown,
  showGroupWorkspace,
  toggleGroupWorkspaceOpen,
  groupMessagesRef,
  groupDisplayMessages,
  isMemberJoinedMessage,
  isHostBubbleMessage,
  expertAvatarUrl,
  dhaAvatarColor,
  dhaIndex,
  hostLogoUrl,
  dhaAvatarChar,
  bubbleDisplayName,
  activeStreamingSpeakerName,
  streamingPulse,
  formatSkillId,
  getToolRawResults,
  expandedToolKey,
  toolRawMeta,
  formatToolPopover,
  formatGroupMsgTime,
  renderMarkdown,
  dhaBodyContent,
  isShortSingleLine,
  formatUserBubbleForDisplay,
  extractUserFileReferenceNames,
  deleteGroupMessage,
  saveDhaMessageToFile,
  pendingSuggestedDhaItems,
  hostDisplayName,
  suggestedInviteLoading,
  currentAutoSwitchHint,
  autoSwitchHintText,
  autoSwitchIgnoreLoading,
  currentActiveStreamingMessage,
  groupWaitingForUser,
  nextSpeakerLabelText,
  orchestrationInterruptHint,
  currentGroupStreaming,
  currentGroupStreamingPhase,
  inviteOneSuggestedDha,
  inviteSuggestedDha,
  groupSuggestedAddDhaIds,
  ignoreAutoSwitchAndPause,
  attachedFiles,
  removeAttachedFile,
  showNextPromptField,
  groupDiscussionGoal,
  goalTextareaRef,
  onAtInput,
  onAtKeydown,
  onGroupInputEnter,
  onGroupCompositionStart,
  onGroupCompositionEnd,
  closeAtDropdownOnBlur,
  showAtDropdown,
  atSource,
  atMentionOptions,
  atSelectedIndex,
  selectMention,
  groupNextPrompt,
  filteredShortcutExperts,
  showMoreMenu,
  moreMenuRef,
  onShowNextPromptFieldChangeByClick,
  openInsertFileModal,
  showInsertFileModal,
  insertFileRef,
  insertFileLoading,
  groupFileCapabilitySummary,
  insertFileEntries,
  insertFileBrowsePath,
  insertFileGoUp,
  insertFileEnterDir,
  insertFileContent,
  triggerInsertLocalFile,
  insertLocalFileUploading,
  insertLocalFileUploadingName,
  insertLocalFileUploadProgress,
  showShortcutEditor,
  showShortcutEditorModal,
  shortcutEditorRef,
  shortcutPresetSearch,
  shortcutPresets,
  filteredShortcutPresets,
  applyShortcutPreset,
  shortcutPresetExpertNamesText,
  deleteShortcutPreset,
  showAddMember,
  addMemberRef,
  orderedMemberIds,
  displayGroupSpeakerName,
  leaderDhaId,
  leaderDisplayId,
  removeMember,
  invitableDhas,
  inviteSingleMember,
  insertLocalFileInputRef,
  onInsertLocalFile,
  groupTurnLimitReached,
  effectiveNextSpeaker,
  canSend,
  groupStreaming,
  otherSessionStreaming,
  stopGroupStream,
  confirmGroupNext,
  sendGroupMessage,
  toolbarDisplayShowHostAvatar,
  toolbarDisplayLabelText,
  toolbarDisplaySpeakerId,
  focusRoleNameForToolbar,
  showAddMemberModal,
  createSessionFromScenarioPreset,
  VIRTUAL_SCENE_HOST_ID,
  onGroupWorkspaceResizeMouseDown,
  groupWorkspaceWidth,
  groupWorkspacePath,
  goGroupWorkspaceUp,
  groupWorkspaceGoRoot,
  createGroupWorkspaceDir,
  createGroupWorkspaceFile,
  groupWorkspaceUploadInputRef,
  groupWorkspaceUploading,
  groupWorkspaceUploadingName,
  groupWorkspaceUploadProgress,
  onGroupWorkspaceUpload,
  groupWorkspacePreviewCollapsed,
  toggleWorkspacePreview,
  groupWorkspaceLoading,
  groupWorkspaceError,
  groupWorkspaceEntries,
  groupWorkspaceEnterDir,
  groupWorkspacePreviewPath,
  previewWorkspaceFile,
  downloadGroupWorkspaceFile,
  renameGroupWorkspaceEntry,
  deleteGroupWorkspaceEntry,
  onWorkspaceInnerResizeMouseDown,
  groupWorkspaceListWidth,
  groupWorkspacePreviewName,
  isTextFile,
  groupWorkspacePreviewLoading,
  groupWorkspacePreviewEditing,
  startWorkspacePreviewEdit,
  saveWorkspacePreviewEdit,
  cancelWorkspacePreviewEdit,
  groupWorkspacePreviewEditContent,
  groupWorkspacePreviewIsImage,
  groupWorkspacePreviewImageUrl,
  groupWorkspacePreviewContent,
})

defineExpose({ refresh: loadGroupDetail, createSessionFromScenarioPreset })
</script>

<style src="./WorkspaceContent.css"></style>
