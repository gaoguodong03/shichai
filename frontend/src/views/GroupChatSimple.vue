<template>
  <div class="group-chat-simple flex flex-col flex-1 min-h-0 bg-page">
    <div ref="messagesContainerRef" class="flex-1 overflow-y-auto px-4 py-4 space-y-3 text-primary">
      <template v-for="(msg, i) in displayedMessages" :key="msg.message_id || i">
        <div :class="['flex', msg.role === 'user' ? 'justify-end' : 'justify-start']">
          <div
            :class="[
              'max-w-2xl rounded-lg px-3 py-2 text-sm whitespace-pre-wrap break-words',
              msg.role === 'user'
                ? 'bg-accent text-accent-contrast'
                : 'bg-card border border-border'
            ]"
          >
            <span v-if="msg.role !== 'user' && dhaName(msg.dha_id)" class="font-medium text-muted block mb-1">{{ dhaName(msg.dha_id) }}</span>
            {{ msg.content || '' }}
          </div>
        </div>
      </template>
      <p v-if="!displayedMessages.length" class="text-muted text-sm">暂无消息，在下方输入并发送。</p>
    </div>
    <div class="flex-shrink-0 p-3 border-t border-border bg-card">
      <div class="flex gap-2">
        <textarea
          v-model="inputText"
          class="flex-1 min-h-[80px] rounded-lg border border-input-border bg-input px-3 py-2 text-primary placeholder-muted resize-y text-sm"
          placeholder="输入消息…"
          :disabled="isStreaming"
          @keydown.enter.meta="sendMessage"
        />
        <button
          type="button"
          class="self-end px-4 py-2 rounded-lg bg-accent text-accent-contrast text-sm font-medium disabled:opacity-50"
          :disabled="isStreaming || !inputText.trim()"
          @click="sendMessage"
        >
          {{ isStreaming ? '发送中…' : '发送' }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, nextTick } from 'vue'

const props = defineProps<{
  groupSessionId: string
  title: string
  messages: { message_id?: string; role: string; dha_id?: string; content: string }[]
  dhaMap?: Record<string, { name?: string }>
}>()

const emit = defineEmits<{ (e: 'message-sent'): void }>()

const displayedMessages = ref<{ message_id?: string; role: string; dha_id?: string; content: string }[]>([])
const inputText = ref('')
const isStreaming = ref(false)
const messagesContainerRef = ref<HTMLElement | null>(null)

watch(
  () => props.messages,
  (next) => {
    displayedMessages.value = Array.isArray(next) ? [...next] : []
  },
  { immediate: true }
)

function dhaName(dhaId?: string) {
  if (!dhaId || !props.dhaMap) return ''
  return props.dhaMap[dhaId]?.name ?? ''
}

function scrollToBottom() {
  nextTick(() => {
    const el = messagesContainerRef.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

async function sendMessage() {
  const msg = inputText.value.trim()
  if (isStreaming.value || !msg) return
  inputText.value = ''
  isStreaming.value = true

  const userMsg = {
    message_id: `msg-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    role: 'user' as const,
    content: msg,
  }
  displayedMessages.value = [...displayedMessages.value, userMsg]
  scrollToBottom()

  try {
    const r = await fetch(`/api/sessions/${encodeURIComponent(props.groupSessionId)}/chat/stream`, {
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
            try {
              const data = JSON.parse(dataStr)
              if (data && (data.role === 'assistant' || data.role === 'user' || data.role === 'host')) {
                displayedMessages.value = [...displayedMessages.value, data]
                scrollToBottom()
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
    isStreaming.value = false
  }
}
</script>
