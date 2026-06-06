<template>
  <div class="flex flex-col h-full p-4 overflow-y-auto themed-scrollbar">
    <div class="max-w-5xl w-full mx-auto">
      <div class="mb-4">
        <h2 class="text-2xl font-semibold text-primary mb-1">沙箱</h2>
        <p class="text-sm text-muted">选择当前账号使用的沙箱版本，并维护 Python 依赖清单（requirements.txt）。</p>
      </div>

      <div class="bg-card border border-border-light rounded-xl p-5 mb-4">
        <div class="flex items-center justify-between mb-3">
          <div>
            <div class="text-sm font-medium text-primary">沙箱版本</div>
            <div class="text-xs text-muted mt-1">Playwright 版包含浏览器运行时，体积更大；普通版更省资源。</div>
          </div>
          <div class="text-xs text-muted">作用域：当前账号</div>
        </div>

        <div class="grid gap-3 md:grid-cols-2">
          <label
            v-for="option in imageOptions"
            :key="option.value"
            class="cursor-pointer rounded-lg border p-4 transition-colors"
            :class="imageVariant === option.value ? 'border-accent bg-accent/10' : 'border-border hover:bg-list-hover'"
          >
            <div class="flex items-start gap-3">
              <input
                v-model="imageVariant"
                type="radio"
                name="sandbox-image-variant"
                class="mt-1"
                :value="option.value"
                :disabled="loading || savingSettings"
              />
              <div class="min-w-0">
                <div class="text-sm font-medium text-primary">{{ option.label }}</div>
                <div class="text-xs text-muted mt-1">{{ option.description }}</div>
                <div class="text-xs text-muted mt-2 break-all font-mono">{{ option.image }}</div>
              </div>
            </div>
          </label>
        </div>

        <div class="mt-3 flex items-center gap-2">
          <button
            type="button"
            class="inline-flex items-center justify-center px-4 py-2 text-sm font-medium rounded-lg bg-accent text-text-inverse hover:bg-accent-hover disabled:opacity-50"
            :disabled="loading || savingSettings"
            @click="saveSettings"
          >
            {{ savingSettings ? '切换中...' : '保存沙箱版本' }}
          </button>
          <span class="text-xs text-muted break-all">当前镜像：{{ currentImage || '未加载' }}</span>
        </div>
      </div>

      <div class="bg-card border border-border-light rounded-xl p-5">
        <div class="flex items-center justify-between mb-3">
          <div class="text-sm font-medium text-primary">requirements.txt</div>
          <div class="text-xs text-muted">作用域：当前账号</div>
        </div>
        <textarea
          v-model="content"
          rows="16"
          class="w-full bg-input-bg text-primary border border-input-border rounded-lg px-3 py-2 text-sm leading-relaxed font-mono resize-y themed-scrollbar focus:outline-none focus:ring-2 focus:ring-input-focus-ring focus:border-input-focus-ring"
          placeholder="例如：&#10;requests==2.32.3&#10;pydantic>=2.7.0"
        />
        <div class="mt-3 flex items-center gap-2">
          <button
            type="button"
            class="inline-flex items-center justify-center px-4 py-2 text-sm font-medium rounded-lg bg-accent text-text-inverse hover:bg-accent-hover disabled:opacity-50"
            :disabled="loading || saving"
            @click="save"
          >
            {{ saving ? '保存中...' : '保存' }}
          </button>
          <button
            type="button"
            class="inline-flex items-center justify-center px-4 py-2 text-sm font-medium rounded-lg bg-card border border-border text-primary hover:bg-list-hover disabled:opacity-50"
            :disabled="loading || saving"
            @click="load"
          >
            重新加载
          </button>
          <span v-if="saved" class="text-sm text-accent">已保存</span>
        </div>
        <div
          v-if="diagnostic"
          class="mt-3 whitespace-pre-wrap break-words rounded-lg border border-border-light bg-list-hover px-3 py-2 text-xs text-muted font-mono"
        >{{ diagnostic }}</div>
        <div
          v-if="error"
          class="mt-3 whitespace-pre-wrap break-words rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700"
        >{{ error }}</div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { apiRequest } from '@/api/base'
