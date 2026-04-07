<template>
  <div class="flex flex-col h-full bg-page overflow-y-auto">
    <div class="flex-1 overflow-y-auto p-4 themed-scrollbar">
      <div class="max-w-5xl w-full mx-auto space-y-6">
      <div v-if="loading" class="text-sm text-muted">加载中...</div>
      <template v-else>
        <section class="space-y-4">
          <h2 class="text-base font-medium text-primary py-1 bg-list-hover rounded-t px-2 -mx-2 mt-0">主持人设置</h2>
          <div class="space-y-3">
            <div class="rounded-xl border border-border bg-card p-4 space-y-2">
              <div class="text-sm font-medium text-primary">主持人名称（默认：四九）</div>
              <p class="text-xs text-muted">
                这里修改后会用于群聊界面中的主持人称呼与 @ 提及（如：@四九）。
              </p>
              <input
                v-model="form.host_display_name"
                type="text"
                class="w-full px-3 py-2 bg-input-bg border border-input-border rounded-lg text-primary placeholder-muted focus:outline-none focus:ring-2 focus:ring-input-focus-ring text-sm"
                placeholder="例如：四九"
              />
            </div>

            <div class="rounded-xl border border-border bg-card p-4 space-y-2">
              <div class="text-sm font-medium text-primary">主持人调度提示词（规则）</div>
              <p class="text-xs text-muted">
                覆盖所有场景：决定下一发言人、生成 next_prompt、发现不适合时推荐补人（由用户确认后再邀请）。
              </p>
              <textarea
                v-model="form.host_master_prompt"
                rows="16"
                class="w-full px-3 py-2 bg-input-bg border border-input-border rounded-lg text-primary placeholder-muted focus:outline-none focus:ring-2 focus:ring-input-focus-ring font-mono text-sm resize-y themed-scrollbar"
                placeholder="主持人总提示词（host_master_prompt）"
              />
            </div>

            <div class="rounded-xl border border-border bg-card p-4 space-y-2">
              <div class="text-sm font-medium text-primary">0 成员组队策略</div>
              <p class="text-xs text-muted">
                仅在会话里没有任何专家时使用：从可选专家列表中推荐 1~3 位最合适专家，等待用户确认邀请。
              </p>
              <textarea
                v-model="form.host_zero_member_policy"
                rows="10"
                class="w-full px-3 py-2 bg-input-bg border border-input-border rounded-lg text-primary placeholder-muted focus:outline-none focus:ring-2 focus:ring-input-focus-ring font-mono text-sm resize-y themed-scrollbar"
                placeholder="0 成员组队策略（host_zero_member_policy）"
              />
            </div>

            <div class="rounded-xl border border-border bg-card p-4 space-y-3">
              <div class="text-sm font-medium text-primary">TF-IDF 路由阈值</div>
              <p class="text-xs text-muted">
                本地语义匹配用于「多专家时谁发言」与「同一专家多 skill 时选哪个」。保存后立即生效，无需重启后端。
                相似度为余弦相似度（0～1）；分差为第一名与第二名的差值。
              </p>
              <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <label class="space-y-1 block">
                  <span class="text-xs text-muted">专家切换 · 最低相似度</span>
                  <input
                    v-model.number="form.router_tfidf.expert_min_score"
                    type="number"
                    min="0"
                    max="1"
                    step="0.01"
                    class="w-full px-3 py-2 bg-input-bg border border-input-border rounded-lg text-primary text-sm"
                  />
                </label>
                <label class="space-y-1 block">
                  <span class="text-xs text-muted">专家切换 · 与第二名最小分差</span>
                  <input
                    v-model.number="form.router_tfidf.expert_min_delta"
                    type="number"
                    min="0"
                    step="0.01"
                    class="w-full px-3 py-2 bg-input-bg border border-input-border rounded-lg text-primary text-sm"
                  />
                </label>
                <label class="space-y-1 block">
                  <span class="text-xs text-muted">技能路由 · 最低相似度</span>
                  <input
                    v-model.number="form.router_tfidf.skill_min_score"
                    type="number"
                    min="0"
                    max="1"
                    step="0.01"
                    class="w-full px-3 py-2 bg-input-bg border border-input-border rounded-lg text-primary text-sm"
                  />
                </label>
                <label class="space-y-1 block">
                  <span class="text-xs text-muted">技能路由 · 与第二名最小分差</span>
                  <input
                    v-model.number="form.router_tfidf.skill_min_delta"
                    type="number"
                    min="0"
                    step="0.01"
                    class="w-full px-3 py-2 bg-input-bg border border-input-border rounded-lg text-primary text-sm"
                  />
                </label>
              </div>
            </div>
          </div>
        </section>
        <div class="flex items-center justify-start gap-3 pt-3">
          <span v-if="saved" class="text-sm text-accent">已保存</span>
          <button
            @click="save"
            :disabled="saving"
            class="inline-flex items-center justify-center px-4 py-2 text-sm font-medium rounded-lg bg-accent text-text-inverse hover:bg-accent-hover disabled:opacity-50"
          >
            {{ saving ? '保存中...' : '保存' }}
          </button>
          <button
            type="button"
            @click="resetToDefaults"
            :disabled="saving"
            class="inline-flex items-center justify-center px-4 py-2 text-sm font-medium rounded-lg bg-card border border-border text-primary hover:bg-list-hover disabled:opacity-50"
          >
            恢复默认
          </button>
        </div>
      </template>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'

