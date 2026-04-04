<template>
  <div class="flex flex-col h-full p-4 overflow-y-auto themed-scrollbar">
    <div class="max-w-5xl w-full mx-auto">
      <div class="mb-4">
        <h2 class="text-2xl font-semibold text-primary mb-1">配置工具</h2>
      </div>
      <div v-if="loading" class="p-4 text-muted">加载中...</div>
      <form v-else-if="server" @submit.prevent="save" class="space-y-6 bg-card backdrop-blur rounded-xl border border-border-light shadow-sm px-5 py-6">
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
            class="w-full px-3 py-2 border border-input-border bg-input-bg text-primary rounded-lg themed-scrollbar focus:outline-none focus:ring-2 focus:ring-input-focus-ring"
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
          <p class="text-xs text-muted mt-1">
            可在 URL 中使用 <code class="font-mono text-[11px]">${vault:密钥标识}</code> 或
            <code class="font-mono text-[11px]">${ENV_VAR}</code>；认证也可用下方「密钥」。
          </p>
        </div>
        <div class="space-y-3 border-t border-border-light pt-4">
          <p class="text-xs text-muted">
            远程认证（可选）：与「设置 → 密钥管理」一致，保存为
            <code class="font-mono text-[11px]">前缀${vault:标识}</code>。
          </p>
          <div>
            <label class="block text-sm font-medium text-primary mb-1">Header 名称</label>
            <input
              v-model="authHeaderName"
              type="text"
              class="w-full px-3 py-2 border border-input-border bg-input-bg text-primary rounded-lg font-mono text-sm focus:outline-none focus:ring-2 focus:ring-input-focus-ring"
              placeholder="Authorization"
            />
          </div>
          <div>
            <label class="block text-sm font-medium text-primary mb-1">值前缀</label>
            <input
              v-model="authPrefix"
              type="text"
              class="w-full px-3 py-2 border border-input-border bg-input-bg text-primary rounded-lg font-mono text-sm focus:outline-none focus:ring-2 focus:ring-input-focus-ring"
              placeholder="Bearer "
            />
          </div>
          <div>
            <label class="block text-sm font-medium text-primary mb-1">密钥</label>
            <select
              v-model="authVaultRef"
              class="w-full px-3 py-2 border border-input-border bg-input-bg text-primary rounded-lg focus:outline-none focus:ring-2 focus:ring-input-focus-ring"
            >
              <option value="">（不添加认证 Header）</option>
              <option v-for="s in secretItems" :key="s.id" :value="s.id">
                {{ s.label || s.id }}{{ s.key_set ? '' : '（未配置）' }}
              </option>
            </select>
          </div>
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
          <p class="text-xs text-muted mt-1">
            可在 Base URL 中使用 <code class="font-mono text-[11px]">${vault:密钥标识}</code> 或环境变量占位符；也可在下方选择密钥。
          </p>
        </div>
        <div class="space-y-3 border-t border-border-light pt-4">
          <p class="text-xs text-muted">
            远程认证（可选）：与「设置 → 密钥管理」一致，保存为
            <code class="font-mono text-[11px]">前缀${vault:标识}</code>。
          </p>
          <div>
            <label class="block text-sm font-medium text-primary mb-1">Header 名称</label>
            <input
              v-model="authHeaderName"
              type="text"
              class="w-full px-3 py-2 border border-input-border bg-input-bg text-primary rounded-lg font-mono text-sm focus:outline-none focus:ring-2 focus:ring-input-focus-ring"
              placeholder="Authorization"
            />
          </div>
          <div>
            <label class="block text-sm font-medium text-primary mb-1">值前缀</label>
            <input
              v-model="authPrefix"
              type="text"
              class="w-full px-3 py-2 border border-input-border bg-input-bg text-primary rounded-lg font-mono text-sm focus:outline-none focus:ring-2 focus:ring-input-focus-ring"
              placeholder="Bearer "
            />
          </div>
          <div>
            <label class="block text-sm font-medium text-primary mb-1">密钥</label>
            <select
              v-model="authVaultRef"
              class="w-full px-3 py-2 border border-input-border bg-input-bg text-primary rounded-lg focus:outline-none focus:ring-2 focus:ring-input-focus-ring"
            >
              <option value="">（不添加认证 Header）</option>
              <option v-for="s in secretItems" :key="s.id" :value="s.id">
                {{ s.label || s.id }}{{ s.key_set ? '' : '（未配置）' }}
              </option>
            </select>
          </div>
        </div>
      </template>
      <div>
        <label class="block text-sm font-medium text-primary mb-1">描述</label>
        <textarea
          v-model="form.metadata.description"
          rows="2"
          class="w-full px-3 py-2 border border-input-border bg-input-bg text-primary rounded-lg themed-scrollbar focus:outline-none focus:ring-2 focus:ring-input-focus-ring"
        />
      </div>
      <p class="text-xs text-muted">ID: {{ server.id }} · 状态: {{ server.status }} · 工具数: {{ server.tool_count ?? 0 }}</p>
      <div class="flex justify-end gap-2 px-4 py-3 flex-shrink-0">
        <button
          type="submit"
          :disabled="saving"
          class="inline-flex items-center justify-center px-4 py-2 text-sm font-medium rounded-lg bg-accent text-text-inverse hover:bg-accent-hover disabled:opacity-50"
        >
          {{ saving ? '保存中...' : '保存' }}
        </button>
        <button
          type="button"
          @click="deleteServer"
          :disabled="deleting"
          class="inline-flex items-center justify-center px-4 py-2 text-sm font-medium rounded-lg bg-danger-subtle text-danger hover:opacity-90 disabled:opacity-50"
        >
          删除
        </button>
      </div>
      </form>
      <div v-else class="p-4 text-muted">未找到该 Server</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useApiSecrets } from '@/composables/useApiSecrets'

