<template>
  <div class="flex flex-col h-full bg-page overflow-y-auto">
    <header class="bg-card px-4 py-3 flex-shrink-0">
      <h1 class="text-lg font-semibold text-primary">主持人设置</h1>
    </header>
    <div class="flex-1 overflow-y-auto p-4 space-y-6">
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
                class="w-full px-3 py-2 bg-input-bg border border-input-border rounded-lg text-primary placeholder-muted focus:outline-none focus:ring-2 focus:ring-input-focus-ring font-mono text-sm"
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
                class="w-full px-3 py-2 bg-input-bg border border-input-border rounded-lg text-primary placeholder-muted focus:outline-none focus:ring-2 focus:ring-input-focus-ring font-mono text-sm"
                placeholder="0 成员组队策略（host_zero_member_policy）"
              />
            </div>
          </div>
        </section>
        <div class="flex items-center gap-3">
          <button
            @click="save"
            :disabled="saving"
            class="px-4 py-2 bg-accent text-text-inverse rounded-lg hover:opacity-90 disabled:opacity-50"
          >
            {{ saving ? '保存中...' : '保存' }}
          </button>
          <button
            type="button"
            @click="resetToDefaults"
            :disabled="saving"
            class="px-4 py-2 bg-card border border-border text-primary rounded-lg hover:bg-list-hover disabled:opacity-50"
          >
            恢复默认
          </button>
          <span v-if="saved" class="text-sm text-accent">已保存</span>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'

const loading = ref(true)
const saving = ref(false)
const saved = ref(false)
const HOST_NAME_UPDATED_EVENT_NAME = 'dha-host-display-name-updated'

const form = ref({
  host_display_name: '四九',
  host_master_prompt: '',
  host_zero_member_policy: '',
})

async function load() {
  loading.value = true
  try {
    const r = await fetch('/api/settings/host-prompts')
    const j = await r.json().catch(() => ({}))
    if (j?.status === 'ok' && j?.data) {
      const next = {
        host_display_name: String(j.data.host_display_name || '四九'),
        host_master_prompt: String(j.data.host_master_prompt || ''),
        host_zero_member_policy: String(j.data.host_zero_member_policy || ''),
      }
      // 兜底：如果后端未返回默认值（例如后端未重启/路由未更新），则再拉一次默认值填充空项
      const hasAny = Object.values(next).some((v) => String(v || '').trim())
      if (!hasAny) {
        const rd = await fetch('/api/settings/host-prompts/defaults')
        const jd = await rd.json().catch(() => ({}))
        if (jd?.status === 'ok' && jd?.data) {
          for (const k of Object.keys(next) as Array<keyof typeof next>) {
            const cur = String(next[k] || '').trim()
            if (!cur) (next[k] as string) = String(jd.data[k] || '')
          }
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
      form.value = {
        host_display_name: String(j.data.host_display_name || '四九'),
        host_master_prompt: String(j.data.host_master_prompt || ''),
        host_zero_member_policy: String(j.data.host_zero_member_policy || ''),
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
