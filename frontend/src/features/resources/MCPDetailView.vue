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
      <div>
        <label class="block text-sm font-medium text-primary mb-1">描述</label>
        <textarea
          v-model="form.metadata.description"
          rows="2"
          class="w-full px-3 py-2 border border-input-border bg-input-bg text-primary rounded-lg themed-scrollbar focus:outline-none focus:ring-2 focus:ring-input-focus-ring"
        />
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
        <div class="space-y-3 border-t border-border-light pt-4">
          <p class="text-xs text-muted">
            本地进程密钥（可选）：选择密钥后会保存到
            <code class="font-mono text-[11px]">transport.env</code>，运行时注入给 stdio MCP。
          </p>
          <div>
            <label class="block text-sm font-medium text-primary mb-1">环境变量名</label>
            <input
              v-model="stdioEnvName"
              type="text"
              class="w-full px-3 py-2 border border-input-border bg-input-bg text-primary rounded-lg font-mono text-sm focus:outline-none focus:ring-2 focus:ring-input-focus-ring"
              placeholder="QWEN_AUDIO_API_KEY"
            />
          </div>
          <div>
            <label class="block text-sm font-medium text-primary mb-1">密钥</label>
            <select
              v-model="stdioVaultRef"
              class="w-full px-3 py-2 border border-input-border bg-input-bg text-primary rounded-lg focus:outline-none focus:ring-2 focus:ring-input-focus-ring"
            >
              <option value="">（不注入密钥）</option>
              <option v-for="s in secretItems" :key="s.id" :value="s.id">
                {{ s.label || s.id }}{{ s.key_set ? '' : '（未配置）' }}
              </option>
            </select>
          </div>
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
      <div class="pt-4 border-t border-border-light space-y-2">
        <div class="text-sm font-medium text-primary">访问方式</div>
        <div v-if="sharePublishing" class="text-sm text-muted py-1">正在生成访问链接...</div>
        <p v-else-if="shareError" class="text-sm text-danger">{{ shareError }}</p>
        <a
          v-else-if="shareFullUrl"
          class="block w-full rounded-xl border border-border-light bg-page px-4 py-3 font-mono text-sm text-accent break-all hover:underline"
          :href="shareFullUrl"
          target="_blank"
          rel="noopener noreferrer"
        >{{ shareFullUrl }}</a>
        <p v-else class="text-sm text-muted">保存工具后自动生成访问链接。</p>
      </div>
      <div class="flex items-center justify-start gap-2 pt-3 flex-shrink-0">
        <button
          type="submit"
          :disabled="saving"
          class="inline-flex items-center justify-center px-4 py-2 text-sm font-medium rounded-lg bg-accent text-text-inverse hover:bg-accent-hover disabled:opacity-50"
        >
          {{ saving ? '保存中...' : '保存' }}
        </button>
        <button
          type="button"
          @click="exportZip"
          :disabled="exporting"
          class="inline-flex items-center justify-center px-4 py-2 text-sm font-medium rounded-lg bg-list-hover text-primary border border-border-light hover:bg-nav-hover-bg disabled:opacity-50"
        >
          {{ exporting ? '导出中...' : '导出' }}
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
import { appAlert, appConfirm } from '@/composables/useAppDialog'

const props = defineProps<{ serverId: string }>()
const emit = defineEmits<{ (e: 'updated'): void; (e: 'deleted'): void }>()

const { secretItems, loadApiSecrets, parseVaultHeader } = useApiSecrets()

const authHeaderName = ref('Authorization')
const authPrefix = ref('Bearer ')
const authVaultRef = ref('')
const stdioEnvName = ref('QWEN_AUDIO_API_KEY')
const stdioVaultRef = ref('')

interface Server {
  id: string
  name: string
  transport?: {
    type: string
    command?: string
    args?: string[]
    url?: string
    base_url?: string
    headers?: Record<string, string>
    env?: Record<string, string>
  }
  metadata?: { description?: string }
}

