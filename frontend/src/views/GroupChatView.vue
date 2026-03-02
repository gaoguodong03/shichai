<template>
  <div class="flex flex-col h-full bg-gray-50">
    <header class="bg-white border-b border-gray-200 px-4 py-3 flex items-center justify-between gap-2">
      <h1 class="text-xl font-semibold text-gray-800 truncate min-w-0">{{ sessionTitle }}</h1>
      <span class="text-xs text-gray-500 flex-shrink-0">{{ dhaIds.length }} 个 DHA</span>
    </header>

    <!-- 消息列表：用 displayedMessages 保证顺序与逐条出现 -->
    <div ref="messagesContainerRef" class="flex-1 overflow-y-auto px-4 py-6 space-y-6">
      <template v-for="(msg, index) in displayedMessages" :key="msg.message_id || index">
        <div
          :data-message-index="index"
          :class="['flex', msg.role === 'user' ? 'justify-end' : 'justify-start']"
        >
          <!-- 用户消息 -->
          <div
            v-if="msg.role === 'user'"
            class="max-w-3xl min-w-0 rounded-lg px-4 py-2 bg-blue-500 text-white"
          >
            <div class="chat-markdown-wrap break-words min-w-0 overflow-hidden">
              <div class="chat-markdown whitespace-pre-wrap" v-html="renderMarkdown(msg.content || '')"></div>
            </div>
          </div>
          <!-- 主持人消息（旧版 role=host 或主持人 DHA 的发言） -->
          <div
            v-else-if="msg.role === 'host'"
            class="max-w-3xl min-w-0 w-full flex justify-center"
          >
            <div class="text-xs text-gray-500 italic px-3 py-1.5 bg-gray-100 rounded-full">
              {{ msg.content || '' }}
            </div>
          </div>
          <!-- DHA 消息：头像（首字）+ 名称 + 简介 + 输出框 -->
          <div
            v-else
            class="max-w-3xl min-w-0 w-full flex gap-2"
          >
            <div class="flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center text-sm font-semibold text-white"
              :style="{ backgroundColor: getDhaAvatarBg(msg.dha_id) }"
            >
              {{ getDhaAvatarChar(msg.dha_id) }}
            </div>
            <div class="min-w-0 flex-1">
            <div class="mb-1.5 flex items-center gap-2 flex-wrap">
              <span class="font-semibold text-gray-800">{{ getDhaName(msg.dha_id) }}</span>
              <span v-if="leaderDhaId && msg.dha_id === leaderDhaId" class="text-xs px-1.5 py-0.5 rounded bg-amber-100 text-amber-800">主持人</span>
              <span v-if="getDhaRole(msg.dha_id)" class="text-xs text-gray-500">{{ getDhaRole(msg.dha_id) }}</span>
            </div>
            <div
              :class="getDhaBoxClass(msg.dha_id)"
              class="rounded-lg px-4 py-3 border-l-4"
            >
              <div class="chat-markdown-wrap break-words min-w-0 overflow-hidden">
                <div class="chat-markdown whitespace-pre-wrap" v-html="renderMarkdown(msg.content || '')"></div>
              </div>
            </div>
            </div>
          </div>
        </div>
      </template>

      <!-- 当前 DHA 正在发言（流式或等待中） -->
      <div v-if="isStreaming && currentStreamingDhaId" class="flex justify-start">
        <div class="max-w-3xl min-w-0 w-full flex gap-2">
          <div class="flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center text-sm font-semibold text-white"
            :style="{ backgroundColor: getDhaAvatarBg(currentStreamingDhaId) }"
          >
            {{ getDhaAvatarChar(currentStreamingDhaId) }}
          </div>
          <div class="min-w-0 flex-1">
          <div class="mb-1.5 flex items-center gap-2">
            <span class="font-semibold text-gray-800">{{ getDhaName(currentStreamingDhaId) }}</span>
            <span class="text-xs text-gray-500">正在发言...</span>
          </div>
          <div
            :class="getDhaBoxClass(currentStreamingDhaId)"
            class="rounded-lg px-4 py-3 border-l-4"
          >
            <div class="chat-markdown-wrap break-words min-w-0 overflow-hidden">
              <div class="chat-markdown whitespace-pre-wrap" v-html="renderMarkdown(currentStreamingText)"></div>
            </div>
          </div>
          </div>
        </div>
      </div>
      <div v-else-if="isStreaming" class="flex justify-start">
        <div class="max-w-3xl rounded-lg px-4 py-3 bg-gray-50 border border-gray-200 flex items-center gap-2">
          <span class="text-sm text-gray-600">正在思考</span>
          <span class="flex gap-1">
            <span class="w-2 h-2 bg-gray-400 rounded-full animate-pulse" style="animation-delay: 0ms"></span>
            <span class="w-2 h-2 bg-gray-400 rounded-full animate-pulse" style="animation-delay: 160ms"></span>
            <span class="w-2 h-2 bg-gray-400 rounded-full animate-pulse" style="animation-delay: 320ms"></span>
          </span>
        </div>
      </div>
    </div>

    <!-- 输入区 -->
    <div class="bg-white border-t border-gray-200 px-4 py-3">
      <div class="flex gap-2">
        <div class="flex-1 flex flex-col gap-1">
          <textarea
            v-model="inputText"
            placeholder="输入消息参与讨论..."
            rows="2"
            class="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm resize-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
            :disabled="isStreaming"
            @keydown.enter.exact.prevent="sendMessage"
          />
          <div class="flex items-center gap-3 flex-wrap text-xs">
            <button
              type="button"
              class="text-gray-500 hover:text-blue-600"
              @click="openFilePicker"
            >
              插入文件
            </button>
            <label class="flex items-center gap-1.5 text-gray-600 cursor-pointer">
              <input
                type="checkbox"
                :checked="speakMode === 'auto'"
                class="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                @change="onAutoSwitchChange"
              />
              <span>自动</span>
            </label>
            <span class="text-gray-500">下一发言人：</span>
            <select
              v-model="overrideNextSpeaker"
              class="border border-gray-300 rounded px-2 py-1 text-gray-700 disabled:opacity-50 disabled:cursor-not-allowed"
              :disabled="speakMode === 'auto'"
            >
              <option value="">由主持人决定</option>
              <option value="user">等待用户</option>
              <option v-for="d in dhaList" :key="d.dha_id" :value="d.dha_id">
                {{ d.name }}
              </option>
            </select>
            <button
              v-if="speakMode === 'manual' && overrideNextSpeaker && overrideNextSpeaker !== 'user'"
              type="button"
              class="px-2 py-1 border border-gray-300 rounded text-gray-600 hover:bg-gray-100"
              @click="openPromptEditor"
            >
              查看/编辑提示词
            </button>
          </div>
        </div>
        <button
          type="button"
          class="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed self-end"
          :disabled="isStreaming || (!inputText.trim() && !overrideNextSpeaker)"
          @click="sendMessage"
        >
          发送
        </button>
      </div>
    </div>

    <!-- 文件选择弹窗（与 Chat 同款样式） -->
    <div
      v-if="showFilePicker"
      class="fixed inset-0 bg-black/30 flex items-center justify-center p-4 z-50"
      @click.self="closeFilePicker"
    >
      <div class="bg-white w-full max-w-2xl rounded-lg shadow-lg border border-gray-200 overflow-hidden">
        <div class="px-4 py-3 border-b border-gray-200 flex items-center justify-between gap-2">
          <div class="text-sm font-semibold text-gray-800 truncate">
            选择要插入到输入框的文件（当前目录：{{ filePickerPath || '/' }}）
          </div>
          <button class="text-sm text-gray-500 hover:text-gray-800" @click="closeFilePicker">关闭</button>
        </div>
        <div class="px-4 py-2 border-b border-gray-100 flex items-center gap-2">
          <button
            class="px-2 py-1 text-sm border border-gray-300 rounded hover:bg-gray-100 disabled:opacity-50"
            :disabled="!filePickerPath"
            @click="filePickerGoUp"
          >
            ↑ 上一级
          </button>
          <button
            class="px-2 py-1 text-sm border border-gray-300 rounded hover:bg-gray-100"
            @click="loadFilePickerEntries(filePickerPath)"
          >
            刷新
          </button>
          <div v-if="filePickerLoading" class="text-xs text-gray-500">加载中...</div>
          <div v-else-if="filePickerError" class="text-xs text-red-600 truncate">{{ filePickerError }}</div>
        </div>
        <div class="max-h-[60vh] overflow-auto">
          <div v-if="!filePickerEntries.length && !filePickerLoading" class="px-4 py-6 text-sm text-gray-500">
            当前目录为空
          </div>
          <button
            v-for="e in filePickerEntries"
            :key="e.path"
            class="w-full text-left px-4 py-2.5 hover:bg-gray-50 flex items-center gap-2 border-b border-gray-100"
            @click="onPickFileEntry(e)"
          >
            <span class="flex-shrink-0">{{ e.is_dir ? '📁' : '📄' }}</span>
            <span class="truncate">{{ e.name }}</span>
            <span v-if="!e.is_dir" class="ml-auto text-xs text-gray-400">插入</span>
          </button>
        </div>
      </div>
    </div>

    <!-- 下一发言人提示词编辑弹窗（manual 模式下使用） -->
    <div
      v-if="showPromptEditor"
      class="fixed inset-0 bg-black/30 flex items-center justify-center p-4 z-50"
      @click.self="closePromptEditor"
    >
      <div class="bg-white w-full max-w-2xl rounded-lg shadow-lg border border-gray-200 overflow-hidden">
        <div class="px-4 py-3 border-b border-gray-200 flex items-center justify-between gap-2">
          <div class="text-sm font-semibold text-gray-800 truncate">
            下一发言人提示词（仅本轮有效）
          </div>
          <button class="text-sm text-gray-500 hover:text-gray-800" @click="closePromptEditor">关闭</button>
        </div>
        <div class="p-4">
          <textarea
            v-model="promptEditorText"
            rows="10"
            class="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm resize-y focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
          />
          <p class="mt-2 text-xs text-gray-500">
            说明：这是发送给下一位 DHA 的完整文本提示词，你可以在 manual 模式下按需微调，仅对本轮生效。
          </p>
        </div>
        <div class="px-4 py-3 border-t border-gray-100 flex justify-end gap-2">
          <button
            type="button"
            class="px-3 py-1.5 text-sm border border-gray-300 rounded text-gray-600 hover:bg-gray-100"
            @click="closePromptEditor"
          >
            取消
          </button>
          <button
            type="button"
            class="px-3 py-1.5 text-sm bg-blue-600 text-white rounded hover:bg-blue-700"
            @click="confirmPromptEditor"
          >
            使用此提示词
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick } from 'vue'
import MarkdownIt from 'markdown-it'

