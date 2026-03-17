<template>
  <div class="flex flex-col h-full bg-page overflow-y-auto">
    <header class="bg-card px-4 py-3 flex-shrink-0 flex items-center justify-between">
      <h1 class="text-lg font-semibold text-primary">LLM 配置</h1>
      <span v-if="defaultLlmLabel" class="text-xs text-muted">当前默认：{{ defaultLlmLabel }}</span>
    </header>

    <div class="flex-1 overflow-y-auto p-4">
      <div v-if="loading" class="text-sm text-muted py-6">加载中...</div>

      <div v-else-if="!effectiveProviderId" class="text-sm text-muted py-6">
        请在左侧选择一个模型，或点击「新建 LLM」。
      </div>

      <div v-else class="max-w-2xl space-y-5">
        <div class="rounded-xl border border-border bg-card p-4">
          <div class="flex items-start justify-between gap-3">
            <div class="min-w-0">
              <div class="text-sm text-muted">Provider</div>
              <div class="text-base font-semibold text-primary truncate">{{ isNew ? '新建 LLM' : effectiveProviderId }}</div>
            </div>
            <div class="flex items-center gap-2">
              <button
                v-if="!isNew && form.default_llm !== effectiveProviderId"
                type="button"
                class="px-3 py-1.5 text-sm bg-accent-subtle text-accent-subtle-text rounded-lg hover:opacity-90"
                @click="setAsDefault"
              >
                设为默认
              </button>
              <button
                v-if="!isNew"
                type="button"
                class="px-3 py-1.5 text-sm bg-danger-subtle text-danger rounded-lg hover:opacity-90"
                @click="removeProvider"
              >
                删除
              </button>
            </div>
          </div>
        </div>

        <div class="rounded-xl border border-border bg-card p-4 space-y-4">
          <div v-if="isNew">
            <label class="block text-sm font-medium text-primary mb-1">标识（英文，如 gemini、my-openai）</label>
            <input
              v-model="edit.id"
              type="text"
              placeholder="gemini"
              class="w-full px-3 py-2 bg-input-bg border border-input-border rounded-lg text-primary placeholder-muted focus:outline-none focus:ring-2 focus:ring-input-focus-ring"
            />
          </div>

          <div>
            <label class="block text-sm font-medium text-primary mb-1">URL</label>
            <input
              v-model="edit.base_url"
              type="url"
              placeholder="http://jeniya.top/v1"
              class="w-full px-3 py-2 bg-input-bg border border-input-border rounded-lg text-primary placeholder-muted focus:outline-none focus:ring-2 focus:ring-input-focus-ring"
            />
          </div>

          <div>
            <label class="block text-sm font-medium text-primary mb-1">模型型号</label>
            <input
              v-model="edit.model"
              type="text"
              placeholder="gemini-3-pro-preview"
              class="w-full px-3 py-2 bg-input-bg border border-input-border rounded-lg text-primary placeholder-muted focus:outline-none focus:ring-2 focus:ring-input-focus-ring"
            />
          </div>

          <div>
            <label class="block text-sm font-medium text-primary mb-1">API Key 环境变量</label>
            <input
              v-model="edit.api_key_env"
              type="text"
              placeholder="JENIYA_API_KEY"
              class="w-full px-3 py-2 bg-input-bg border border-input-border rounded-lg text-primary placeholder-muted focus:outline-none focus:ring-2 focus:ring-input-focus-ring"
            />
          </div>

          <div class="flex items-center gap-3 pt-1">
            <button
              type="button"
              @click="saveProvider"
              :disabled="saving"
              class="px-4 py-2 bg-accent text-text-inverse rounded-lg hover:opacity-90 disabled:opacity-50"
            >
              {{ saving ? '保存中...' : (isNew ? '创建' : '保存') }}
            </button>
            <span v-if="saved" class="text-sm text-accent">已保存</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'

const props = defineProps<{
  providerId?: string | null
}>()

const emit = defineEmits<{
  (e: 'updated', selectedId?: string): void
}>()

