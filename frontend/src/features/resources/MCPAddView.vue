<template>
  <div class="flex flex-col h-full p-4 overflow-y-auto themed-scrollbar">
    <div class="max-w-5xl w-full mx-auto">
      <div class="mb-4">
        <h2 class="text-2xl font-semibold text-primary mb-1">新建工具</h2>
      </div>
      <form novalidate @submit.prevent="submit" class="space-y-6 bg-card backdrop-blur rounded-xl border border-border-light shadow-sm px-5 py-6">
        <div>
          <label class="block text-sm font-medium text-primary mb-1">工具类型 *</label>
          <select
            v-model="toolType"
            class="w-full px-3 py-2 border border-input-border bg-input-bg text-primary rounded-lg focus:outline-none focus:ring-2 focus:ring-input-focus-ring"
          >
            <option value="mcp">MCP</option>
            <option value="http_api">HTTP API</option>
          </select>
        </div>

        <div v-if="toolType === 'mcp'" class="space-y-2 border-b border-border-light pb-5">
          <label class="block text-sm font-medium text-primary mb-1">导入 mcpServers JSON</label>
          <textarea
            v-model="importJson"
            rows="5"
            class="w-full px-3 py-2 border border-input-border bg-input-bg text-primary rounded-lg font-mono text-sm themed-scrollbar focus:outline-none focus:ring-2 focus:ring-input-focus-ring"
            placeholder="{ &quot;mcpServers&quot;: { &quot;MiniMax&quot;: { &quot;command&quot;: &quot;uvx&quot;, &quot;args&quot;: [&quot;minimax-mcp&quot;], &quot;env&quot;: { &quot;MINIMAX_API_KEY&quot;: &quot;&lt;insert-your-api-key-here&gt;&quot; } } } }"
          />
          <div class="flex justify-start">
            <button
              type="button"
              @click="applyImportedConfig"
              class="inline-flex items-center justify-center px-3 py-2 text-sm font-medium rounded-lg bg-list-hover text-primary border border-border-light hover:bg-nav-hover-bg"
            >
              解析导入
            </button>
          </div>
        </div>

        <div>
          <label class="block text-sm font-medium text-primary mb-1">名称 *</label>
          <input
            v-model="form.name"
            type="text"
            required
            class="w-full px-3 py-2 border border-input-border bg-input-bg text-primary rounded-lg focus:outline-none focus:ring-2 focus:ring-input-focus-ring"
            placeholder="例如：文件系统 MCP"
          />
        </div>
        <template v-if="toolType === 'http_api'">
          <div>
            <label class="block text-sm font-medium text-primary mb-1">请求方法 *</label>
            <select v-model="httpApi.type" class="w-full px-3 py-2 border border-input-border bg-input-bg text-primary rounded-lg focus:outline-none focus:ring-2 focus:ring-input-focus-ring">
              <option value="GET">GET</option>
              <option value="POST">POST</option>
              <option value="PUT">PUT</option>
              <option value="PATCH">PATCH</option>
              <option value="DELETE">DELETE</option>
            </select>
          </div>
          <div>
            <label class="block text-sm font-medium text-primary mb-1">Base URL *</label>
            <input v-model="httpApi.base_url" type="url" class="w-full px-3 py-2 border border-input-border bg-input-bg text-primary rounded-lg focus:outline-none focus:ring-2 focus:ring-input-focus-ring" placeholder="https://api.example.com" />
          </div>
          <div>
            <label class="block text-sm font-medium text-primary mb-1">Path</label>
            <input v-model="httpApi.path" type="text" class="w-full px-3 py-2 border border-input-border bg-input-bg text-primary rounded-lg focus:outline-none focus:ring-2 focus:ring-input-focus-ring" placeholder="/v1/search" />
          </div>
          <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div>
              <label class="block text-sm font-medium text-primary mb-1">Header JSON</label>
              <textarea v-model="httpApi.headerJson" rows="4" class="w-full px-3 py-2 border border-input-border bg-input-bg text-primary rounded-lg font-mono text-sm themed-scrollbar focus:outline-none focus:ring-2 focus:ring-input-focus-ring" placeholder="{ &quot;Authorization&quot;: &quot;Bearer ${vault:token}&quot; }" />
            </div>
            <div>
              <label class="block text-sm font-medium text-primary mb-1">Query JSON</label>
              <textarea v-model="httpApi.queryJson" rows="4" class="w-full px-3 py-2 border border-input-border bg-input-bg text-primary rounded-lg font-mono text-sm themed-scrollbar focus:outline-none focus:ring-2 focus:ring-input-focus-ring" placeholder="{ &quot;q&quot;: &quot;keyword&quot; }" />
            </div>
          </div>
          <div>
            <label class="block text-sm font-medium text-primary mb-1">Body</label>
            <textarea v-model="httpApi.body" rows="4" class="w-full px-3 py-2 border border-input-border bg-input-bg text-primary rounded-lg font-mono text-sm themed-scrollbar focus:outline-none focus:ring-2 focus:ring-input-focus-ring" />
          </div>
        </template>

        <div v-if="toolType === 'mcp'">
          <label class="block text-sm font-medium text-primary mb-1">传输类型 *</label>
          <select
            v-model="form.transport.type"
            @change="onTransportChange"
            class="w-full px-3 py-2 border border-input-border bg-input-bg text-primary rounded-lg focus:outline-none focus:ring-2 focus:ring-input-focus-ring"
          >
            <option value="stdio">stdio</option>
            <option value="sse">SSE</option>
            <option value="http">HTTP</option>
            <option value="streamable_http">Streamable HTTP</option>
            <option value="custom">自定义</option>
          </select>
        </div>
        <template v-if="toolType === 'mcp' && form.transport.type === 'stdio'">
          <div>
            <label class="block text-sm font-medium text-primary mb-1">命令 *</label>
            <input
              v-model="form.transport.command"
              type="text"
              required
              class="w-full px-3 py-2 border border-input-border bg-input-bg text-primary rounded-lg focus:outline-none focus:ring-2 focus:ring-input-focus-ring"
              placeholder="例如：uvx"
            />
          </div>
          <div>
            <label class="block text-sm font-medium text-primary mb-1">参数（每行一个）</label>
            <textarea
              v-model="stdioArgs"
              rows="3"
              class="w-full px-3 py-2 border border-input-border bg-input-bg text-primary rounded-lg themed-scrollbar focus:outline-none focus:ring-2 focus:ring-input-focus-ring"
              placeholder="例如：&#10;minimax-mcp"
            />
          </div>
        </template>
        <template v-if="toolType === 'mcp' && form.transport.type === 'sse'">
          <div>
            <label class="block text-sm font-medium text-primary mb-1">URL *</label>
            <input
              v-model="form.transport.url"
              type="url"
              required
              class="w-full px-3 py-2 border border-input-border bg-input-bg text-primary rounded-lg focus:outline-none focus:ring-2 focus:ring-input-focus-ring"
              placeholder="例如：http://localhost:8000/sse"
            />
          </div>
        </template>
        <template v-if="toolType === 'mcp' && (form.transport.type === 'http' || form.transport.type === 'streamable_http')">
          <div>
            <label class="block text-sm font-medium text-primary mb-1">Base URL *</label>
            <input
              v-model="form.transport.base_url"
              type="url"
              required
              class="w-full px-3 py-2 border border-input-border bg-input-bg text-primary rounded-lg focus:outline-none focus:ring-2 focus:ring-input-focus-ring"
              placeholder="例如：http://localhost:8000/mcp"
            />
          </div>
        </template>
        <template v-if="toolType === 'mcp' && form.transport.type === 'custom'">
          <div>
            <label class="block text-sm font-medium text-primary mb-1">自定义 transport JSON</label>
            <textarea
              v-model="customTransportJson"
              rows="6"
              class="w-full px-3 py-2 border border-input-border bg-input-bg text-primary rounded-lg font-mono text-sm themed-scrollbar focus:outline-none focus:ring-2 focus:ring-input-focus-ring"
              placeholder="{ &quot;url&quot;: &quot;https://example.com/mcp&quot; }"
            />
          </div>
        </template>

        <div v-if="toolType === 'mcp' && (form.transport.type === 'stdio' || form.transport.type === 'custom')" class="space-y-3 border-t border-border-light pt-4">
          <div class="flex items-center justify-between gap-3">
            <label class="block text-sm font-medium text-primary">环境变量</label>
            <button type="button" @click="addEnvRow" class="text-sm text-accent hover:underline">添加</button>
          </div>
          <div v-for="row in envRows" :key="row.id" class="grid grid-cols-1 md:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)_auto_auto] gap-2 items-center">
            <input v-model="row.key" type="text" class="px-3 py-2 border border-input-border bg-input-bg text-primary rounded-lg font-mono text-sm focus:outline-none focus:ring-2 focus:ring-input-focus-ring" placeholder="MINIMAX_API_KEY" />
            <input v-model="row.value" type="text" class="px-3 py-2 border border-input-border bg-input-bg text-primary rounded-lg font-mono text-sm focus:outline-none focus:ring-2 focus:ring-input-focus-ring" placeholder="${vault:minimax}" />
            <select class="px-2 py-2 border border-input-border bg-input-bg text-primary rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-input-focus-ring" @change="setVaultValue(row, $event)">
              <option value="">填入密钥</option>
              <option v-for="s in secretItems" :key="s.id" :value="s.id">{{ s.label || s.id }}</option>
            </select>
            <button type="button" @click="removeEnvRow(row.id)" class="px-2 py-2 text-sm text-danger hover:opacity-80">删除</button>
          </div>
        </div>

        <div v-if="toolType === 'mcp' && (form.transport.type === 'sse' || form.transport.type === 'http' || form.transport.type === 'streamable_http' || form.transport.type === 'custom')" class="space-y-3 border-t border-border-light pt-4">
          <div class="flex items-center justify-between gap-3">
            <label class="block text-sm font-medium text-primary">请求头</label>
            <button type="button" @click="addHeaderRow" class="text-sm text-accent hover:underline">添加</button>
          </div>
          <div v-for="row in headerRows" :key="row.id" class="grid grid-cols-1 md:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)_auto_auto] gap-2 items-center">
            <input v-model="row.key" type="text" class="px-3 py-2 border border-input-border bg-input-bg text-primary rounded-lg font-mono text-sm focus:outline-none focus:ring-2 focus:ring-input-focus-ring" placeholder="Authorization" />
            <input v-model="row.value" type="text" class="px-3 py-2 border border-input-border bg-input-bg text-primary rounded-lg font-mono text-sm focus:outline-none focus:ring-2 focus:ring-input-focus-ring" placeholder="Bearer ${vault:token}" />
            <select class="px-2 py-2 border border-input-border bg-input-bg text-primary rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-input-focus-ring" @change="setVaultValue(row, $event)">
              <option value="">填入密钥</option>
              <option v-for="s in secretItems" :key="s.id" :value="s.id">{{ s.label || s.id }}</option>
            </select>
            <button type="button" @click="removeHeaderRow(row.id)" class="px-2 py-2 text-sm text-danger hover:opacity-80">删除</button>
          </div>
        </div>

        <div>
          <label class="block text-sm font-medium text-primary mb-1">描述</label>
          <textarea
            v-model="form.metadata.description"
            rows="2"
            class="w-full px-3 py-2 border border-input-border bg-input-bg text-primary rounded-lg themed-scrollbar focus:outline-none focus:ring-2 focus:ring-input-focus-ring"
            placeholder="MCP Server 的功能描述"
          />
        </div>
        <div class="flex justify-end gap-3 pt-1">
          <button
            type="submit"
            :disabled="saving"
            class="inline-flex items-center justify-center px-4 py-2 text-sm font-medium rounded-lg bg-accent text-text-inverse hover:bg-accent-hover disabled:opacity-50"
          >
            {{ saving ? '新建中...' : '新建' }}
          </button>
        </div>
      </form>
    </div>
  </div>
