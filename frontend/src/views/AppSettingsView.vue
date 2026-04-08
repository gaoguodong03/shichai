<template>
  <div class="flex flex-col h-full bg-page overflow-y-auto">
    <div class="flex-1 overflow-y-auto p-4 themed-scrollbar">
      <div class="max-w-5xl w-full mx-auto space-y-6">
      <div v-if="loading" class="text-sm text-muted">加载中...</div>
      <template v-else>
        <section class="space-y-4">
          <h2 class="text-base font-medium text-primary py-1 bg-list-hover rounded-t px-2 -mx-2 mt-0">主持人设置（全局默认）</h2>
          <p class="text-xs text-muted -mt-1 px-2">
            此处为<strong>账号级</strong>默认规则：适用于普通新建会话、以及主持人调度时的<strong>通用约束</strong>。
            在「资源中心 → 场景」里为<strong>场景主持人（四九）</strong>配置的 Skill 与系统提示会写入该场景会话；
            运行时模型会先看到<strong>下面两段全局提示</strong>，再叠加场景 Skill 全文（二者配合，不是互相替代）。
          </p>
          <div class="space-y-3">
            <div class="rounded-xl border border-border bg-card p-4 space-y-2">
              <div class="text-sm font-medium text-primary">主持人名称（默认：四九）</div>
              <p class="text-xs text-muted">
                用于群聊气泡、成员列表与 @ 提及（如：@四九）。
              </p>
              <input
                v-model="form.host_display_name"
                type="text"
                class="w-full px-3 py-2 bg-input-bg border border-input-border rounded-lg text-primary placeholder-muted focus:outline-none focus:ring-2 focus:ring-input-focus-ring text-sm"
                placeholder="例如：四九"
              />
            </div>

            <div class="rounded-xl border border-border bg-card p-4 space-y-2">
              <div class="text-sm font-medium text-primary">全局调度规则（host_master_prompt）</div>
              <p class="text-xs text-muted">
                约定主持人输出 JSON、next_prompt 自包含、以及招募模式下如何填写 suggested_add_agent_ids。
                每轮系统还会在用户消息里注入「职责边界」「可邀请名单」等，无需把场景专有流程写死在这里。
              </p>
              <textarea
                v-model="form.host_master_prompt"
                rows="16"
                class="w-full px-3 py-2 bg-input-bg border border-input-border rounded-lg text-primary placeholder-muted focus:outline-none focus:ring-2 focus:ring-input-focus-ring font-mono text-sm resize-y themed-scrollbar"
                placeholder="全局调度规则（与场景 Skill 叠加）"
              />
            </div>

            <div class="rounded-xl border border-border bg-card p-4 space-y-2">
              <div class="text-sm font-medium text-primary">尚无协作专家时的组队说明（host_zero_member_policy）</div>
              <p class="text-xs text-muted">
                仅当会话里<strong>还没有任何专家</strong>时追加到系统提示：先推荐 1～3 位可邀请专家，并输出 suggested_add_agent_ids，等待用户确认邀请。
              </p>
              <textarea
                v-model="form.host_zero_member_policy"
                rows="10"
                class="w-full px-3 py-2 bg-input-bg border border-input-border rounded-lg text-primary placeholder-muted focus:outline-none focus:ring-2 focus:ring-input-focus-ring font-mono text-sm resize-y themed-scrollbar"
                placeholder="0 人时的推荐与 JSON 约定"
              />
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
      const d = j.data as Record<string, unknown>
      const next = {
        host_display_name: String(d.host_display_name || '四九'),
        host_master_prompt: String(d.host_master_prompt || ''),
        host_zero_member_policy: String(d.host_zero_member_policy || ''),
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
      const d = j.data as Record<string, unknown>
      form.value = {
        host_display_name: String(d.host_display_name || '四九'),
        host_master_prompt: String(d.host_master_prompt || ''),
        host_zero_member_policy: String(d.host_zero_member_policy || ''),
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
