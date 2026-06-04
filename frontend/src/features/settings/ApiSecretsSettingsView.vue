<template>
  <div class="flex flex-col h-full p-4 overflow-hidden min-h-0">
    <div class="max-w-5xl w-full mx-auto flex flex-1 min-h-0 gap-4">
      <aside
        class="w-52 shrink-0 flex flex-col gap-2 border border-border-light rounded-xl p-3 bg-card backdrop-blur"
      >
        <button
          type="button"
          class="w-full h-10 px-3 rounded-xl text-sm font-semibold flex items-center justify-center gap-1 transition-colors shadow-sm bg-nav-selected-bg text-nav-selected-text hover:bg-nav-hover-bg"
          @click="selectNew"
        >
          <span class="text-base leading-none">＋</span>
          <span>创建密钥</span>
        </button>
        <div class="flex-1 min-h-0 overflow-y-auto themed-scrollbar space-y-1 pt-1">
          <div v-if="loading" class="text-xs text-muted px-2 py-2">加载中...</div>
          <template v-else>
            <button
              v-for="s in items"
              :key="s.id"
              type="button"
              @click="selectedId = s.id"
              :class="[
                'w-full text-left px-2.5 py-2 rounded-lg text-sm transition-colors',
                selectedId === s.id
                  ? 'bg-accent-subtle text-accent-subtle-text'
                  : 'hover:bg-list-hover text-list-hover-text',
              ]"
            >
              <div class="truncate font-medium">{{ s.label || s.id }}</div>
              <div class="truncate text-[11px] text-muted mt-0.5 font-mono">{{ s.id }}</div>
            </button>
            <p v-if="!items.length" class="text-xs text-muted px-2 py-2">暂无条目</p>
          </template>
        </div>
      </aside>

      <div class="flex-1 min-w-0 overflow-y-auto themed-scrollbar">
        <div class="mb-4">
          <h2 class="text-2xl font-semibold text-primary mb-1">密钥管理</h2>
          <p class="text-sm text-muted">
            在此保存 API Key；在「资源中心 → 配置模型」中可为每个提供方选择对应密钥。
          </p>
        </div>

        <div
          v-if="!selectedId"
          class="text-sm text-muted py-12 text-center border border-dashed border-border-light rounded-xl"
        >
          请从左侧选择一条密钥，或点击「创建密钥」。
        </div>

        <form
          v-else-if="selectedId === '__new__'"
          class="space-y-6 bg-card backdrop-blur rounded-xl border border-border-light shadow-sm px-5 py-6"
          @submit.prevent="createSecret"
        >
          <div>
            <label class="block text-sm font-medium text-primary mb-1">标识</label>
            <input
              v-model="draftNew.id"
              type="text"
              required
              class="w-full px-3 py-2 bg-input-bg border border-input-border rounded-lg text-primary placeholder-muted focus:outline-none focus:ring-2 focus:ring-input-focus-ring font-mono text-sm"
              placeholder="例如：QWEN_API_KEY"
            />
            <p class="text-xs text-muted mt-1">字母、数字、连字符、下划线，可与 .env 变量名一致（区分大小写），创建后不可修改。</p>
          </div>
          <div>
            <label class="block text-sm font-medium text-primary mb-1">显示名称（可选）</label>
            <input
              v-model="draftNew.label"
              type="text"
              class="w-full px-3 py-2 bg-input-bg border border-input-border rounded-lg text-primary placeholder-muted focus:outline-none focus:ring-2 focus:ring-input-focus-ring"
              placeholder="例如：Jeniya 主密钥"
            />
          </div>
          <div>
            <label class="block text-sm font-medium text-primary mb-1">API Key</label>
            <input
              v-model="draftNew.api_key"
              type="password"
              autocomplete="new-password"
              required
              class="w-full px-3 py-2 bg-input-bg border border-input-border rounded-lg text-primary placeholder-muted focus:outline-none focus:ring-2 focus:ring-input-focus-ring font-mono text-sm"
              placeholder="sk-..."
            />
          </div>
          <div class="flex items-center justify-start gap-2 pt-3">
            <button
              type="button"
              class="inline-flex items-center justify-center px-4 py-2 text-sm font-medium rounded-lg bg-list-hover text-primary hover:opacity-90"
              @click="selectedId = null"
            >
              取消
            </button>
            <button
              type="submit"
              class="inline-flex items-center justify-center px-4 py-2 text-sm font-medium rounded-lg bg-accent text-text-inverse hover:bg-accent-hover disabled:opacity-50"
              :disabled="saving"
            >
              {{ saving ? '创建中...' : '创建' }}
            </button>
          </div>
        </form>

        <form
          v-else
          class="space-y-6 bg-card backdrop-blur rounded-xl border border-border-light shadow-sm px-5 py-6"
          @submit.prevent="updateSecret"
        >
          <div>
            <label class="block text-sm font-medium text-primary mb-1">标识</label>
            <input
              :value="selectedId"
              type="text"
              readonly
              class="w-full px-3 py-2 bg-page border border-border-light rounded-lg text-muted font-mono text-sm cursor-not-allowed"
            />
          </div>
          <div>
            <label class="block text-sm font-medium text-primary mb-1">显示名称</label>
            <input
              v-model="draftEdit.label"
              type="text"
              class="w-full px-3 py-2 bg-input-bg border border-input-border rounded-lg text-primary focus:outline-none focus:ring-2 focus:ring-input-focus-ring"
            />
          </div>
          <div>
            <label class="block text-sm font-medium text-primary mb-1">更新 API Key（可选）</label>
            <input
              v-model="draftEdit.api_key"
              type="password"
              autocomplete="new-password"
              class="w-full px-3 py-2 bg-input-bg border border-input-border rounded-lg text-primary placeholder-muted focus:outline-none focus:ring-2 focus:ring-input-focus-ring font-mono text-sm"
              placeholder="留空则不修改"
            />
            <p v-if="currentKeySet" class="text-xs text-muted mt-1">当前已保存密钥。</p>
          </div>
          <div class="flex items-center justify-start gap-2 flex-wrap pt-3">
            <button
              type="submit"
              class="inline-flex items-center justify-center px-4 py-2 text-sm font-medium rounded-lg bg-accent text-text-inverse hover:bg-accent-hover disabled:opacity-50"
              :disabled="saving"
            >
              {{ saving ? '保存中...' : '保存' }}
            </button>
            <button
              type="button"
              class="inline-flex items-center justify-center px-4 py-2 text-sm font-medium rounded-lg bg-danger-subtle text-danger hover:opacity-90"
              @click="removeSecret"
            >
              删除
            </button>
          </div>
        </form>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, onMounted } from 'vue'
