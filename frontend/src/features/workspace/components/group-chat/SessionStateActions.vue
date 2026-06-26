<template>
  <div ref="rootRef" class="relative">
    <div class="flex items-center gap-2">
      <button
        type="button"
        class="group-chat-header-btn"
        :disabled="forking"
        @click="forkSession"
      >
        {{ forking ? '分叉中…' : '分叉' }}
      </button>
      <button
        type="button"
        class="group-chat-header-btn"
        :class="[panelOpen && 'group-chat-header-btn-active']"
        @click="togglePanel"
      >
        状态
      </button>
    </div>

    <div
      v-if="panelOpen"
      class="group-chat-session-meta-popover right-0 mt-2 w-[22rem]"
      role="dialog"
      aria-label="会话状态"
      @click.stop
    >
      <div class="group-chat-meta-section">
        <div class="group-chat-meta-label flex items-center justify-between gap-2">
          <span>状态快照</span>
          <span v-if="loading" class="text-xs text-muted">加载中…</span>
        </div>
        <div v-if="!checkpoints.length" class="group-chat-meta-empty">暂无状态快照</div>
        <div v-else class="group-chat-meta-topic-list">
          <button
            v-for="item in checkpoints"
            :key="item.id"
            type="button"
            class="group-chat-meta-topic-item"
            :disabled="rollingBackId === item.id"
            @click="rollbackTo(item)"
          >
            <span class="group-chat-meta-topic-name">{{ formatCheckpointLabel(item) }}</span>
            <div class="group-chat-meta-topic-snippet">
              <span>{{ formatCheckpointTime(item.created_at) }}</span>
              <span v-if="item.reason" class="ml-2 text-muted">· {{ item.reason }}</span>
            </div>
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onUnmounted, ref, watch } from 'vue'
import { apiRequest } from '@/api/base'
import { appAlert, appConfirm } from '@/composables/useAppDialog'

interface SessionCheckpoint {
  id: string
  created_at?: string
  reason?: string
}

const props = defineProps<{
  sessionId: string
  sessionTitle?: string
}>()

const emit = defineEmits<{
  (e: 'forked', sessionId: string): void
  (e: 'rolled-back'): void
}>()

const rootRef = ref<HTMLElement | null>(null)
const panelOpen = ref(false)
const loading = ref(false)
const forking = ref(false)
const rollingBackId = ref('')
const checkpoints = ref<SessionCheckpoint[]>([])
let fetchSeq = 0

function togglePanel() {
  panelOpen.value = !panelOpen.value
}

async function loadCheckpoints() {
  const id = (props.sessionId || '').trim()
  if (!id) {
    checkpoints.value = []
    return
  }
  const seq = ++fetchSeq
  loading.value = true
  try {
    const response = await apiRequest(`/sessions/${encodeURIComponent(id)}/snapshots`)
    const payload = await response.json().catch(() => null)
    if (seq !== fetchSeq) return
    checkpoints.value = response.ok && payload?.status === 'ok' && Array.isArray(payload?.data?.checkpoints)
      ? payload.data.checkpoints
      : []
  } catch {
    if (seq === fetchSeq) checkpoints.value = []
  } finally {
    if (seq === fetchSeq) loading.value = false
  }
}

async function forkSession() {
  const id = (props.sessionId || '').trim()
  if (!id || forking.value) return
  const ok = await appConfirm({
    title: '分叉会话',
    message: '将当前工作区和聊天状态复制成一个新的会话分支。',
    confirmText: '分叉',
    variant: 'info',
  })
  if (!ok) return
  forking.value = true
  try {
    const response = await apiRequest(`/sessions/${encodeURIComponent(id)}/clone`, { method: 'POST' })
    const payload = await response.json().catch(() => null)
    if (!response.ok || payload?.status !== 'ok' || !payload?.data?.session_id) {
      await appAlert({ title: '分叉失败', message: payload?.detail || '分叉失败', variant: 'danger' })
      return
    }
    emit('forked', String(payload.data.session_id))
  } catch {
    await appAlert({ title: '分叉失败', message: '分叉失败，请检查网络', variant: 'danger' })
  } finally {
    forking.value = false
  }
}

async function rollbackTo(item: SessionCheckpoint) {
  const id = (props.sessionId || '').trim()
  const checkpointId = String(item.id || '').trim()
  if (!id || !checkpointId || rollingBackId.value) return
  const ok = await appConfirm({
    title: '回溯会话',
    message: `确定回溯到「${formatCheckpointLabel(item)}」吗？后续状态将被删除。`,
    confirmText: '回溯',
    variant: 'warning',
  })
  if (!ok) return
  rollingBackId.value = checkpointId
  try {
    const response = await apiRequest(`/sessions/${encodeURIComponent(id)}/rollback`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ checkpoint_id: checkpointId }),
    })
    const payload = await response.json().catch(() => null)
    if (!response.ok || payload?.status !== 'ok') {
      await appAlert({ title: '回溯失败', message: payload?.detail || '回溯失败', variant: 'danger' })
      return
    }
    panelOpen.value = false
    emit('rolled-back')
    await loadCheckpoints()
  } catch {
    await appAlert({ title: '回溯失败', message: '回溯失败，请检查网络', variant: 'danger' })
  } finally {
    rollingBackId.value = ''
  }
}

function formatCheckpointLabel(item: SessionCheckpoint) {
  return String(item.reason || '状态快照')
}

function formatCheckpointTime(value?: string) {
  if (!value) return ''
  try {
    return new Date(value).toLocaleString('zh-CN', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return value
  }
}

function onDocumentClick(e: MouseEvent) {
  const root = rootRef.value
  if (!root || root.contains(e.target as Node)) return
  panelOpen.value = false
}

watch(
  () => props.sessionId,
  () => {
    panelOpen.value = false
    loadCheckpoints()
  },
  { immediate: true },
)

watch(panelOpen, (open) => {
  if (open) {
    loadCheckpoints()
    document.addEventListener('click', onDocumentClick)
    return
  }
  document.removeEventListener('click', onDocumentClick)
})

onUnmounted(() => {
  document.removeEventListener('click', onDocumentClick)
})
</script>
