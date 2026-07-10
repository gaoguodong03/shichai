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

            <label class="block text-sm font-medium text-primary mb-1">环境变量名</label>

            <input

              v-model="edit.api_key_env"

              type="text"

              placeholder="QWEN_API_KEY"

              class="w-full px-3 py-2 bg-input-bg border border-input-border rounded-lg text-primary placeholder-muted focus:outline-none focus:ring-2 focus:ring-input-focus-ring font-mono text-sm"

            />

          </div>



          <div class="space-y-4 rounded-xl border border-border-light bg-bg-subtle/40 p-4">

            <div>

              <label class="block text-sm font-medium text-primary mb-1">调用参数（可选）</label>

              <p class="text-xs text-muted">仅开放官网明确支持的字段；留空表示使用厂商默认值。</p>

            </div>

            <div class="grid grid-cols-1 md:grid-cols-3 gap-3">

              <div>
                <label class="block text-xs text-muted mb-1">温度 temperature</label>
                <input v-model.trim="edit.params.temperature" type="number" step="0.01" min="0" placeholder="如 0.7" class="w-full px-3 py-2 bg-input-bg border border-input-border rounded-lg text-primary placeholder-muted focus:outline-none focus:ring-2 focus:ring-input-focus-ring" />
              </div>

              <div>
                <label class="block text-xs text-muted mb-1">核采样 top_p</label>
                <input v-model.trim="edit.params.top_p" type="number" step="0.01" min="0" max="1" placeholder="如 0.95" class="w-full px-3 py-2 bg-input-bg border border-input-border rounded-lg text-primary placeholder-muted focus:outline-none focus:ring-2 focus:ring-input-focus-ring" />
              </div>

              <div>
                <label class="block text-xs text-muted mb-1">最大输出 max_tokens</label>
                <input v-model.trim="edit.params.max_tokens" type="number" step="1" min="1" placeholder="如 2000" class="w-full px-3 py-2 bg-input-bg border border-input-border rounded-lg text-primary placeholder-muted focus:outline-none focus:ring-2 focus:ring-input-focus-ring" />
              </div>

              <div>
                <label class="block text-xs text-muted mb-1">存在惩罚 presence_penalty</label>
                <input v-model.trim="edit.params.presence_penalty" type="number" step="0.01" min="-2" max="2" placeholder="-2 到 2" class="w-full px-3 py-2 bg-input-bg border border-input-border rounded-lg text-primary placeholder-muted focus:outline-none focus:ring-2 focus:ring-input-focus-ring" />
              </div>

              <div>
                <label class="block text-xs text-muted mb-1">频率惩罚 frequency_penalty</label>
                <input v-model.trim="edit.params.frequency_penalty" type="number" step="0.01" min="-2" max="2" placeholder="-2 到 2" class="w-full px-3 py-2 bg-input-bg border border-input-border rounded-lg text-primary placeholder-muted focus:outline-none focus:ring-2 focus:ring-input-focus-ring" />
              </div>

              <div>
                <label class="block text-xs text-muted mb-1">随机种子 seed</label>
                <input v-model.trim="edit.params.seed" type="number" step="1" placeholder="可选整数" class="w-full px-3 py-2 bg-input-bg border border-input-border rounded-lg text-primary placeholder-muted focus:outline-none focus:ring-2 focus:ring-input-focus-ring" />
              </div>

            </div>

            <div v-if="isQwenLike" class="grid grid-cols-1 md:grid-cols-2 gap-3 pt-2 border-t border-border-light">

              <div>
                <label class="block text-xs text-muted mb-1">Qwen/百炼思考模式 enable_thinking</label>
                <select v-model="edit.params.enable_thinking" class="w-full px-3 py-2 bg-input-bg border border-input-border rounded-lg text-primary focus:outline-none focus:ring-2 focus:ring-input-focus-ring">
                  <option value="">默认</option>
                  <option value="true">开启</option>
                  <option value="false">关闭</option>
                </select>
              </div>

              <div>
                <label class="block text-xs text-muted mb-1">思考预算 thinking_budget</label>
                <input v-model.trim="edit.params.thinking_budget" type="number" step="1" min="0" placeholder="如 50" class="w-full px-3 py-2 bg-input-bg border border-input-border rounded-lg text-primary placeholder-muted focus:outline-none focus:ring-2 focus:ring-input-focus-ring" />
              </div>

            </div>

            <div v-if="isDeepSeekLike || isGlmLike" class="grid grid-cols-1 md:grid-cols-2 gap-3 pt-2 border-t border-border-light">

              <div>
                <label class="block text-xs text-muted mb-1">思考模式 thinking</label>
                <select v-model="edit.params.thinking" class="w-full px-3 py-2 bg-input-bg border border-input-border rounded-lg text-primary focus:outline-none focus:ring-2 focus:ring-input-focus-ring">
                  <option value="">默认</option>
                  <option value="true">开启</option>
                  <option value="false">关闭</option>
                </select>
              </div>

              <div v-if="isGlmLike">
                <label class="block text-xs text-muted mb-1">采样 do_sample</label>
                <select v-model="edit.params.do_sample" class="w-full px-3 py-2 bg-input-bg border border-input-border rounded-lg text-primary focus:outline-none focus:ring-2 focus:ring-input-focus-ring">
                  <option value="">默认</option>
                  <option value="true">开启</option>
                  <option value="false">关闭</option>
                </select>
              </div>

            </div>

            <div v-if="isGeminiLike || isClaudeLike" class="grid grid-cols-1 md:grid-cols-2 gap-3 pt-2 border-t border-border-light">

              <div>
                <label class="block text-xs text-muted mb-1">Top K</label>
                <input v-model.trim="edit.params.top_k" type="number" step="1" min="0" placeholder="如 20" class="w-full px-3 py-2 bg-input-bg border border-input-border rounded-lg text-primary placeholder-muted focus:outline-none focus:ring-2 focus:ring-input-focus-ring" />
              </div>

              <div v-if="isGeminiLike">
                <label class="block text-xs text-muted mb-1">Gemini 思考级别 thinkingLevel</label>
                <select v-model="edit.params.gemini_thinking_level" class="w-full px-3 py-2 bg-input-bg border border-input-border rounded-lg text-primary focus:outline-none focus:ring-2 focus:ring-input-focus-ring">
                  <option value="">默认</option>
                  <option value="low">low</option>
                </select>
              </div>

            </div>

          </div>



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



