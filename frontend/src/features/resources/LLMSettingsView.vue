<template>

  <div class="flex flex-col h-full p-4 overflow-y-auto">

    <div class="max-w-5xl w-full mx-auto">

      <div class="mb-4 flex items-center justify-between gap-2">

        <h2 class="text-2xl font-semibold text-primary mb-1">配置模型</h2>

        <span v-if="defaultLlmLabel" class="text-xs text-muted">当前默认：{{ defaultLlmLabel }}</span>

      </div>

      <div v-if="loading" class="text-sm text-muted py-6">加载中...</div>



      <div v-else-if="!effectiveLlmName" class="text-sm text-muted py-6">

        请在左侧选择一个模型，或点击「新建 LLM」。

      </div>



      <div v-else class="space-y-4">

        <form

          @submit.prevent="saveProvider"

          class="space-y-6 bg-card backdrop-blur rounded-xl border border-border-light shadow-sm px-5 py-6"

        >

          <div class="flex items-center justify-between gap-3">

            <div class="min-w-0 flex-1">

              <label class="block text-sm text-muted mb-1">名称</label>

              <div class="w-full px-3 py-2 bg-input-bg border border-input-border rounded-lg text-primary">
                {{ isNew ? ((edit.model || '').trim() || '保存时使用模型型号') : effectiveLlmName }}
              </div>

            </div>

            <button

              v-if="!isNew && form.default_llm !== effectiveLlmName"

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

              placeholder="https://jeniya.top/v1"

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

            <label class="block text-sm font-medium text-primary mb-1">LiteLLM Provider</label>

            <input

              v-model="edit.provider"

              type="text"

              placeholder="openai / deepseek / anthropic / gemini / bedrock …"

              class="w-full px-3 py-2 bg-input-bg border border-input-border rounded-lg text-primary placeholder-muted focus:outline-none focus:ring-2 focus:ring-input-focus-ring font-mono text-sm"

            />

            <p class="text-xs text-muted mt-1">用于路由：最终模型 id 为 provider/model；留空则默认按 openai 兼容网关处理。</p>

          </div>



          <div>

            <label class="block text-sm font-medium text-primary mb-1">环境变量名</label>

            <input

              v-model="edit.api_key_env"

              type="text"

              placeholder="QWEN_API_KEY"

              class="w-full px-3 py-2 bg-input-bg border border-input-border rounded-lg text-primary placeholder-muted focus:outline-none focus:ring-2 focus:ring-input-focus-ring font-mono text-sm"

            />

          </div>



          <LLMAdvancedParamsPanel
            v-model:params="edit.params"
          />



          <div class="flex items-center justify-start gap-2 pt-3 flex-shrink-0">

            <span v-if="saved" class="text-sm text-accent">已保存</span>

            <button

              v-if="isNew"

              type="button"

              class="inline-flex items-center justify-center px-4 py-2 text-sm font-medium rounded-lg bg-accent text-text-inverse hover:bg-accent-hover disabled:opacity-50"

              @click="saveProvider"

              :disabled="saving"

            >

              {{ saving ? '新建中...' : '新建' }}

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

              class="inline-flex items-center justify-center px-4 py-2 text-sm font-medium rounded-lg bg-list-hover text-primary border border-border-light hover:bg-nav-hover-bg disabled:opacity-50"

              title="导出 ZIP 模型包"

              @click="exportProviderBundle"

            >

              导出

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
import { apiRequest } from '@/api/base'

import { ref, computed, onMounted, watch } from 'vue'
import { appAlert, appConfirm } from '@/composables/useAppDialog'
import LLMAdvancedParamsPanel from './LLMAdvancedParamsPanel.vue'
import type { ModelParams } from './llmSettingsTypes'



const props = defineProps<{

  llmName?: string | null

  /** 父级刷新模型列表时递增，用于导入/覆盖后同步详情 */
  providersVersion?: number

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

      [key: string]: unknown

    }

  >

}>({ default_llm: 'qwen3-max', llm_providers: {} })



function emptyParams(): ModelParams {
  return {
    temperature: '',
    top_p: '',
    max_tokens: '',
    presence_penalty: '',
    frequency_penalty: '',
    seed: '',
    extra_body: '',
  }
}

const edit = ref({

  id: '',

  provider: '',

  base_url: '',

  model: '',

  api_key_env: '',

  params: emptyParams(),

})

function valueToParam(value: unknown): string {
  if (value === undefined || value === null || value === '') return ''
  return String(value)
}

