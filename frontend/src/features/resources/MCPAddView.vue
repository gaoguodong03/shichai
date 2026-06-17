<template>
  <div class="flex flex-col h-full p-4 overflow-y-auto themed-scrollbar">
    <div class="max-w-5xl w-full mx-auto">
      <div class="mb-4">
        <h2 class="text-2xl font-semibold text-primary mb-1">新建工具</h2>
      </div>
      <form @submit.prevent="submit" class="space-y-6 bg-card backdrop-blur rounded-xl border border-border-light shadow-sm px-5 py-6">
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
            placeholder="例如：python"
          />
        </div>
        <div>
          <label class="block text-sm font-medium text-primary mb-1">参数（每行一个）</label>
          <textarea
            v-model="stdioArgs"
            rows="3"
            class="w-full px-3 py-2 border border-input-border bg-input-bg text-primary rounded-lg themed-scrollbar focus:outline-none focus:ring-2 focus:ring-input-focus-ring"
            placeholder="例如：&#10;-m&#10;mcp_server_fs"
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
            placeholder="例如：http://localhost:8000/sse"
          />
          <p class="text-xs text-muted mt-1">
            可在 URL 中使用 <code class="font-mono text-[11px]">${vault:密钥标识}</code> 或
            <code class="font-mono text-[11px]">${ENV_VAR}</code>；也可在表单底部选择密钥自动注入 URL。
          </p>
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
            placeholder="例如：http://localhost:8000/mcp"
          />
          <p class="text-xs text-muted mt-1">
            可在 Base URL 中使用 <code class="font-mono text-[11px]">${vault:密钥标识}</code> 或环境变量占位符；也可在表单底部选择密钥自动注入 URL。
          </p>
        </div>
      </template>
      <div>
        <label class="block text-sm font-medium text-primary mb-1">描述</label>
        <textarea
          v-model="form.metadata.description"
          rows="2"
          class="w-full px-3 py-2 border border-input-border bg-input-bg text-primary rounded-lg themed-scrollbar focus:outline-none focus:ring-2 focus:ring-input-focus-ring"
          placeholder="MCP Server 的功能描述"
        />
      </div>
      <div v-if="form.transport.type === 'sse' || form.transport.type === 'http'" class="space-y-2 border-t border-border-light pt-4">
        <label class="block text-sm font-medium text-primary mb-1">密钥</label>
        <select
          v-model="authVaultRef"
          class="w-full px-3 py-2 border border-input-border bg-input-bg text-primary rounded-lg focus:outline-none focus:ring-2 focus:ring-input-focus-ring"
        >
          <option value="">（不注入密钥）</option>
          <option v-for="s in secretItems" :key="s.id" :value="s.id">
            {{ s.label || s.id }}{{ s.key_set ? '' : '（未配置）' }}
          </option>
        </select>
        <p class="text-xs text-muted">
          选中后，保存时会把 <code class="font-mono text-[11px]">${vault:密钥标识}</code> 注入到 URL 末尾；如果 URL 已有 vault 占位符，则替换为当前密钥。
        </p>
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
import { ref, computed, onMounted } from 'vue'
import { useApiSecrets } from '@/composables/useApiSecrets'
import { appAlert } from '@/composables/useAppDialog'

const emit = defineEmits<{ (e: 'created', id: string): void }>()

const { secretItems, loadApiSecrets } = useApiSecrets()
const authVaultRef = ref('')
const stdioEnvName = ref('QWEN_AUDIO_API_KEY')
const stdioVaultRef = ref('')

const saving = ref(false)
const form = ref({
  name: '',
  transport: {
    type: 'stdio' as 'stdio' | 'sse' | 'http',
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

function onTransportChange() {
  form.value.transport = {
    type: form.value.transport.type,
    command: '',
    args: [],
    url: '',
    base_url: '',
    env: {},
  }
  authVaultRef.value = ''
  stdioEnvName.value = 'QWEN_AUDIO_API_KEY'
  stdioVaultRef.value = ''
}

function applySelectedVaultToUrl(current: string): string {
  const vid = authVaultRef.value.trim()
  const value = current || ''
  if (!vid) return value.replace(/\$\{vault:[^}]+\}/g, '')
  const placeholder = '${vault:' + vid + '}'
  if (/\$\{vault:[^}]+\}/.test(value)) return value.replace(/\$\{vault:[^}]+\}/g, placeholder)
  return value + placeholder
}

function buildStdioEnv(): Record<string, string> | undefined {
  const vid = stdioVaultRef.value.trim()
  const name = stdioEnvName.value.trim()
  if (!vid || !name) return undefined
  return { [name]: '${vault:' + vid + '}' }
}

async function submit() {
  if (!form.value.name.trim()) return
  saving.value = true
  try {
    const transport: Record<string, unknown> = {
      type: form.value.transport.type,
    }
    if (form.value.transport.type === 'stdio') {
      transport.command = form.value.transport.command
      transport.args = form.value.transport.args || []
      const stdioEnv = buildStdioEnv()
      if (stdioEnv) transport.env = stdioEnv
    } else if (form.value.transport.type === 'sse') {
      transport.url = applySelectedVaultToUrl(form.value.transport.url)
    } else if (form.value.transport.type === 'http') {
      transport.base_url = applySelectedVaultToUrl(form.value.transport.base_url)
    }

    const body: Record<string, unknown> = {
      name: form.value.name.trim(),
      transport,
      metadata: form.value.metadata,
    }
    const r = await apiRequest('/settings/mcp', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    const j = await r.json()
    if (j.status === 'ok' && j.data?.id) {
      emit('created', j.data.id)
    } else {
      await appAlert({ title: '新建失败', message: j.detail || '新建失败', variant: 'danger' })
    }
  } catch {
    await appAlert({ title: '新建失败', message: '新建失败', variant: 'danger' })
  } finally {
    saving.value = false
  }
}

onMounted(() => {
  loadApiSecrets()
})
</script>
