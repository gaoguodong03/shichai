<template>
  <div class="flex flex-col h-full bg-card text-primary overflow-y-auto">
    <header class="border-b border-border px-4 py-3 flex items-center justify-between">
      <h1 class="text-lg font-semibold text-primary">MCP Server 详情</h1>
      <div class="flex gap-2">
        <button
          v-if="server"
          @click="deleteServer"
          :disabled="deleting"
          class="px-3 py-1.5 text-sm text-danger border border-danger/40 rounded-lg hover:bg-danger-subtle disabled:opacity-50"
        >
          删除
        </button>
      </div>
    </header>
    <div v-if="loading" class="p-4 text-muted">加载中...</div>
    <form v-else-if="server" @submit.prevent="save" class="flex-1 overflow-y-auto p-4 space-y-4">
      <div>
        <label class="block text-sm font-medium text-primary mb-1">名称 *</label>
        <input
          v-model="form.name"
          type="text"
          required
          class="w-full px-3 py-2 border border-input-border bg-input-bg text-primary rounded-lg focus:outline-none focus:ring-2 focus:ring-input-focus-ring"
        />
      </div>
      <div class="flex items-center gap-2">
        <input v-model="form.enabled" type="checkbox" id="mcp-enabled" class="rounded border-input-border bg-input-bg" />
        <label for="mcp-enabled" class="text-sm text-primary">启用</label>
      </div>
      <div>
        <label class="block text-sm font-medium text-primary mb-1">传输类型 *</label>
        <select
          v-model="form.transport.type"
          @change="onTransportChange"
          class="w-full px-3 py-2 border border-input-border bg-input-bg text-primary rounded-lg focus:outline-none focus:ring-2 focus:ring-input-focus-ring"
        >
          <option value="stdio">stdio</option>
          <option value="sse">SSE</option>
          <option value="http">HTTP</option>
        </select>
      </div>
      <template v-if="form.transport.type === 'stdio'">
        <div>
          <label class="block text-sm font-medium text-primary mb-1">命令 *</label>
          <input
            v-model="form.transport.command"
            type="text"
            required
            class="w-full px-3 py-2 border border-input-border bg-input-bg text-primary rounded-lg focus:outline-none focus:ring-2 focus:ring-input-focus-ring"
          />
        </div>
        <div>
          <label class="block text-sm font-medium text-primary mb-1">参数（每行一个）</label>
          <textarea
            v-model="stdioArgs"
            rows="3"
            class="w-full px-3 py-2 border border-input-border bg-input-bg text-primary rounded-lg focus:outline-none focus:ring-2 focus:ring-input-focus-ring"
          />
        </div>
      </template>
      <template v-if="form.transport.type === 'sse'">
        <div>
          <label class="block text-sm font-medium text-primary mb-1">URL *</label>
          <input
            v-model="form.transport.url"
            type="url"
            required
            class="w-full px-3 py-2 border border-input-border bg-input-bg text-primary rounded-lg focus:outline-none focus:ring-2 focus:ring-input-focus-ring"
          />
        </div>
      </template>
      <template v-if="form.transport.type === 'http'">
        <div>
          <label class="block text-sm font-medium text-primary mb-1">Base URL *</label>
          <input
            v-model="form.transport.base_url"
            type="url"
            required
            class="w-full px-3 py-2 border border-input-border bg-input-bg text-primary rounded-lg focus:outline-none focus:ring-2 focus:ring-input-focus-ring"
          />
        </div>
      </template>
      <div>
        <label class="block text-sm font-medium text-primary mb-1">描述</label>
        <textarea
          v-model="form.metadata.description"
          rows="2"
          class="w-full px-3 py-2 border border-input-border bg-input-bg text-primary rounded-lg focus:outline-none focus:ring-2 focus:ring-input-focus-ring"
        />
      </div>
      <p class="text-xs text-muted">ID: {{ server.id }} · 状态: {{ server.status }} · 工具数: {{ server.tool_count ?? 0 }}</p>
      <div class="flex gap-3">
        <button
          type="submit"
          :disabled="saving"
          class="px-4 py-2 bg-accent text-text-inverse rounded-lg hover:bg-accent-hover disabled:opacity-50"
        >
          {{ saving ? '保存中...' : '保存' }}
        </button>
      </div>
    </form>
    <div v-else class="p-4 text-muted">未找到该 Server</div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'

