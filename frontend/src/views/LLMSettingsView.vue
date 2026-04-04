<template>

  <div class="flex flex-col h-full p-4 overflow-y-auto">

    <div class="max-w-5xl w-full mx-auto">

      <div class="mb-4 flex items-center justify-between gap-2">

        <h2 class="text-2xl font-semibold text-primary mb-1">配置模型</h2>

        <span v-if="defaultLlmLabel" class="text-xs text-muted">当前默认：{{ defaultLlmLabel }}</span>

      </div>

      <div v-if="loading" class="text-sm text-muted py-6">加载中...</div>



      <div v-else-if="!effectiveProviderId" class="text-sm text-muted py-6">

        请在左侧选择一个模型，或点击「新建 LLM」。

      </div>



      <div v-else class="space-y-4">

        <form

          @submit.prevent="saveProvider"

          class="space-y-6 bg-card backdrop-blur rounded-xl border border-border-light shadow-sm px-5 py-6"

        >

          <div class="flex items-center justify-between gap-3">

            <div class="min-w-0 flex-1">

              <label class="block text-sm text-muted mb-1">提供商</label>

              <input

                v-model="edit.id"

                type="text"

                placeholder="例如：qwen、jeniya、gemini"

                class="w-full px-3 py-2 bg-input-bg border border-input-border rounded-lg text-primary placeholder-muted focus:outline-none focus:ring-2 focus:ring-input-focus-ring"

              />

            </div>

            <button

              v-if="!isNew && form.default_llm !== effectiveProviderId"

              type="button"

              class="px-3 py-1.5 text-sm bg-accent-subtle text-accent-subtle-text rounded-lg hover:opacity-90"

              @click="setAsDefault"

            >

              设为默认

            </button>

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

            <label class="block text-sm font-medium text-primary mb-1">API Key</label>

            <p class="text-xs text-muted mb-2">

              从「设置 → 密钥管理」里选一条：左侧列表<strong>第二行小字（标识）</strong>与下拉里括号中的 id 一致即同一密钥。不选时，使用环境变量（如

              <code class="font-mono text-[11px]">QWEN_API_KEY</code>）。

            </p>

            <select

              v-model="edit.api_key_ref"

              class="w-full px-3 py-2 bg-input-bg border border-input-border rounded-lg text-primary focus:outline-none focus:ring-2 focus:ring-input-focus-ring"

            >

              <option value="">（不选密钥，使用环境变量）</option>

              <option v-for="s in secretItems" :key="s.id" :value="s.id">

                {{ secretOptionLabel(s) }}

              </option>

            </select>

          </div>



          <div class="flex items-center justify-end gap-2 px-4 py-3 flex-shrink-0">

            <span v-if="saved" class="text-sm text-accent mr-auto">已保存</span>

            <button

              v-if="isNew"

              type="button"

              class="inline-flex items-center justify-center px-4 py-2 text-sm font-medium rounded-lg bg-accent text-text-inverse hover:bg-accent-hover disabled:opacity-50"

              @click="saveProvider"

              :disabled="saving"

            >

              {{ saving ? '创建中...' : '创建' }}

            </button>

            <button

              v-else

              type="submit"

              :disabled="saving"

              class="inline-flex items-center justify-center px-4 py-2 text-sm font-medium rounded-lg bg-accent text-text-inverse hover:bg-accent-hover disabled:opacity-50"

            >

              {{ saving ? '保存中...' : '保存' }}

            </button>

            <button

              v-if="!isNew"

              type="button"

              class="inline-flex items-center justify-center px-4 py-2 text-sm font-medium rounded-lg bg-danger-subtle text-danger hover:opacity-90"

              @click="removeProvider"

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

  llm_providers: Record<

    string,

    {

      base_url?: string

      model?: string

      api_key_env?: string

      api_key_ref?: string

      api_key_set?: boolean

    }

  >

}>({ default_llm: 'qwen', llm_providers: {} })



const secretItems = ref<{ id: string; label: string; key_set: boolean }[]>([])



const edit = ref({

  id: '',

  base_url: '',

  model: '',

  api_key_env: '',

  api_key_ref: '',

})



const effectiveProviderId = computed(() => (props.providerId || '').trim() || null)

const isNew = computed(() => effectiveProviderId.value === '__new__')

const defaultLlmLabel = computed(() => (form.value.default_llm || '').trim())

/** 与密钥管理侧栏一致：显示名 +（标识 id） */
function secretOptionLabel(s: { id: string; label: string; key_set: boolean }) {
  const name = (s.label || '').trim() || s.id
  const suffix = s.key_set ? '' : '（未配置密钥）'
  if (name === s.id) return `${s.id}${suffix}`
  return `${name}（${s.id}）${suffix}`
}

async function loadSecrets() {

  try {

    const r = await fetch('/api/settings/api-secrets')

    const j = await r.json()

    if (j?.status === 'ok' && j?.data?.items) {

      secretItems.value = j.data.items

    }

  } catch {

    secretItems.value = []

  }

}



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

    await loadSecrets()

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

      setTimeout(() => {

        saved.value = false

      }, 2000)

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

      edit.value = {

        id: '',

        base_url: 'http://jeniya.top/v1',

        model: '',

        api_key_env: 'JENIYA_API_KEY',

        api_key_ref: '',

      }

      return

    }

    const meta = form.value.llm_providers[pid]

    if (!meta) return

    edit.value = {

      id: pid,

      base_url: meta.base_url ?? '',

      model: meta.model ?? '',

      api_key_env: meta.api_key_env ?? '',

      api_key_ref: (meta.api_key_ref || '').trim(),

    }

  },

  { deep: true },

)



async function saveProvider() {

  const pid = effectiveProviderId.value

  if (!pid) return

  const nid = (edit.value.id || '').trim().toLowerCase().replace(/\s+/g, '-')

  if (!nid) {

    alert('请填写标识')

    return

  }



  const refVal = (edit.value.api_key_ref || '').trim()



  if (pid === '__new__') {

    if (form.value.llm_providers[nid]) {

      alert('该标识已存在')

      return

    }

    const row: Record<string, unknown> = {

      base_url: (edit.value.base_url || '').trim() || undefined,

      model: (edit.value.model || '').trim() || undefined,

      api_key_env: (edit.value.api_key_env || '').trim() || undefined,

    }

    if (refVal) row.api_key_ref = refVal

    form.value.llm_providers = {

      ...form.value.llm_providers,

      [nid]: row as (typeof form.value.llm_providers)[string],

    }

    await saveAll(nid)

    return

  }



  if (!form.value.llm_providers[pid]) return

  if (nid !== pid && form.value.llm_providers[nid]) {

    alert('该标识已存在')

    return

  }

  const nextProviders = { ...form.value.llm_providers }

  const baseMeta = nextProviders[pid] || {}

  delete nextProviders[pid]

  const nextRow: Record<string, unknown> = {

    ...baseMeta,

    base_url: (edit.value.base_url || '').trim() || undefined,

    model: (edit.value.model || '').trim() || undefined,

    api_key_env: (edit.value.api_key_env || '').trim() || undefined,

  }

  if (refVal) {

    nextRow.api_key_ref = refVal

  } else {

    nextRow.api_key_ref = ''

  }

  nextProviders[nid] = nextRow as (typeof form.value.llm_providers)[string]

  form.value.llm_providers = nextProviders

  if (form.value.default_llm === pid) {

    form.value.default_llm = nid

  }

  await saveAll(nid)

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