function paramsFromMeta(meta: Record<string, unknown>): ModelParams {
  const params = emptyParams()
  params.temperature = valueToParam(meta.temperature)
  params.top_p = valueToParam(meta.top_p)
  params.max_tokens = valueToParam(meta.max_tokens || meta.max_completion_tokens)
  params.presence_penalty = valueToParam(meta.presence_penalty)
  params.frequency_penalty = valueToParam(meta.frequency_penalty)
  params.seed = valueToParam(meta.seed)

  const extraBody: Record<string, unknown> =
    meta.extra_body && typeof meta.extra_body === 'object' && !Array.isArray(meta.extra_body)
      ? { ...(meta.extra_body as Record<string, unknown>) }
      : {}

  // Migrate legacy flat vendor fields into extra_body for display/edit.
  if (!('enable_thinking' in extraBody) && typeof meta.enable_thinking === 'boolean') {
    extraBody.enable_thinking = meta.enable_thinking
  }
  if (!('thinking_budget' in extraBody) && meta.thinking_budget !== undefined && meta.thinking_budget !== '') {
    extraBody.thinking_budget = meta.thinking_budget
  }
  if (!('thinking' in extraBody) && meta.thinking !== undefined && meta.thinking !== '') {
    if (typeof meta.thinking === 'boolean') {
      extraBody.thinking = { type: meta.thinking ? 'enabled' : 'disabled' }
    } else {
      extraBody.thinking = meta.thinking
    }
  }
  if (!('do_sample' in extraBody) && typeof meta.do_sample === 'boolean') {
    extraBody.do_sample = meta.do_sample
  }
  if (!('top_k' in extraBody) && !('topK' in extraBody) && meta.top_k !== undefined && meta.top_k !== '') {
    extraBody.top_k = meta.top_k
  }
  if (!('thinkingConfig' in extraBody) && meta.gemini_thinking_level === 'low') {
    extraBody.thinkingConfig = { thinkingLevel: 'low' }
  }

  params.extra_body = Object.keys(extraBody).length
    ? JSON.stringify(extraBody, null, 2)
    : ''
  return params
}

function optionalNumber(raw: string, label: string) {
  const value = raw.trim()
  if (!value) return undefined
  const num = Number(value)
  if (!Number.isFinite(num)) throw new Error(`「${label}」需要填写数字`)
  return num
}

function optionalInteger(raw: string, label: string) {
  const num = optionalNumber(raw, label)
  if (num === undefined) return undefined
  if (!Number.isInteger(num)) throw new Error(`「${label}」需要填写整数`)
  return num
}

function assignIfPresent(target: Record<string, unknown>, key: string, value: unknown) {
  if (value !== undefined && value !== '') target[key] = value
}

function buildAdvancedConfig() {
  const params = edit.value.params
  const advanced: Record<string, unknown> = {}
  try {
    assignIfPresent(advanced, 'temperature', optionalNumber(params.temperature, 'temperature'))
    assignIfPresent(advanced, 'top_p', optionalNumber(params.top_p, 'top_p'))
    assignIfPresent(advanced, 'max_tokens', optionalInteger(params.max_tokens, 'max_tokens'))
    assignIfPresent(advanced, 'presence_penalty', optionalNumber(params.presence_penalty, 'presence_penalty'))
    assignIfPresent(advanced, 'frequency_penalty', optionalNumber(params.frequency_penalty, 'frequency_penalty'))
    assignIfPresent(advanced, 'seed', optionalInteger(params.seed, 'seed'))

    const rawExtra = (params.extra_body || '').trim()
    if (rawExtra) {
      let parsed: unknown
      try {
        parsed = JSON.parse(rawExtra)
      } catch {
        throw new Error('extra_body 需要是合法 JSON 对象')
      }
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
        throw new Error('extra_body 需要是 JSON 对象（不能是数组或基础类型）')
      }
      advanced.extra_body = parsed
    }
  } catch (err) {
    void appAlert({ title: '参数不合法', message: err instanceof Error ? err.message : String(err), variant: 'warning' })
    return null
  }
  return advanced
}



const effectiveLlmName = computed(() => (props.llmName || '').trim() || null)

const isNew = computed(() => effectiveLlmName.value === '__new__')

const defaultLlmLabel = computed(() => (form.value.default_llm || '').trim())

function applyProviderToEdit(llmName: string) {
  const meta = form.value.llm_providers[llmName]
  if (!meta) return

  const params = paramsFromMeta(meta as Record<string, unknown>)

  edit.value = {
    id: llmName,
    provider: String((meta as Record<string, unknown>).provider ?? ''),
    base_url: meta.base_url ?? '',
    model: meta.model ?? '',
    api_key_env: meta.api_key_env ?? '',
    params,
  }
}

async function syncEditForProvider(llmName: string | null) {
  if (!llmName) return

  if (llmName === '__new__') {
    edit.value = {
      id: '',
      provider: 'openai',
      base_url: 'https://jeniya.top/v1',
      model: '',
      api_key_env: 'JENIYA_API_KEY',
      params: emptyParams(),
    }
    return
  }

  if (!form.value.llm_providers[llmName]) {
    await load({ silent: true })
  }

  applyProviderToEdit(llmName)
}

