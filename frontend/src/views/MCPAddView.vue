<template>
  <div class="flex flex-col h-full p-4 overflow-y-auto themed-scrollbar">
    <div class="max-w-5xl w-full mx-auto">
      <div class="mb-4">
        <h2 class="text-2xl font-semibold text-primary mb-1">创建工具</h2>
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
      <div class="flex justify-end gap-3 pt-1">
        <button
          type="submit"
          :disabled="saving"
          class="inline-flex items-center justify-center px-4 py-2 text-sm font-medium rounded-lg bg-accent text-text-inverse hover:bg-accent-hover disabled:opacity-50"
        >
          {{ saving ? '创建中...' : '创建' }}
        </button>
      </div>
      </form>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'

const emit = defineEmits<{ (e: 'created', id: string): void }>()

const saving = ref(false)
const form = ref({
  name: '',
  enabled: true,
  transport: {
    type: 'stdio' as 'stdio' | 'sse' | 'http',
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

function onTransportChange() {
  form.value.transport = {
    type: form.value.transport.type,
    command: '',
    args: [],
    url: '',
    base_url: '',
  }
}

async function submit() {
  if (!form.value.name.trim()) return
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
        ...(form.value.transport.type === 'http' && { base_url: form.value.transport.base_url }),
      },
      metadata: form.value.metadata,
    }
    const r = await fetch('/api/settings/mcp', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    const j = await r.json()
    if (j.status === 'ok' && j.data?.id) {
      emit('created', j.data.id)
    } else {
      alert(j.detail || '创建失败')
    }
  } catch {
    alert('创建失败')
  } finally {
    saving.value = false
  }
}
</script>