const props = withDefaults(
  defineProps<{
    groupSessionId: string
    sessionTitle: string
    messages: { message_id?: string; role: string; dha_id?: string; content: string }[]
    dhaMap?: Record<string, { name?: string; role?: string }>
    dhaIds: string[]
    leaderDhaId?: string
    speakMode?: string
  }>(),
  { dhaMap: () => ({}), leaderDhaId: '', speakMode: 'auto' }
)

const emit = defineEmits<{
  (e: 'message-sent'): void
  (e: 'speak-mode-changed'): void
}>()

const inputText = ref('')
const isStreaming = ref(false)
const overrideNextSpeaker = ref('')
const customPrompt = ref('') // manual 模式下，用户可编辑的下一发言人提示词
const messagesContainerRef = ref<HTMLElement | null>(null)
/** 用于逐条展示的消息列表：从 props 同步，并从流式 message 事件追加 */
const displayedMessages = ref<{ message_id?: string; role: string; dha_id?: string; content: string }[]>([])
const currentStreamingText = ref('')
const currentStreamingDhaId = ref('')
const showFilePicker = ref(false)
const filePickerPath = ref('')
const filePickerLoading = ref(false)
const filePickerError = ref('')
const filePickerEntries = ref<{ name: string; path: string; is_dir?: boolean }[]>([])
const showPromptEditor = ref(false)
const promptEditorText = ref('')