</template>

<script setup lang="ts">
import { apiRequest } from '@/api/base'
import { computed, onMounted, ref } from 'vue'
import { useApiSecrets } from '@/composables/useApiSecrets'
import { appAlert } from '@/composables/useAppDialog'
import { buildMcpServerPayload, mapConfigRowsToMap, parseImportedMcpServers, type McpServerDraft } from './mcpConfigContract'

const emit = defineEmits<{ (e: 'created', id: string): void }>()

const { secretItems, loadApiSecrets } = useApiSecrets()

type TransportType = 'stdio' | 'sse' | 'http' | 'streamable_http' | 'custom'
interface KeyValueRow {
  id: number
  key: string
  value: string
}

let rowSeq = 0
const saving = ref(false)
const toolType = ref<'mcp' | 'http_api'>('mcp')
const importJson = ref('')
const customTransportJson = ref('')
const envRows = ref<KeyValueRow[]>([])
const headerRows = ref<KeyValueRow[]>([])
const form = ref({
  name: '',
  transport: {
    type: 'stdio' as TransportType,
    command: '',
    args: [] as string[],
    url: '',
    base_url: '',
  },
  metadata: { description: '' },
})
const httpApi = ref({
  type: 'GET',
  base_url: '',
  path: '',
  headerJson: '',
  queryJson: '',
  body: '',
  timeout_seconds: 60,
})