type BoolChoice = '' | 'true' | 'false'
type ModelParams = {
  temperature: string
  top_p: string
  max_tokens: string
  presence_penalty: string
  frequency_penalty: string
  seed: string
  enable_thinking: BoolChoice
  thinking_budget: string
  thinking: BoolChoice
  do_sample: BoolChoice
  top_k: string
  gemini_thinking_level: '' | 'low'
}

function emptyParams(): ModelParams {
  return {
    temperature: '',
    top_p: '',
    max_tokens: '',
    presence_penalty: '',
    frequency_penalty: '',
    seed: '',
    enable_thinking: '',
    thinking_budget: '',
    thinking: '',
    do_sample: '',
    top_k: '',
    gemini_thinking_level: '',
  }
}

const edit = ref({

  id: '',

  base_url: '',

  model: '',

  api_key_env: '',

  params: emptyParams(),

})

const providerFingerprint = computed(() => `${effectiveLlmName.value || ''} ${edit.value.base_url} ${edit.value.model}`.toLowerCase())
const isQwenLike = computed(() => /qwen|dashscope|aliyun|百炼|bailian/.test(providerFingerprint.value))
const isDeepSeekLike = computed(() => isDeepSeekFingerprint(providerFingerprint.value))
const isGlmLike = computed(() => /glm|zhipu|bigmodel|智谱/.test(providerFingerprint.value))
const isGeminiLike = computed(() => /gemini|googleapis|generativelanguage|google/.test(providerFingerprint.value))
const isClaudeLike = computed(() => /claude|anthropic/.test(providerFingerprint.value))

function isDeepSeekFingerprint(fingerprint: string) {
  return /deepseek/.test(fingerprint.toLowerCase())
}

function valueToParam(value: unknown): string {
  if (value === undefined || value === null || value === '') return ''
  return String(value)
}

function boolToChoice(value: unknown): BoolChoice {
  if (value === true) return 'true'
  if (value === false) return 'false'
  if (typeof value === 'string') {
    const normalized = value.trim().toLowerCase()
    if (normalized === 'true') return 'true'
    if (normalized === 'false') return 'false'
  }
  return ''
}

function paramsFromMeta(meta: Record<string, unknown>): ModelParams {
  const params = emptyParams()
  params.temperature = valueToParam(meta.temperature)
  params.top_p = valueToParam(meta.top_p)
  params.max_tokens = valueToParam(meta.max_tokens || meta.max_completion_tokens)
  params.presence_penalty = valueToParam(meta.presence_penalty)
  params.frequency_penalty = valueToParam(meta.frequency_penalty)
  params.seed = valueToParam(meta.seed)
  params.enable_thinking = boolToChoice(meta.enable_thinking)
  params.thinking_budget = valueToParam(meta.thinking_budget)
  params.thinking = boolToChoice(meta.thinking)
  params.do_sample = boolToChoice(meta.do_sample)
  params.top_k = valueToParam(meta.top_k)
  params.gemini_thinking_level = meta.gemini_thinking_level === 'low' ? 'low' : ''

  const extraBody = meta.extra_body && typeof meta.extra_body === 'object' && !Array.isArray(meta.extra_body)
    ? meta.extra_body as Record<string, unknown>
    : {}
  params.enable_thinking ||= boolToChoice(extraBody.enable_thinking)
  params.thinking_budget ||= valueToParam(extraBody.thinking_budget)
  params.thinking ||= boolToChoice(extraBody.thinking)
  params.do_sample ||= boolToChoice(extraBody.do_sample)
  params.top_k ||= valueToParam(extraBody.top_k || extraBody.topK)
  params.gemini_thinking_level ||= extraBody.thinkingConfig && typeof extraBody.thinkingConfig === 'object'
    && (extraBody.thinkingConfig as Record<string, unknown>).thinkingLevel === 'low'
    ? 'low'
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

function choiceToBool(value: BoolChoice) {
  if (value === 'true') return true
  if (value === 'false') return false
  return undefined
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
    assignIfPresent(advanced, 'enable_thinking', choiceToBool(params.enable_thinking))
    assignIfPresent(advanced, 'thinking_budget', optionalInteger(params.thinking_budget, 'thinking_budget'))
    assignIfPresent(advanced, 'thinking', choiceToBool(params.thinking))
    assignIfPresent(advanced, 'do_sample', choiceToBool(params.do_sample))
    assignIfPresent(advanced, 'top_k', optionalInteger(params.top_k, 'top_k'))
    assignIfPresent(advanced, 'gemini_thinking_level', params.gemini_thinking_level)
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
  if (isDeepSeekFingerprint(`${llmName} ${meta.base_url ?? ''} ${meta.model ?? ''}`) && params.thinking === '') {
    params.thinking = 'false'
  }

  edit.value = {
    id: llmName,
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

watch(
  () => providerFingerprint.value,
  () => {
    if (isDeepSeekLike.value && edit.value.params.thinking === '') {
      edit.value.params.thinking = 'false'
    }
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
