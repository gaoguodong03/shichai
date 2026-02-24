<template>
  <div class="flex flex-col h-full bg-gray-50">
    <header class="bg-white border-b border-gray-200 px-4 py-3 flex items-center justify-between">
      <h1 class="text-xl font-semibold text-gray-800 truncate">{{ sessionTitle }}</h1>
      <div class="text-xs text-gray-500">
        {{ dhaIds.length }} 个 DHA
      </div>
    </header>

    <!-- 消息列表 -->
    <div ref="messagesContainerRef" class="flex-1 overflow-y-auto px-4 py-6 space-y-6">
      <template v-for="(msg, index) in messages" :key="msg.message_id || index">
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
          <!-- DHA 消息：名称 + 简介 + 输出框，不同 DHA 不同样式 -->
          <div
            v-else
            class="max-w-3xl min-w-0 w-full"
          >
            <div class="mb-1.5">
              <span class="font-semibold text-gray-800">{{ getDhaName(msg.dha_id) }}</span>
              <span v-if="getDhaRole(msg.dha_id)" class="ml-2 text-xs text-gray-500">{{ getDhaRole(msg.dha_id) }}</span>
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
      </template>

      <!-- 等待回复中 -->
      <div v-if="isStreaming" class="flex justify-start">
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
        <div class="flex items-center gap-2 text-xs text-gray-500">
          <span>下一发言人：</span>
          <select
            v-model="overrideNextSpeaker"
            class="border border-gray-300 rounded px-2 py-1 text-gray-700"
          >
            <option value="">由领导人决定</option>
            <option value="user">等待用户</option>
            <option v-for="d in dhaList" :key="d.dha_id" :value="d.dha_id">
              {{ d.name }}
            </option>
          </select>
        </div>
        <div class="flex gap-2">
          <textarea
            v-model="inputText"
            placeholder="输入消息参与讨论..."
            rows="2"
            class="flex-1 border border-gray-300 rounded-lg px-3 py-2 text-sm resize-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
            :disabled="isStreaming"
            @keydown.enter.exact.prevent="sendMessage"
          />
          <button
            type="button"
            class="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
            :disabled="isStreaming || !inputText.trim()"
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
  }>(),
  { dhaMap: () => ({}) }
)

const emit = defineEmits<{
  (e: 'message-sent'): void
}>()

const inputText = ref('')
const isStreaming = ref(false)
const overrideNextSpeaker = ref('')
const messagesContainerRef = ref<HTMLElement | null>(null)

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

const md = new MarkdownIt()
function renderMarkdown(text: string) {
  if (!text) return ''
  try {
    return md.render(text)
  } catch {
    return text
  }
}

async function sendMessage() {
  const msg = inputText.value.trim()
  if (!msg || isStreaming.value) return

  inputText.value = ''
  isStreaming.value = true

  const body: Record<string, string> = { message: msg }
  if (overrideNextSpeaker.value) {
    body.override_next_speaker = overrideNextSpeaker.value
  }

  try {
    const r = await fetch(`/api/group-sessions/${encodeURIComponent(props.groupSessionId)}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (!r.ok) throw new Error(r.statusText)
    const j = await r.json()
    if (j.status === 'ok' && j.data?.messages) {
      emit('message-sent')
    }
  } catch (e) {
    console.error('Group 发送失败', e)
  } finally {
    isStreaming.value = false
  }
}

watch(
  () => props.messages.length,
  () => {
    nextTick(() => {
      messagesContainerRef.value?.scrollTo({ top: messagesContainerRef.value.scrollHeight, behavior: 'smooth' })
    })
  }
)
</script>