const stdioArgs = computed({
  get: () => form.value.transport.args?.join('\n') || '',
  set: (v: string) => {
    form.value.transport.args = v.split('\n').map((s) => s.trim()).filter(Boolean)
  },
})

function nextRow(key = '', value = ''): KeyValueRow {
  rowSeq += 1
  return { id: rowSeq, key, value }
}

function mapToRows(value: unknown): KeyValueRow[] {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return []
  return Object.entries(value as Record<string, unknown>).map(([key, val]) => nextRow(key, String(val ?? '')))
}

function addEnvRow() {
  envRows.value.push(nextRow())
}

function removeEnvRow(id: number) {
  envRows.value = envRows.value.filter((row) => row.id !== id)
}

function addHeaderRow() {
  headerRows.value.push(nextRow())
}

function removeHeaderRow(id: number) {
  headerRows.value = headerRows.value.filter((row) => row.id !== id)
}

function setVaultValue(row: KeyValueRow, event: Event) {
  const select = event.target as HTMLSelectElement
  const id = select.value.trim()
  if (id) row.value = '${vault:' + id + '}'
  select.value = ''
}

function normalizeKnownTransportType(type: string): TransportType {
  return ['stdio', 'sse', 'http', 'streamable_http', 'custom'].includes(type) ? type as TransportType : 'custom'
}