const DHA_AVATAR_COLORS = [
  '#2563eb', '#059669', '#b45309', '#7c3aed', '#be123c', '#0891b2', '#0d9488', '#4f46e5',
]

function getDhaAvatarChar(dhaId: string) {
  const name = getDhaName(dhaId)
  if (!name) return '?'
  const first = name.trim().charAt(0)
  return first || dhaId?.charAt(0) || '?'
}

function getDhaAvatarBg(dhaId: string) {
  let hash = 0
  const s = dhaId || ''
  for (let i = 0; i < s.length; i++) {
    hash = ((hash << 5) - hash) + s.charCodeAt(i)
    hash |= 0
  }
  return DHA_AVATAR_COLORS[Math.abs(hash) % DHA_AVATAR_COLORS.length]
}

function openFilePicker() {
  showFilePicker.value = true
  filePickerError.value = ''
  loadFilePickerEntries('')
}

function closeFilePicker() {
  showFilePicker.value = false
}

async function loadFilePickerEntries(path: string) {
  filePickerLoading.value = true
  filePickerError.value = ''
  try {
    const url = path ? `/api/files?path=${encodeURIComponent(path)}` : '/api/files'
    const r = await fetch(url)
    const j = await r.json()
    if (j.status === 'ok' && j.data?.entries) {
      filePickerEntries.value = j.data.entries as { name: string; path: string; is_dir?: boolean }[]
      filePickerPath.value = path
    } else {
      filePickerEntries.value = []
      filePickerError.value = (j as { detail?: string }).detail || '加载失败'
    }
  } catch {
    filePickerEntries.value = []
    filePickerError.value = '加载失败'
  } finally {
    filePickerLoading.value = false
  }
}

