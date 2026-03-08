<template>
  <!-- 根节点：占满父级给的 flex 区域，文字色与背景用内联兜底 -->
  <div
    class="workspace-pane"
    style="width: 100%; flex: 1; min-height: 0; display: flex; flex-direction: column; overflow: hidden; color: #111; background: #f5f5f7;"
  >
    <!-- 加载中 -->
    <div
      v-if="loading && !detail"
      style="flex: 1; min-height: 0; display: flex; align-items: center; justify-content: center; padding: 1rem; color: #111;"
    >
      <p style="margin: 0;">加载中…</p>
    </div>
    <!-- 错误 + 重试 -->
    <div
      v-else-if="error"
      style="flex: 1; min-height: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 1rem; color: #111;"
    >
      <p style="margin: 0;">{{ error }}</p>
      <button
        type="button"
        style="margin-top: 0.5rem; padding: 0.375rem 0.75rem; border: 1px solid #ccc; border-radius: 0.5rem; background: transparent; color: #111; cursor: pointer; font-size: 0.875rem;"
        @click="load"
      >
        重试
      </button>
    </div>
    <!-- 群聊内容：包裹层设 theme 变量兜底，避免子组件文字不可见 -->
    <div
      v-else-if="detail"
      class="group-chat-wrapper"
      style="flex: 1; min-height: 0; display: flex; flex-direction: column; overflow: hidden; width: 100%; background: #f5f5f7; color: #111; --color-text: #111; --color-text-muted: #666; --color-page: #f5f5f7; --color-card: #fff; --color-border: #ddd; --color-input-border: #ccc; --color-list-hover: #eee; --color-accent: #007aff; --color-accent-subtle: #e8f0fe; --color-accent-subtle-text: #0040c0; --color-user-bubble: #007aff; --color-tool-call-border: #007aff; --color-tool-call-bg: #e8f0fe; --color-tool-call-text: #0040c0; --color-skill: #5856d6;"
    >
      <GroupChatView
        :key="detail.id"
        style="flex: 1; min-height: 0; display: flex; flex-direction: column; overflow: hidden; width: 100%;"
        :group-session-id="detail.id"
        :session-title="detail.title || '群聊'"
        :messages="detail.messages || []"
        :dha-map="detail.dha_map || {}"
        :dha-ids="detail.dha_ids || []"
        :all-dha-instances="dhaInstances"
        :leader-dha-id="detail.leader_dha_id || ''"
        :speak-mode="detail.speak_mode || 'auto'"
        :is-single-dha="(detail.dha_ids?.length || 0) <= 1"
        @message-sent="$emit('message-sent')"
        @speak-mode-changed="$emit('speak-mode-changed')"
        @dha-added="$emit('dha-added')"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import GroupChatView from './GroupChatView.vue'

const props = defineProps<{
  groupSessionId: string
  dhaInstances: { dha_id: string; name: string; role?: string }[]
}>()

defineEmits<{
  (e: 'message-sent'): void
  (e: 'speak-mode-changed'): void
  (e: 'dha-added'): void
}>()

const detail = ref<{
  id: string
  title: string
  messages: { message_id?: string; role: string; dha_id?: string; content: string }[]
  dha_map: Record<string, { name?: string; role?: string }>
  dha_ids: string[]
  leader_dha_id?: string
  speak_mode?: string
} | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)

function normalizeDetail(id: string, j: unknown): typeof detail.value {
  if (j === null || j === undefined) return null
  // 响应直接是消息数组（非常规）
  if (Array.isArray(j)) {
    return {
      id,
      title: '群聊',
      messages: j as { message_id?: string; role: string; dha_id?: string; content: string }[],
      dha_map: {},
      dha_ids: [],
      leader_dha_id: '',
      speak_mode: 'auto',
    }
  }
  if (typeof j !== 'object') return null
  const o = j as Record<string, unknown>
  // 标准格式：{ status: 'ok', data: { id, title, messages, ... } }
  if (o.status === 'ok' && o.data && typeof o.data === 'object') {
    const d = o.data as Record<string, unknown>
    if (d.id) return d as typeof detail.value
  }
  // 直接返回 data 对象（无 status 包装）；兼容 speak_node 拼写
  if (o.id && (Array.isArray(o.messages) || o.messages === undefined)) {
    return {
      id: String(o.id),
      title: String(o.title ?? '群聊'),
      messages: Array.isArray(o.messages) ? (o.messages as typeof detail.value['messages']) : [],
      dha_map: (o.dha_map && typeof o.dha_map === 'object') ? (o.dha_map as Record<string, { name?: string; role?: string }>) : {},
      dha_ids: Array.isArray(o.dha_ids) ? (o.dha_ids as string[]) : [],
      leader_dha_id: String(o.leader_dha_id ?? ''),
      speak_mode: String((o.speak_mode ?? o.speak_node) ?? 'auto'),
    }
  }
  return null
}

async function load() {
  const id = props.groupSessionId
  if (!id) return
  loading.value = true
  error.value = null
  try {
    const r = await fetch(`/api/group-sessions/${encodeURIComponent(id)}`)
    const j = await r.json().catch(() => null)
    const parsed = normalizeDetail(id, j)
    if (parsed) {
      // 有有效数据就渲染（即使 HTTP 状态非 2xx，部分代理/后端会误报）
      detail.value = parsed
    } else {
      detail.value = null
      error.value = !r.ok
        ? (r.status === 404 ? '会话不存在' : (j && typeof j === 'object' && 'detail' in j ? String((j as { detail?: string }).detail) : `请求失败 ${r.status}`))
        : (j && typeof j === 'object' && 'detail' in j ? String((j as { detail?: string }).detail) : '返回格式异常，无法显示')
    }
  } catch (e) {
    detail.value = null
    error.value = '网络错误，请确认后端已启动（默认端口 8000）'
  } finally {
    loading.value = false
  }
}

watch(() => props.groupSessionId, (id) => {
  detail.value = null
  error.value = null
  if (id) load()
}, { immediate: true })

defineExpose({ load })
</script>
