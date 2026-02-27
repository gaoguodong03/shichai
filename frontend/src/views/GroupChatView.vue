<template>
  <div class="flex flex-col h-full bg-gray-50">
    <header class="bg-white border-b border-gray-200 px-4 py-3 flex items-center justify-between">
      <h1 class="text-xl font-semibold text-gray-800 truncate">{{ sessionTitle }}</h1>
      <div class="text-xs text-gray-500">
        {{ dhaIds.length }} 个 DHA
      </div>
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
      <div class="flex flex-col gap-2">
        <div class="flex items-center gap-2 text-xs" :class="speakMode === 'manual' ? 'text-amber-700' : 'text-gray-500'">
          <span>{{ speakMode === 'manual' ? '请选择发言人（必选）：' : '下一发言人：' }}</span>
          <select
            v-model="overrideNextSpeaker"
            class="border border-gray-300 rounded px-2 py-1 text-gray-700"
          >
            <option value="">{{ speakMode === 'manual' ? '请选择' : '由主持人决定' }}</option>
            <option value="user">等待用户</option>
            <option v-for="d in dhaList" :key="d.dha_id" :value="d.dha_id">
              {{ d.name }}
            </option>
          </select>
        </div>
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
            <div class="flex items-center gap-2">
              <button
                type="button"
                class="text-xs text-gray-500 hover:text-blue-600"
                @click="showFilePicker = !showFilePicker; showFilePicker && loadFileEntries()"
              >
                插入文件
              </button>
              <div v-if="showFilePicker" class="flex flex-wrap gap-1 max-h-24 overflow-y-auto">
                <button
                  v-for="e in fileEntries"
                  :key="e.path"
                  type="button"
                  class="text-xs px-2 py-1 rounded bg-gray-100 hover:bg-gray-200 truncate max-w-[180px]"
                  @click="insertFileRef(e.path)"
                >
                  {{ e.name }}
                </button>
              </div>
            </div>
          </div>
          <button
            type="button"
            class="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed self-end"
            :disabled="isStreaming || !inputText.trim() || (speakMode === 'manual' && !overrideNextSpeaker)"
            @click="sendMessage"
          >
            发送
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
}>()

const inputText = ref('')
const isStreaming = ref(false)
const overrideNextSpeaker = ref('')
const messagesContainerRef = ref<HTMLElement | null>(null)
/** 用于逐条展示的消息列表：从 props 同步，并从流式 message 事件追加 */
const displayedMessages = ref<{ message_id?: string; role: string; dha_id?: string; content: string }[]>([])
const currentStreamingText = ref('')
const currentStreamingDhaId = ref('')
const showFilePicker = ref(false)
const fileEntries = ref<{ name: string; path: string }[]>([])

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

async function loadFileEntries() {
  if (fileEntries.value.length) return
  try {
    const r = await fetch('/api/files')
    const j = await r.json()
    if (j.status === 'ok' && j.data?.entries) {
      fileEntries.value = (j.data.entries as { name: string; path: string }[]).filter((e: any) => !e.is_dir)
    }
  } catch {
    fileEntries.value = []
  }
}

function insertFileRef(filePath: string) {
  inputText.value = (inputText.value || '') + `\n【文件引用：${filePath}】\n`
  showFilePicker.value = false
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
  if (!msg || isStreaming.value) return

  inputText.value = ''
  isStreaming.value = true
  currentStreamingText.value = ''
  currentStreamingDhaId.value = ''

  const userMsg = {
    message_id: `msg-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    role: 'user' as const,
    content: msg,
  }
  displayedMessages.value = [...displayedMessages.value, userMsg]
  scrollToBottom()

  const body: Record<string, string> = { message: msg }
  if (overrideNextSpeaker.value) {
    body.override_next_speaker = overrideNextSpeaker.value
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
