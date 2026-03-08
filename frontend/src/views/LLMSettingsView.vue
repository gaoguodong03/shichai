<template>
  <div class="flex flex-col h-full bg-page overflow-y-auto">
    <header class="bg-card px-4 py-3 flex-shrink-0">
      <h1 class="text-lg font-semibold text-primary">模型选择</h1>
    </header>
    <div class="flex-1 overflow-y-auto p-4 space-y-6">
      <section class="space-y-4">
        <h2 class="text-base font-medium text-primary py-1 bg-list-hover rounded-t px-2 -mx-2 mt-0">默认模型</h2>
        <div>
          <label class="block text-sm font-medium text-primary mb-1">默认 LLM</label>
          <select
            v-model="form.default_llm"
            class="w-full max-w-xs px-3 py-2 bg-input-bg border border-input-border rounded-lg text-primary focus:outline-none focus:ring-2 focus:ring-input-focus-ring"
          >
            <option v-for="id in providerIds" :key="id" :value="id">{{ id }}</option>
          </select>
          <p class="mt-1 text-xs text-muted">对话与群聊将使用该模型；API Key 从下方各模型对应的环境变量读取。</p>
        </div>
      </section>

      <section class="space-y-4">
        <div class="flex items-center justify-between">
          <h2 class="text-base font-medium text-primary py-1 bg-list-hover rounded-t px-2 -mx-2 mt-0">模型列表</h2>
          <button
            type="button"
            @click="openAdd"
            class="px-4 py-2 bg-accent text-text-inverse rounded-lg hover:opacity-90"
          >
            + 添加模型
          </button>
        </div>
        <p class="text-sm text-muted">每个模型需配置：URL、模型型号、API Key 环境变量名（密钥在 .env 中配置）。</p>

        <div v-if="loading" class="text-sm text-muted py-4">加载中...</div>
        <div v-else class="space-y-3">
          <div
            v-for="(meta, id) in form.llm_providers"
            :key="id"
            class="rounded-xl p-4 border-2 border-border bg-card text-primary hover:border-border transition-colors"
          >
            <div class="flex items-start justify-between gap-4">
              <div class="flex-1 min-w-0">
                <div class="flex items-center gap-2 mb-2">
                  <h3 class="font-medium text-primary">{{ id }}</h3>
                  <span
                    v-if="form.default_llm === id"
                    class="px-2 py-0.5 text-xs rounded-full bg-accent-subtle text-accent-subtle-text"
                  >
                    默认
                  </span>
                </div>
                <dl class="grid grid-cols-1 sm:grid-cols-3 gap-2 text-sm">
                  <div>
                    <dt class="text-muted">URL</dt>
                    <dd class="font-mono truncate text-primary" :title="meta.base_url">{{ meta.base_url || '—' }}</dd>
                  </div>
                  <div>
                    <dt class="text-muted">模型型号</dt>
                    <dd class="font-mono text-primary">{{ meta.model || '—' }}</dd>
                  </div>
                  <div>
                    <dt class="text-muted">API Key 环境变量</dt>
                    <dd class="font-mono text-primary">{{ meta.api_key_env || '—' }}</dd>
                  </div>
                </dl>
              </div>
              <div class="flex items-center gap-2 flex-shrink-0">
                <button
                  type="button"
                  @click="openEdit(id)"
                  class="px-3 py-1.5 text-sm bg-list-hover text-primary rounded-lg hover:bg-accent-subtle hover:text-accent-subtle-text"
                >
                  编辑
                </button>
                <button
                  type="button"
                  @click="removeProvider(id)"
                  class="px-3 py-1.5 text-sm bg-danger-subtle text-danger rounded-lg hover:opacity-90"
                >
                  删除
                </button>
              </div>
            </div>
          </div>
        </div>
      </section>

      <div class="flex items-center gap-3 pt-2">
        <button
          type="button"
          @click="save"
          :disabled="saving"
          class="px-4 py-2 bg-accent text-text-inverse rounded-lg hover:opacity-90 disabled:opacity-50"
        >
          {{ saving ? '保存中...' : '保存' }}
        </button>
        <span v-if="saved" class="text-sm text-accent">已保存</span>
      </div>
    </div>

    <!-- 添加/编辑弹层 -->
    <div
      v-if="showModal"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
      @click.self="showModal = false"
    >
      <div class="bg-card border border-border rounded-xl shadow-xl max-w-lg w-full mx-4 p-6 text-primary">
        <h3 class="text-lg font-semibold mb-4">{{ editingId == null ? '添加模型' : '编辑模型' }}</h3>
        <div class="space-y-4">
          <div>
            <label class="block text-sm font-medium text-primary mb-1">标识（英文，如 qwen、my-openai）</label>
            <input
              v-model="modalForm.id"
              type="text"
              placeholder="qwen"
              class="w-full px-3 py-2 bg-input-bg border border-input-border rounded-lg text-primary placeholder-muted focus:outline-none focus:ring-2 focus:ring-input-focus-ring"
              :readonly="editingId != null"
            />
          </div>
          <div>
            <label class="block text-sm font-medium text-primary mb-1">URL（API 基础地址）</label>
            <input
              v-model="modalForm.base_url"
              type="url"
              placeholder="https://dashscope.aliyuncs.com/compatible-mode/v1"
              class="w-full px-3 py-2 bg-input-bg border border-input-border rounded-lg text-primary placeholder-muted focus:outline-none focus:ring-2 focus:ring-input-focus-ring"
            />
          </div>
          <div>
            <label class="block text-sm font-medium text-primary mb-1">模型型号</label>
            <input
              v-model="modalForm.model"
              type="text"
              placeholder="qwen3-max"
              class="w-full px-3 py-2 bg-input-bg border border-input-border rounded-lg text-primary placeholder-muted focus:outline-none focus:ring-2 focus:ring-input-focus-ring"
            />
          </div>
          <div>
            <label class="block text-sm font-medium text-primary mb-1">API Key 环境变量名</label>
            <input
              v-model="modalForm.api_key_env"
              type="text"
              placeholder="QWEN_API_KEY"
              class="w-full px-3 py-2 bg-input-bg border border-input-border rounded-lg text-primary placeholder-muted focus:outline-none focus:ring-2 focus:ring-input-focus-ring"
            />
            <p class="mt-1 text-xs text-muted">在 .env 中配置该变量，不在此处填写密钥</p>
          </div>
        </div>
        <div class="flex justify-end gap-2 mt-6">
          <button
            type="button"
            @click="showModal = false"
            class="px-4 py-2 text-primary bg-list-hover rounded-lg hover:bg-accent-subtle hover:text-accent-subtle-text"
          >
            取消
          </button>
          <button
            type="button"
            @click="submitModal"
            class="px-4 py-2 bg-accent text-text-inverse rounded-lg hover:opacity-90"
          >
            {{ editingId == null ? '添加' : '保存' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'

const loading = ref(true)
const saving = ref(false)
const saved = ref(false)
const form = ref<{
  default_llm: string
  llm_providers: Record<string, { base_url?: string; model?: string; api_key_env?: string }>
}>({
  default_llm: 'qwen',
  llm_providers: {},
})

const providerIds = computed(() => Object.keys(form.value.llm_providers))

const showModal = ref(false)
const editingId = ref<string | null>(null)
const modalForm = ref({
  id: '',
  base_url: '',
  model: '',
  api_key_env: '',
})

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

function openAdd() {
  editingId.value = null
  modalForm.value = { id: '', base_url: '', model: '', api_key_env: '' }
  showModal.value = true
}

function openEdit(id: string) {
  const meta = form.value.llm_providers[id]
  if (!meta) return
  editingId.value = id
  modalForm.value = {
    id,
    base_url: meta.base_url ?? '',
    model: meta.model ?? '',
    api_key_env: meta.api_key_env ?? '',
  }
  showModal.value = true
}

function submitModal() {
  const { id, base_url, model, api_key_env } = modalForm.value
  const tid = (id || '').trim().toLowerCase().replace(/\s+/g, '-')
  if (!tid) {
    alert('请填写标识')
    return
  }
  const isNew = editingId.value == null
  if (isNew && form.value.llm_providers[tid]) {
    alert('该标识已存在')
    return
  }
  const next = { ...form.value.llm_providers }
  if (isNew) {
    next[tid] = { base_url: base_url.trim() || undefined, model: model.trim() || undefined, api_key_env: api_key_env.trim() || undefined }
  } else {
    const key = editingId.value!
    if (key !== tid) {
      delete next[key]
      next[tid] = { base_url: base_url.trim() || undefined, model: model.trim() || undefined, api_key_env: api_key_env.trim() || undefined }
      if (form.value.default_llm === key) form.value.default_llm = tid
    } else {
      next[key] = { base_url: base_url.trim() || undefined, model: model.trim() || undefined, api_key_env: api_key_env.trim() || undefined }
    }
  }
  form.value.llm_providers = next
  showModal.value = false
}

function removeProvider(id: string) {
  if (!confirm(`确定删除模型「${id}」？`)) return
  const next = { ...form.value.llm_providers }
  delete next[id]
  form.value.llm_providers = next
  if (form.value.default_llm === id) {
    form.value.default_llm = Object.keys(next)[0] || 'qwen'
  }
}

async function save() {
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
      saved.value = true
      setTimeout(() => { saved.value = false }, 2000)
    } else {
      alert((j as { detail?: string }).detail || '保存失败')
    }
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>