const server = ref<Server | null>(null)
const loading = ref(false)
const saving = ref(false)
const deleting = ref(false)
const exporting = ref(false)
const shareId = ref('')
const sharePublishing = ref(false)
const shareError = ref('')
const shareFullUrl = computed(() =>
  shareId.value ? `${publicAppOriginForShareLink()}/share/run?id=${encodeURIComponent(shareId.value)}` : '',
)
const form = ref({
  name: '',
  transport: {
    type: 'stdio' as string,
    command: '',
    args: [] as string[],
    url: '',
    base_url: '',
    env: {} as Record<string, string>,
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
  const stdioAuth = parseStdioVaultEnv(t.env)
  authHeaderName.value = auth.headerName
  authPrefix.value = auth.prefix
  authVaultRef.value = auth.vaultRef
  stdioEnvName.value = stdioAuth.envName
  stdioVaultRef.value = stdioAuth.vaultRef
  form.value = {
    name: s.name,
    transport: {
      type: t.type || 'stdio',
      command: t.command || '',
      args: Array.isArray(t.args) ? [...t.args] : [],
      url: httpUrl,
      base_url: httpUrl,
      env: t.env && typeof t.env === 'object' ? { ...t.env } : {},
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
    env: {},
  }
  authHeaderName.value = 'Authorization'
  authPrefix.value = 'Bearer '
  authVaultRef.value = ''
  stdioEnvName.value = 'QWEN_AUDIO_API_KEY'
  stdioVaultRef.value = ''
}

function buildRemoteHeaders(): Record<string, string> | undefined {
  const vid = authVaultRef.value.trim()
  if (!vid) return undefined
  const hn = authHeaderName.value.trim() || 'Authorization'
  const p = authPrefix.value ?? ''
  return { [hn]: p + '${vault:' + vid + '}' }
}

function parseStdioVaultEnv(env?: Record<string, string>): { envName: string; vaultRef: string } {
  const fallback = { envName: 'QWEN_AUDIO_API_KEY', vaultRef: '' }
  if (!env) return fallback
  const preferred = env.QWEN_AUDIO_API_KEY ? ['QWEN_AUDIO_API_KEY'] : []
  const names = [...preferred, ...Object.keys(env).filter((k) => k !== 'QWEN_AUDIO_API_KEY')]
  for (const name of names) {
    const m = /^\$\{vault:([^}]+)\}\s*$/.exec(String(env[name] || ''))
    if (m) return { envName: name, vaultRef: m[1] }
  }
  return fallback
}

function buildStdioEnv(): Record<string, string> | undefined {
  const env = { ...(form.value.transport.env || {}) }
  const name = stdioEnvName.value.trim()
  if (!name) return Object.keys(env).length ? env : undefined
  if (stdioVaultRef.value.trim()) {
    env[name] = '${vault:' + stdioVaultRef.value.trim() + '}'
  } else if (/^\$\{vault:[^}]+\}\s*$/.test(String(env[name] || ''))) {
    delete env[name]
  }
  return Object.keys(env).length ? env : undefined
}

async function load(options: { silent?: boolean } = {}) {
  if (!props.serverId) return
  const showPageLoading = !options.silent && (!server.value || (server.value.id !== props.serverId && !saving.value))
  if (showPageLoading) loading.value = true
  try {
    await loadApiSecrets()
    const r = await fetch('/api/settings/mcp')
    const j = await r.json()
    if (j.status === 'ok' && j.data?.servers) {
      const s = j.data.servers.find((x: { id: string }) => x.id === props.serverId) || null
      if (s || !options.silent) server.value = s
      if (s) fillForm(s)
    }
  } finally {
    if (showPageLoading) loading.value = false
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
      const stdioEnv = buildStdioEnv()
      if (stdioEnv) transport.env = stdioEnv
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
      const savedServer = j.data && typeof j.data === 'object' ? j.data as Partial<Server> : null
      if (savedServer) {
        server.value = { ...server.value, ...savedServer }
        fillForm(server.value)
      }
      emit('updated')
      await load({ silent: true })
    } else {
      await appAlert({ title: '保存失败', message: j.detail || '保存失败', variant: 'danger' })
    }
  } finally {
    saving.value = false
  }
}

async function deleteServer() {
  if (!server.value) return
  const ok = await appConfirm({
    title: '删除 MCP Server',
    message: '确定要删除该 MCP Server 吗？',
    variant: 'danger',
    confirmText: '删除',
  })
  if (!ok) return
  deleting.value = true
  try {
    const r = await fetch(`/api/settings/mcp/${encodeURIComponent(props.serverId)}`, { method: 'DELETE' })
    const j = await r.json()
    if (j.status === 'ok') {
      emit('deleted')
    } else {
      await appAlert({ title: '删除失败', message: j.detail || '删除失败', variant: 'danger' })
    }
  } finally {
    deleting.value = false
  }
}

async function exportZip() {
  if (!props.serverId || !server.value) return
  exporting.value = true
  try {
    const r = await fetch(`/api/settings/mcp/${encodeURIComponent(props.serverId)}/export-zip`)
    if (!r.ok) {
      let msg = '导出失败'
      try {
        const j = (await r.json()) as { detail?: string }
        if (j.detail) msg = j.detail
      } catch {
        /* ignore */
      }
      await appAlert({ title: '导出失败', message: msg, variant: 'danger' })
      return
    }
    const blob = await r.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${props.serverId}.zip`
    a.click()
    URL.revokeObjectURL(url)
  } finally {
    exporting.value = false
  }
}

function publicAppOriginForShareLink(): string {
  const raw = import.meta.env.VITE_PUBLIC_APP_ORIGIN
  if (typeof raw === 'string' && raw.trim()) return raw.trim().replace(/\/$/, '')
  return window.location.origin
}

async function ensureServerSharePublished() {
  if (!props.serverId) return
  const id = props.serverId
  sharePublishing.value = true
  shareError.value = ''
  try {
    let nextShareId: string | null = null
    const r0 = await fetch(`/api/settings/mcp/${encodeURIComponent(id)}/share-link`)
    const j0 = await r0.json().catch(() => ({}))
    if (j0?.status === 'ok' && j0?.data?.share_id) nextShareId = String(j0.data.share_id)
    if (!nextShareId) {
      const r1 = await fetch(`/api/settings/mcp/${encodeURIComponent(id)}/publish-share`, { method: 'POST' })
      const j1 = await r1.json().catch(() => ({}))
      if (j1?.status === 'ok' && j1?.data?.share_id) nextShareId = String(j1.data.share_id)
    }
    if (!nextShareId) throw new Error('生成访问链接失败')
    if (props.serverId === id) shareId.value = nextShareId
  } catch (e) {
    if (props.serverId === id) shareError.value = (e as Error).message || '生成访问链接失败'
  } finally {
    if (props.serverId === id) sharePublishing.value = false
  }
}

watch(
  () => props.serverId,
  async () => {
    shareId.value = ''
    shareError.value = ''
    await load()
    if (props.serverId) void ensureServerSharePublished()
  },
  { immediate: true },
)
</script>