import { onMounted, ref } from 'vue'

type SandboxImageOption = {
  value: string
  label: string
  description: string
  image: string
}

const loading = ref(false)
const saving = ref(false)
const savingSettings = ref(false)
const saved = ref(false)
const error = ref('')
const content = ref('')
const imageVariant = ref('standard')
const currentImage = ref('')
const imageOptions = ref<SandboxImageOption[]>([])
const diagnostic = ref('')

function formatSaveError(j: Record<string, unknown>, fallback: string) {
  const detail = String(j?.detail || j?.message || fallback)
  const data = (j?.data || {}) as Record<string, unknown>
  const rawError = String(data?.error || '')
  if (!rawError || detail.includes(rawError)) return detail
  return `${detail}\n\n${rawError}`
}

async function load() {
  loading.value = true
  error.value = ''
  saved.value = false
  diagnostic.value = ''
  try {
    const [settingsR, requirementsR] = await Promise.all([
      apiRequest('/settings/sandbox'),
      apiRequest('/settings/sandbox/requirements'),
    ])
    const settingsJ = await settingsR.json().catch(() => ({}))
    const requirementsJ = await requirementsR.json().catch(() => ({}))
    if (settingsJ?.status === 'ok') {
      imageVariant.value = String(settingsJ?.data?.image_variant || 'standard')
      currentImage.value = String(settingsJ?.data?.image || '')
      imageOptions.value = Array.isArray(settingsJ?.data?.options) ? settingsJ.data.options : []
    } else {
      error.value = String(settingsJ?.detail || '加载沙箱设置失败')
    }
    if (requirementsJ?.status === 'ok') {
      content.value = String(requirementsJ?.data?.content ?? '')
    } else if (!error.value) {
      error.value = String(requirementsJ?.detail || '加载 requirements.txt 失败')
    }
  } catch (e) {
    error.value = String(e || '加载失败')
  } finally {
    loading.value = false
  }
}

async function saveSettings() {
  savingSettings.value = true
  error.value = ''
  saved.value = false
  diagnostic.value = ''
  try {
    const r = await apiRequest('/settings/sandbox', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ image_variant: imageVariant.value }),
    })
    const j = await r.json().catch(() => ({}))
    if (j?.status === 'ok') {
      imageVariant.value = String(j?.data?.image_variant || imageVariant.value)
      currentImage.value = String(j?.data?.image || currentImage.value)
      saved.value = true
      setTimeout(() => { saved.value = false }, 2000)
    } else {
      error.value = formatSaveError(j as Record<string, unknown>, '保存沙箱版本失败')
    }
  } catch (e) {
    error.value = String(e || '保存沙箱版本失败')
  } finally {
    savingSettings.value = false
  }
}

async function save() {
  saving.value = true
  error.value = ''
  saved.value = false
  diagnostic.value = ''
  try {
    const r = await apiRequest('/settings/sandbox/requirements', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content: content.value }),
    })
    const j = await r.json().catch(() => ({}))
    if (j?.status === 'ok') {
      const data = (j?.data || {}) as Record<string, unknown>
      diagnostic.value = [
        `sandbox_id=${String(data?.sandbox_id || '')}`,
        `image_ref=${String(data?.image_ref || '')}`,
        `requirements_hash=${String(data?.requirements_hash || '')}`,
        `installed=${String(data?.installed_requirements_hash || '')}`,
        `verified=${String(data?.verified_requirements_hash || '')}`,
        `verifier=${String(data?.requirements_verifier_version || '')}`,
      ].join('\n')
      saved.value = true
      setTimeout(() => { saved.value = false }, 2000)
    } else {
      error.value = formatSaveError(j as Record<string, unknown>, '保存失败')
    }
  } catch (e) {
    error.value = String(e || '保存失败')
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>