import { appAlert, appConfirm } from '@/composables/useAppDialog'

type Item = { id: string; label: string; key_set: boolean }

const loading = ref(true)
const saving = ref(false)
const items = ref<Item[]>([])
const selectedId = ref<string | null>(null)

const draftNew = ref({ id: '', label: '', api_key: '' })
const draftEdit = ref({ label: '', api_key: '' })

const currentKeySet = ref(false)

async function load() {
  loading.value = true
  try {
    const r = await fetch('/api/settings/api-secrets')
    const j = await r.json()
    if (j?.status === 'ok' && j?.data?.items) {
      items.value = j.data.items as Item[]
    } else {
      items.value = []
    }
  } finally {
    loading.value = false
  }
}

function selectNew() {
  selectedId.value = '__new__'
  draftNew.value = { id: '', label: '', api_key: '' }
}

async function createSecret() {
  saving.value = true
  try {
    const r = await fetch('/api/settings/api-secrets', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        id: (draftNew.value.id || '').trim(),
        label: (draftNew.value.label || '').trim() || undefined,
        api_key: draftNew.value.api_key,
      }),
    })
    const j = await r.json()
    if (j?.status === 'ok' && j?.data?.id) {
      await load()
      selectedId.value = j.data.id as string
      draftNew.value = { id: '', label: '', api_key: '' }
    } else {
      await appAlert({ title: '创建失败', message: (j as { detail?: string }).detail || '创建失败', variant: 'danger' })
    }
  } finally {
    saving.value = false
  }
}

async function updateSecret() {
  const id = selectedId.value
  if (!id || id === '__new__') return
  saving.value = true
  try {
    const body: { label?: string; api_key?: string } = {
      label: (draftEdit.value.label || '').trim(),
    }
    const nk = (draftEdit.value.api_key || '').trim()
    if (nk) body.api_key = nk
    const r = await fetch(`/api/settings/api-secrets/${encodeURIComponent(id)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    const j = await r.json()
    if (j?.status === 'ok') {
      await load()
      draftEdit.value.api_key = ''
    } else {
      await appAlert({ title: '保存失败', message: (j as { detail?: string }).detail || '保存失败', variant: 'danger' })
    }
  } finally {
    saving.value = false
  }
}

async function removeSecret() {
  const id = selectedId.value
  if (!id || id === '__new__') return
  const ok = await appConfirm({
    title: '删除密钥',
    message: `确定删除密钥「${id}」？引用该密钥的模型配置将需在编辑中重新选择。`,
    variant: 'danger',
    confirmText: '删除',
  })
  if (!ok) return
  saving.value = true
  try {
    const r = await fetch(`/api/settings/api-secrets/${encodeURIComponent(id)}`, {
      method: 'DELETE',
    })
    const j = await r.json()
    if (j?.status === 'ok') {
      selectedId.value = null
      await load()
    } else {
      await appAlert({ title: '删除失败', message: (j as { detail?: string }).detail || '删除失败', variant: 'danger' })
    }
  } finally {
    saving.value = false
  }
}

watch(
  () => selectedId.value,
  (sid) => {
    if (!sid || sid === '__new__') return
    const row = items.value.find((x) => x.id === sid)
    draftEdit.value = { label: row?.label || sid, api_key: '' }
    currentKeySet.value = !!row?.key_set
  },
)

watch(
  () => items.value,
  () => {
    const sid = selectedId.value
    if (!sid || sid === '__new__') return
    const row = items.value.find((x) => x.id === sid)
    if (row) {
      draftEdit.value.label = row.label || sid
      currentKeySet.value = row.key_set
    }
  },
  { deep: true },
)

onMounted(load)
</script>