function onTransportChange() {
  form.value.transport = {
    type: form.value.transport.type,
    command: '',
    args: [],
    url: '',
    base_url: '',
  }
  envRows.value = []
  headerRows.value = []
  customTransportJson.value = ''
}

function fillFormFromDraft(draft: McpServerDraft) {
  const transport = draft.transport || { type: 'stdio' }
  const originalType = String(transport.type || 'stdio')
  const type = normalizeKnownTransportType(originalType)
  const extraTransport = { ...transport }
  delete extraTransport.type
  delete extraTransport.command
  delete extraTransport.args
  delete extraTransport.url
  delete extraTransport.base_url
  delete extraTransport.env
  delete extraTransport.headers
  if (type === 'custom' && originalType !== 'custom') extraTransport.type = originalType

  form.value = {
    name: draft.name,
    transport: {
      type,
      command: String(transport.command || ''),
      args: Array.isArray(transport.args) ? transport.args.map(String) : [],
      url: String(transport.url || transport.base_url || ''),
      base_url: String(transport.base_url || transport.url || ''),
    },
    metadata: { description: draft.metadata?.description || '' },
  }
  envRows.value = mapToRows(transport.env)
  headerRows.value = mapToRows(transport.headers)
  customTransportJson.value = Object.keys(extraTransport).length ? JSON.stringify(extraTransport, null, 2) : ''
}

async function applyImportedConfig() {
  try {
    const drafts = parseImportedMcpServers(importJson.value)
    if (!drafts.length) return
    fillFormFromDraft(drafts[0])
    const notes = [...(drafts[0].warnings || [])]
    if (drafts.length > 1) notes.push(`已导入第一个 Server；该 JSON 中还有 ${drafts.length - 1} 个 Server 可分别创建。`)
    if (notes.length) {
      await appAlert({ title: '导入完成', message: notes.join('\n') })
    }
  } catch {
    await appAlert({ title: '导入失败', message: 'JSON 格式或 MCP 配置结构不正确', variant: 'danger' })
  }
}