async function load(options: { silent?: boolean } = {}) {
  const showLoading = !options.silent
  if (showLoading) loading.value = true

  try {
    const r = await apiRequest('/settings/app')
    const j = await r.json()

    if (j?.status === 'ok' && j?.data) {
      form.value = {
        default_llm: j.data.default_llm ?? 'qwen3-max',
        llm_providers: { ...(j.data.llm_providers || {}) },
      }
    }

  } finally {
    if (showLoading) loading.value = false
  }
}



async function saveAll(nextSelectedId?: string) {

  saving.value = true

  saved.value = false

  try {

    const r = await apiRequest('/settings/app', {

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

      await appAlert({ title: '保存失败', message: (j as { detail?: string }).detail || '保存失败', variant: 'danger' })

    }

  } finally {

    saving.value = false

  }

}



onMounted(async () => {
  await load()
  await syncEditForProvider(effectiveLlmName.value)
})

watch(
  () => effectiveLlmName.value,
  (pid) => {
    void syncEditForProvider(pid)
  },
)

watch(
  () => props.providersVersion,
  () => {
    if (props.providersVersion == null) return
    void (async () => {
      await load({ silent: true })
      await syncEditForProvider(effectiveLlmName.value)
    })()
  },
)



async function saveProvider() {

  const pid = effectiveLlmName.value

  if (!pid) return

  const nid = (edit.value.model || '').trim()

  if (!nid) {

    await appAlert({ title: '无法保存模型', message: '模型型号不能为空', variant: 'warning' })

    return

  }



  const advanced = buildAdvancedConfig()

  if (advanced === null) return



  if (pid === '__new__') {

    if (form.value.llm_providers[nid]) {

      await appAlert({ title: '无法保存模型', message: '同名模型已存在', variant: 'warning' })

      return

    }

    const row: Record<string, unknown> = {

      ...advanced,

      provider: (edit.value.provider || '').trim() || undefined,

      base_url: (edit.value.base_url || '').trim() || undefined,

      model: (edit.value.model || '').trim() || undefined,

      api_key_env: (edit.value.api_key_env || '').trim() || undefined,

    }

    form.value.llm_providers = {

      ...form.value.llm_providers,

      [nid]: row as (typeof form.value.llm_providers)[string],

    }

    await saveAll(nid)

    return

  }



  if (!form.value.llm_providers[pid]) return

  if (nid !== pid && form.value.llm_providers[nid]) {

    await appAlert({ title: '无法保存模型', message: '同名模型已存在', variant: 'warning' })

    return

  }

  const nextProviders = { ...form.value.llm_providers }

  delete nextProviders[pid]

  const nextRow: Record<string, unknown> = {

    ...advanced,

    provider: (edit.value.provider || '').trim() || undefined,

    base_url: (edit.value.base_url || '').trim() || undefined,

    model: (edit.value.model || '').trim() || undefined,

    api_key_env: (edit.value.api_key_env || '').trim() || undefined,

  }

  nextProviders[nid] = nextRow as (typeof form.value.llm_providers)[string]

  form.value.llm_providers = nextProviders

  if (form.value.default_llm === pid) {

    form.value.default_llm = nid

  }

  await saveAll(nid)

}



async function setAsDefault() {

  const pid = effectiveLlmName.value

  if (!pid || pid === '__new__') return

  form.value.default_llm = pid

  await saveAll()

}



async function exportProviderBundle() {

  const pid = effectiveLlmName.value

  if (!pid || pid === '__new__') return

  try {

    const r = await apiRequest(`/settings/llm-providers/${encodeURIComponent(pid)}/export-bundle`)

    if (!r.ok) {

      const j = (await r.json().catch(() => ({}))) as { detail?: string }

      throw new Error(j.detail || '导出失败')

    }

    const blob = await r.blob()

    const url = URL.createObjectURL(blob)

    const a = document.createElement('a')

    a.href = url

    a.download = `llm-bundle-${pid.replace(/[/\\]/g, '_')}.zip`

    a.click()

    URL.revokeObjectURL(url)

  } catch (e) {

    await appAlert({ title: '导出失败', message: (e as Error).message || '导出失败', variant: 'danger' })

  }

}



async function removeProvider() {

  const pid = effectiveLlmName.value

  if (!pid || pid === '__new__') return

  const ok = await appConfirm({
    title: '删除模型',
    message: `确定删除模型「${pid}」？`,
    variant: 'danger',
    confirmText: '删除',
  })
  if (!ok) return

  const next = { ...form.value.llm_providers }

  delete next[pid]

  form.value.llm_providers = next

  await saveAll(Object.keys(next)[0] || undefined)

}

</script>