function filePickerGoUp() {
  const p = filePickerPath.value.replace(/\/?[^/]+\/?$/, '').replace(/\/$/, '')
  loadFilePickerEntries(p)
}

function onPickFileEntry(e: { path: string; name: string; is_dir?: boolean }) {
  if (e.is_dir) {
    loadFilePickerEntries(e.path)
    return
  }
  inputText.value = (inputText.value || '') + `\n【文件引用：${e.path}】\n`
  closeFilePicker()
}

async function openPromptEditor() {
  if (!overrideNextSpeaker.value || overrideNextSpeaker.value === 'user') {
    return
  }
  try {
    const r = await fetch(`/api/group-sessions/${encodeURIComponent(props.groupSessionId)}/prompt-preview`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ dha_id: overrideNextSpeaker.value }),
    })
    const j = await r.json()
    if (j.status === 'ok' && j.data?.prompt) {
      promptEditorText.value = j.data.prompt as string
      showPromptEditor.value = true
    } else {
      alert((j as { detail?: string }).detail || '加载提示词失败')
    }
  } catch {
    alert('加载提示词失败，请检查网络或后端服务')
  }
}

function closePromptEditor() {
  showPromptEditor.value = false
}

function confirmPromptEditor() {
  customPrompt.value = promptEditorText.value || ''
  showPromptEditor.value = false
}

watch(
  () => props.messages,
  (next) => {
    if (!isStreaming.value && next?.length !== undefined) {
      displayedMessages.value = [...next]
    }
  },
  { immediate: true }
)

const dhaList = computed(() => {
  return props.dhaIds.map((id) => ({
    dha_id: id,
    name: props.dhaMap[id]?.name || id,
    role: props.dhaMap[id]?.role,
  }))
})

function getDhaName(dhaId: string) {
  const map = props.dhaMap || {}
  return map[dhaId]?.name || dhaId || '助手'
}

function getDhaRole(dhaId: string) {
  const map = props.dhaMap || {}
  const role = map[dhaId]?.role
  return (role && String(role).trim()) || ''
}

const DHA_BOX_COLORS = [
  'border-l-blue-500 bg-blue-50/50',
  'border-l-emerald-500 bg-emerald-50/50',
  'border-l-amber-500 bg-amber-50/50',
  'border-l-violet-500 bg-violet-50/50',
  'border-l-rose-500 bg-rose-50/50',
  'border-l-cyan-500 bg-cyan-50/50',
  'border-l-teal-500 bg-teal-50/50',
  'border-l-indigo-500 bg-indigo-50/50',
]