const loading = ref(true)
const saving = ref(false)
const saved = ref(false)
const HOST_NAME_UPDATED_EVENT_NAME = 'dha-host-display-name-updated'

type RouterTfidfForm = {
  expert_min_score: number
  expert_min_delta: number
  skill_min_score: number
  skill_min_delta: number
}

function defaultRouterTfidf(): RouterTfidfForm {
  return {
    expert_min_score: 0.05,
    expert_min_delta: 0.01,
    skill_min_score: 0.12,
    skill_min_delta: 0.01,
  }
}

function mergeRouterTfidf(raw: unknown): RouterTfidfForm {
  const b = defaultRouterTfidf()
  if (!raw || typeof raw !== 'object') return b
  const o = raw as Record<string, unknown>
  for (const k of Object.keys(b) as Array<keyof RouterTfidfForm>) {
    const v = o[k]
    if (typeof v === 'number' && !Number.isNaN(v)) b[k] = v
    else if (typeof v === 'string' && v.trim() !== '') {
      const n = parseFloat(v)
      if (!Number.isNaN(n)) b[k] = n
    }
  }
  return b
}

const form = ref({
  host_display_name: '四九',
  host_master_prompt: '',
  host_zero_member_policy: '',
  router_tfidf: defaultRouterTfidf(),
})

async function load() {
  loading.value = true
  try {
    const r = await fetch('/api/settings/host-prompts')
    const j = await r.json().catch(() => ({}))
    if (j?.status === 'ok' && j?.data) {
      const d = j.data as Record<string, unknown>
      const next = {
        host_display_name: String(d.host_display_name || '四九'),
        host_master_prompt: String(d.host_master_prompt || ''),
        host_zero_member_policy: String(d.host_zero_member_policy || ''),
        router_tfidf: mergeRouterTfidf(d.router_tfidf),
      }
      // 兜底：如果后端未返回默认值（例如后端未重启/路由未更新），则再拉一次默认值填充空项
      const hasAny = [next.host_display_name, next.host_master_prompt, next.host_zero_member_policy].some(
        (v) => String(v || '').trim(),
      )
      if (!hasAny) {
        const rd = await fetch('/api/settings/host-prompts/defaults')
        const jd = await rd.json().catch(() => ({}))
        if (jd?.status === 'ok' && jd?.data) {
          const dd = jd.data as Record<string, unknown>
          for (const k of ['host_display_name', 'host_master_prompt', 'host_zero_member_policy'] as const) {
            const cur = String((next as Record<string, string>)[k] || '').trim()
            if (!cur) (next as Record<string, string>)[k] = String(dd[k] || '')
          }
          next.router_tfidf = mergeRouterTfidf(dd.router_tfidf)
        }
      }
      form.value = next
    }
  } finally {
    loading.value = false
  }
}

async function save() {
  saving.value = true
  saved.value = false
  try {
    const r = await fetch('/api/settings/host-prompts', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        host_display_name: form.value.host_display_name,
        host_master_prompt: form.value.host_master_prompt,
        host_zero_member_policy: form.value.host_zero_member_policy,
        router_tfidf: form.value.router_tfidf,
      }),
    })
    const j = await r.json().catch(() => ({}))
    if (j?.status === 'ok') {
      await load()
      window.dispatchEvent(new CustomEvent(HOST_NAME_UPDATED_EVENT_NAME))
      saved.value = true
      setTimeout(() => { saved.value = false }, 2000)
    } else {
      alert((j as { detail?: string })?.detail || '保存失败')
    }
  } finally {
    saving.value = false
  }
}

async function resetToDefaults() {
  if (!window.confirm('确定恢复为默认主持人设置？这将覆盖你当前的修改。')) return
  saving.value = true
  saved.value = false
  try {
    const r = await fetch('/api/settings/host-prompts/reset', { method: 'POST' })
    const j = await r.json().catch(() => ({}))
    if (j?.status === 'ok' && j?.data) {
      const d = j.data as Record<string, unknown>
      form.value = {
        host_display_name: String(d.host_display_name || '四九'),
        host_master_prompt: String(d.host_master_prompt || ''),
        host_zero_member_policy: String(d.host_zero_member_policy || ''),
        router_tfidf: mergeRouterTfidf(d.router_tfidf),
      }
      window.dispatchEvent(new CustomEvent(HOST_NAME_UPDATED_EVENT_NAME))
      saved.value = true
      setTimeout(() => { saved.value = false }, 2000)
    } else {
      alert((j as { detail?: string })?.detail || '恢复默认失败')
    }
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>