const loading = ref(true)
const saving = ref(false)
const saved = ref(false)
const form = ref<{
  default_llm: string
  llm_providers: Record<string, { base_url?: string; model?: string; api_key_env?: string; api_key_set?: boolean }>
}>({ default_llm: 'qwen', llm_providers: {} })

const edit = ref({
  id: '',
  base_url: '',
  model: '',
  api_key_env: '',
})

const effectiveProviderId = computed(() => (props.providerId || '').trim() || null)
const isNew = computed(() => effectiveProviderId.value === '__new__')
const defaultLlmLabel = computed(() => (form.value.default_llm || '').trim())

async function load() {
  loading.value = true
  try {
    const r = await fetch('/api/settings/app')
    const j = await r.json()
    if (j?.status === 'ok' && j?.data) {
      form.value = {
        default_llm: j.data.default_llm ?? 'qwen',
        llm_providers: { ...(j.data.llm_providers || {}) },
      }
    }
  } finally {
    loading.value = false
  }
}

async function saveAll(nextSelectedId?: string) {
  saving.value = true
  saved.value = false
  try {
    const r = await fetch('/api/settings/app', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        default_llm: form.value.default_llm,
        llm_providers: form.value.llm_providers,
      }),
    })
    const j = await r.json()
    if (j?.status === 'ok') {
      await load()
      saved.value = true
      setTimeout(() => { saved.value = false }, 2000)
      emit('updated', nextSelectedId)
    } else {
      alert((j as { detail?: string }).detail || '保存失败')
    }
  } finally {
    saving.value = false
  }
}

onMounted(load)

watch(
  () => [effectiveProviderId.value, form.value.llm_providers],
  () => {
    const pid = effectiveProviderId.value
    if (!pid) return
    if (pid === '__new__') {
      edit.value = { id: '', base_url: 'http://jeniya.top/v1', model: '', api_key_env: 'JENIYA_API_KEY' }
      return
    }
    const meta = form.value.llm_providers[pid]
    if (!meta) return
    edit.value = {
      id: pid,
      base_url: meta.base_url ?? '',
      model: meta.model ?? '',
      api_key_env: meta.api_key_env ?? '',
    }
  },
  { deep: true },
)

async function saveProvider() {
  const pid = effectiveProviderId.value
  if (!pid) return

  if (pid === '__new__') {
    const nid = (edit.value.id || '').trim().toLowerCase().replace(/\s+/g, '-')
    if (!nid) {
      alert('请填写标识')
      return
    }
    if (form.value.llm_providers[nid]) {
      alert('该标识已存在')
      return
    }
    form.value.llm_providers = {
      ...form.value.llm_providers,
      [nid]: {
        base_url: (edit.value.base_url || '').trim() || undefined,
        model: (edit.value.model || '').trim() || undefined,
        api_key_env: (edit.value.api_key_env || '').trim() || undefined,
      },
    }
    await saveAll(nid)
    return
  }

  if (!form.value.llm_providers[pid]) return
  form.value.llm_providers = {
    ...form.value.llm_providers,
    [pid]: {
      ...(form.value.llm_providers[pid] || {}),
      base_url: (edit.value.base_url || '').trim() || undefined,
      model: (edit.value.model || '').trim() || undefined,
      api_key_env: (edit.value.api_key_env || '').trim() || undefined,
    },
  }
  await saveAll()
}

async function setAsDefault() {
  const pid = effectiveProviderId.value
  if (!pid || pid === '__new__') return
  form.value.default_llm = pid
  await saveAll()
}

async function removeProvider() {
  const pid = effectiveProviderId.value
  if (!pid || pid === '__new__') return
  if (!confirm(`确定删除模型「${pid}」？`)) return
  const next = { ...form.value.llm_providers }
  delete next[pid]
  form.value.llm_providers = next
  if (form.value.default_llm === pid) {
    form.value.default_llm = Object.keys(next)[0] || 'qwen'
  }
  await saveAll(form.value.default_llm)
}
</script>