function parseCustomTransport(): Record<string, unknown> {
  if (!customTransportJson.value.trim()) return {}
  const parsed = JSON.parse(customTransportJson.value)
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error('invalid_custom_transport')
  return parsed as Record<string, unknown>
}

function buildDraft(): McpServerDraft {
  const transport: Record<string, unknown> & { type: string } = { type: form.value.transport.type }
  if (form.value.transport.type === 'stdio') {
    transport.command = form.value.transport.command
    transport.args = form.value.transport.args || []
  } else if (form.value.transport.type === 'sse') {
    transport.url = form.value.transport.url
  } else if (form.value.transport.type === 'http' || form.value.transport.type === 'streamable_http') {
    transport.base_url = form.value.transport.base_url
  } else {
    Object.assign(transport, parseCustomTransport())
    if (!transport.type) transport.type = form.value.transport.type
  }

  const env = mapConfigRowsToMap(envRows.value)
  const headers = mapConfigRowsToMap(headerRows.value, { defaultKeyForValuedRow: 'Authorization' })
  if (env) transport.env = env
  if (headers) transport.headers = headers

  return {
    name: form.value.name.trim(),
    transport,
    metadata: { description: form.value.metadata.description || '' },
  }
}

async function validateRequiredFields(): Promise<boolean> {
  if (!form.value.name.trim()) {
    await appAlert({ title: '无法保存工具', message: '工具名称不能为空', variant: 'warning' })
    return false
  }
  if (toolType.value === 'http_api') {
    if (!httpApi.value.base_url.trim()) {
      await appAlert({ title: '无法保存工具', message: 'Base URL 不能为空', variant: 'warning' })
      return false
    }
    try {
      if (httpApi.value.headerJson.trim()) JSON.parse(httpApi.value.headerJson)
      if (httpApi.value.queryJson.trim()) JSON.parse(httpApi.value.queryJson)
    } catch {
      await appAlert({ title: '无法保存工具', message: 'Header/Query 必须是合法 JSON', variant: 'warning' })
      return false
    }
    return true
  }
  if (form.value.transport.type === 'stdio' && !String(form.value.transport.command || '').trim()) {
    await appAlert({ title: '无法保存工具', message: '命令不能为空', variant: 'warning' })
    return false
  }
  if (form.value.transport.type === 'sse' && !String(form.value.transport.url || '').trim()) {
    await appAlert({ title: '无法保存工具', message: 'URL 不能为空', variant: 'warning' })
    return false
  }
  if ((form.value.transport.type === 'http' || form.value.transport.type === 'streamable_http') && !String(form.value.transport.base_url || '').trim()) {
    await appAlert({ title: '无法保存工具', message: 'Base URL 不能为空', variant: 'warning' })
    return false
  }
  return true
}

function buildHttpApiPayload() {
  return {
    name: form.value.name.trim(),
    type: 'http_api',
    description: form.value.metadata.description || '',
    config: {
      type: httpApi.value.type,
      base_url: httpApi.value.base_url.trim(),
      path: httpApi.value.path.trim(),
      header: httpApi.value.headerJson.trim() ? JSON.parse(httpApi.value.headerJson) : {},
      query: httpApi.value.queryJson.trim() ? JSON.parse(httpApi.value.queryJson) : {},
      body: httpApi.value.body,
      timeout_seconds: httpApi.value.timeout_seconds,
    },
  }
}

async function submit() {
  if (!(await validateRequiredFields())) return
  saving.value = true
  try {
    const body = toolType.value === 'http_api' ? buildHttpApiPayload() : buildMcpServerPayload(buildDraft())
    const r = await apiRequest('/settings/mcp', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    const j = await r.json()
    if (j.status === 'ok' && j.data?.name) {
      emit('created', j.data.name)
    } else {
      await appAlert({ title: '新建失败', message: j.detail || '新建失败', variant: 'danger' })
    }
  } catch {
    await appAlert({ title: '新建失败', message: '请检查自定义 transport JSON 或必填字段', variant: 'danger' })
  } finally {
    saving.value = false
  }
}

onMounted(() => {
  loadApiSecrets()
})
</script>