const props = defineProps<{ serverId: string }>()
const emit = defineEmits<{ (e: 'updated'): void; (e: 'deleted'): void }>()

interface Server {
  id: string
  name: string
  enabled: boolean
  status: string
  tool_count?: number
  transport?: {
    type: string
    command?: string
    args?: string[]
    url?: string
    base_url?: string
  }
  metadata?: { description?: string }
}

const server = ref<Server | null>(null)
const loading = ref(false)
const saving = ref(false)
const deleting = ref(false)
const testing = ref(false)
const form = ref({
  name: '',
  enabled: true,
  transport: {
    type: 'stdio' as string,
    command: '',
    args: [] as string[],
    url: '',
    base_url: '',
  },
  metadata: { description: '' },
})

const stdioArgs = computed({
  get: () => form.value.transport.args?.join('\n') || '',
  set: (v: string) => {
    form.value.transport.args = v.split('\n').map((s) => s.trim()).filter(Boolean)
  },
})

function fillForm(s: Server) {
  const t = (s.transport ?? {}) as NonNullable<Server['transport']>
  const httpUrl = t.base_url || t.url || ''
  form.value = {
    name: s.name,
    enabled: s.enabled,
    transport: {
      type: t.type || 'stdio',
      command: t.command || '',
      args: Array.isArray(t.args) ? [...t.args] : [],
      url: httpUrl,
      base_url: httpUrl,
    },
    metadata: { description: s.metadata?.description || '' },
  }
}

function onTransportChange() {
  form.value.transport = {
    type: form.value.transport.type,
    command: '',
    args: [],
    url: '',
    base_url: '',
  }
}

async function load() {
  if (!props.serverId) return
  loading.value = true
  try {
    const r = await fetch('/api/settings/mcp')
    const j = await r.json()
    if (j.status === 'ok' && j.data?.servers) {
      const s = j.data.servers.find((x: { id: string }) => x.id === props.serverId) || null
      server.value = s
      if (s) fillForm(s)
    }
  } finally {
    loading.value = false
  }
}

async function save() {
  if (!server.value) return
  saving.value = true
  try {
    const body: Record<string, unknown> = {
      name: form.value.name.trim(),
      enabled: form.value.enabled,
      transport: {
        type: form.value.transport.type,
        ...(form.value.transport.type === 'stdio' && {
          command: form.value.transport.command,
          args: form.value.transport.args || [],
        }),
        ...(form.value.transport.type === 'sse' && { url: form.value.transport.url }),
        ...(form.value.transport.type === 'http' && {
          url: form.value.transport.base_url || form.value.transport.url,
          base_url: form.value.transport.base_url || form.value.transport.url,
        }),
      },
      metadata: form.value.metadata,
    }
    const r = await fetch(`/api/settings/mcp/${encodeURIComponent(props.serverId)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    const j = await r.json()
    if (j.status === 'ok') {
      emit('updated')
      await load()
    } else {
      alert(j.detail || '保存失败')
    }
  } finally {
    saving.value = false
  }
}

async function deleteServer() {
  if (!server.value || !confirm('确定要删除该 MCP Server 吗？')) return
  deleting.value = true
  try {
    const r = await fetch(`/api/settings/mcp/${encodeURIComponent(props.serverId)}`, { method: 'DELETE' })
    const j = await r.json()
    if (j.status === 'ok') {
      emit('deleted')
    } else {
      alert(j.detail || '删除失败')
    }
  } finally {
    deleting.value = false
  }
}

async function testConnection() {
  if (!server.value) return
  testing.value = true
  try {
    const r = await fetch(`/api/settings/mcp/${encodeURIComponent(props.serverId)}/test`, {
      method: 'POST',
    })
    const j = await r.json()
    if (j.status === 'ok') {
      if (j.data?.connected) {
        alert(`连接测试成功，耗时 ${j.data?.response_time ?? '?'} ms，工具数约 ${j.data?.tool_count ?? 0}`)
      } else {
        alert(j.data?.error || j.detail || '连接测试失败')
      }
      await load()
    } else {
      alert(j.detail || '连接测试失败')
    }
  } catch (e) {
    console.error('Failed to test MCP connection', e)
    alert('连接测试失败')
  } finally {
    testing.value = false
  }
}

watch(
  () => props.serverId,
  async () => {
    await load()
  },
  { immediate: true },
)
</script>