const props = defineProps<{ serverId: string }>()
const emit = defineEmits<{ (e: 'updated'): void; (e: 'deleted'): void }>()

const { secretItems, loadApiSecrets, parseVaultHeader } = useApiSecrets()

const authHeaderName = ref('Authorization')
const authPrefix = ref('Bearer ')
const authVaultRef = ref('')

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
    headers?: Record<string, string>
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
  const auth = parseVaultHeader(t.headers)
  authHeaderName.value = auth.headerName
  authPrefix.value = auth.prefix
  authVaultRef.value = auth.vaultRef
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
  authHeaderName.value = 'Authorization'
  authPrefix.value = 'Bearer '
  authVaultRef.value = ''
}

function buildRemoteHeaders(): Record<string, string> | undefined {
  const vid = authVaultRef.value.trim()
  if (!vid) return undefined
  const hn = authHeaderName.value.trim() || 'Authorization'
  const p = authPrefix.value ?? ''
  return { [hn]: p + '${vault:' + vid + '}' }
}

async function load() {
  if (!props.serverId) return
  loading.value = true
  try {
    await loadApiSecrets()
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
    const remoteHeaders = buildRemoteHeaders()
    const transport: Record<string, unknown> = {
      type: form.value.transport.type,
    }
    if (form.value.transport.type === 'stdio') {
      transport.command = form.value.transport.command
      transport.args = form.value.transport.args || []
    } else if (form.value.transport.type === 'sse') {
      transport.url = form.value.transport.url
      if (remoteHeaders) transport.headers = remoteHeaders
    } else if (form.value.transport.type === 'http') {
      const u = form.value.transport.base_url || form.value.transport.url
      transport.base_url = u
      if (remoteHeaders) transport.headers = remoteHeaders
    }

    const body: Record<string, unknown> = {
      name: form.value.name.trim(),
      enabled: form.value.enabled,
      transport,
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