function getDhaBoxClass(dhaId: string): string {
  if (!dhaId) return 'border-l-gray-400 bg-gray-50/50'
  let hash = 0
  for (let i = 0; i < dhaId.length; i++) {
    hash = ((hash << 5) - hash) + dhaId.charCodeAt(i)
    hash |= 0
  }
  const idx = Math.abs(hash) % DHA_BOX_COLORS.length
  return DHA_BOX_COLORS[idx]
}

const md = new MarkdownIt({ breaks: true })
/** 去掉末尾空行，并把连续换行压成单个，减少段落间空行 */
function normalizeContent(s: string) {
  if (!s) return ''
  return s.trimEnd().replace(/\n{2,}/g, '\n')
}
function renderMarkdown(text: string) {
  if (!text) return ''
  try {
    return md.render(normalizeContent(text))
  } catch {
    return text
  }
}

async function sendMessage() {
  const msg = inputText.value.trim()
  const hasOverride = !!overrideNextSpeaker.value
  if (isStreaming.value) return
  if (!msg && !hasOverride) return

  inputText.value = ''
  isStreaming.value = true
  currentStreamingText.value = ''
  currentStreamingDhaId.value = ''

  if (msg) {
    const userMsg = {
      message_id: `msg-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      role: 'user' as const,
      content: msg,
    }
    displayedMessages.value = [...displayedMessages.value, userMsg]
    scrollToBottom()
  }

  const body: Record<string, string> = { message: msg || '' }
  if (hasOverride) {
    body.override_next_speaker = overrideNextSpeaker.value
  }
  if (customPrompt.value.trim()) {
    body.custom_prompt = customPrompt.value.trim()
  }

  try {
    const r = await fetch(`/api/group-sessions/${encodeURIComponent(props.groupSessionId)}/chat/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
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
          const eventType = block.slice(0, block.indexOf('\n')).replace('event: ', '').trim()
          const dataStr = block.includes('\ndata: ') ? block.split('\ndata: ').slice(1).join('\ndata: ').trim() : ''
          if (eventType === 'message' && dataStr) {
            try {
              const data = JSON.parse(dataStr)
              if (data && (data.role === 'assistant' || data.role === 'user')) {
                currentStreamingText.value = ''
                currentStreamingDhaId.value = ''
                displayedMessages.value = [...displayedMessages.value, data]
                scrollToBottom()
              }
            } catch (_) {}
          } else if (eventType === 'content' && dataStr) {
            try {
              const data = JSON.parse(dataStr)
              if (data?.dha_id) {
                currentStreamingDhaId.value = data.dha_id
                if (data.text) currentStreamingText.value = (currentStreamingText.value || '') + data.text
                scrollToBottom()
              }
            } catch (_) {}
          } else if (eventType === 'end') {
            currentStreamingText.value = ''
            currentStreamingDhaId.value = ''
          }
        }
      }
    }
    emit('message-sent')
  } catch (e) {
    console.error('Group 发送失败', e)
  } finally {
    isStreaming.value = false
    currentStreamingText.value = ''
    currentStreamingDhaId.value = ''
  }
}

async function onAutoSwitchChange(e: Event) {
  const target = e.target as HTMLInputElement
  const next = target.checked ? 'auto' : 'manual'
  try {
    const r = await fetch(`/api/group-sessions/${encodeURIComponent(props.groupSessionId)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ speak_mode: next }),
    })
    const j = await r.json()
    if (j.status === 'ok') {
      emit('speak-mode-changed')
    } else {
      target.checked = !target.checked
    }
  } catch {
    target.checked = !target.checked
  }
}

watch(
  () => overrideNextSpeaker.value,
  () => {
    // 选择不同的下一发言人时，清空上一次编辑的提示词，避免误用
    customPrompt.value = ''
  }
)

function scrollToBottom() {
  nextTick(() => {
    messagesContainerRef.value?.scrollTo({ top: messagesContainerRef.value.scrollHeight, behavior: 'smooth' })
  })
}

watch(
  () => displayedMessages.value.length,
  () => { scrollToBottom() }
)
</script>

<style scoped>
.chat-markdown :deep(p) {
  margin: 0 0 0.35em 0;
}
.chat-markdown :deep(p:last-child) {
  margin-bottom: 0;
}
</style>
