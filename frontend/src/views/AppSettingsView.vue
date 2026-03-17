<template>
  <div class="flex flex-col h-full bg-page overflow-y-auto">
    <header class="bg-card px-4 py-3 flex-shrink-0">
      <h1 class="text-lg font-semibold text-primary">主持人提示词</h1>
    </header>
    <div class="flex-1 overflow-y-auto p-4 space-y-6">
      <div v-if="loading" class="text-sm text-muted">加载中...</div>
      <template v-else>
        <section class="space-y-4">
          <h2 class="text-base font-medium text-primary py-1 bg-list-hover rounded-t px-2 -mx-2 mt-0">主持人提示词</h2>
          <div class="space-y-3">
            <div class="rounded-xl border border-border bg-card p-4 space-y-2">
              <div class="text-sm font-medium text-primary">主持人输入模板（上下文段）</div>
              <p class="text-xs text-muted">
                对应 `group_chat.py` 中主持人用于决定下一位发言人的那段输入。可用变量：`{dha_text}`、`{discussion_goal}`、`{recent_messages}`。
              </p>
              <textarea
                v-model="form.host_context_template"
                rows="10"
                class="w-full px-3 py-2 bg-input-bg border border-input-border rounded-lg text-primary placeholder-muted focus:outline-none focus:ring-2 focus:ring-input-focus-ring font-mono text-sm"
                placeholder="主持人输入模板（上下文段）"
              />
            </div>

            <div class="rounded-xl border border-border bg-card p-4 space-y-2">
              <div class="text-sm font-medium text-primary">非首轮：上一位专家判断指令</div>
              <p class="text-xs text-muted">
                对应主持人在“上一位专家发言后”追加的判断指令。可用变量：`{last_speaker_dha_id}`。
              </p>
              <textarea
                v-model="form.host_after_last_speaker_template"
                rows="3"
                class="w-full px-3 py-2 bg-input-bg border border-input-border rounded-lg text-primary placeholder-muted focus:outline-none focus:ring-2 focus:ring-input-focus-ring font-mono text-sm"
                placeholder="上一位专家判断指令"
              />
            </div>

            <div class="rounded-xl border border-border bg-card p-4 space-y-2">
              <div class="text-sm font-medium text-primary">首轮：指定第一个发言人指令</div>
              <p class="text-xs text-muted">
                对应主持人在“没有上一位专家时”追加的指令。
              </p>
              <textarea
                v-model="form.host_first_speaker_instruction"
                rows="3"
                class="w-full px-3 py-2 bg-input-bg border border-input-border rounded-lg text-primary placeholder-muted focus:outline-none focus:ring-2 focus:ring-input-focus-ring font-mono text-sm"
                placeholder="首轮指令"
              />
            </div>

            <div class="rounded-xl border border-border bg-card p-4 space-y-2">
              <div class="text-sm font-medium text-primary">next_prompt 规则（自包含要求等）</div>
              <p class="text-xs text-muted">
                对应 `group_chat.py` 中要求主持人输出 next_prompt 的规则段落。
              </p>
              <textarea
                v-model="form.host_next_prompt_rules"
                rows="10"
                class="w-full px-3 py-2 bg-input-bg border border-input-border rounded-lg text-primary placeholder-muted focus:outline-none focus:ring-2 focus:ring-input-focus-ring font-mono text-sm"
                placeholder="next_prompt 规则"
              />
            </div>

            <div class="rounded-xl border border-border bg-card p-4 space-y-2">
              <div class="text-sm font-medium text-primary">仅 1 位专家：循环推进规则</div>
              <p class="text-xs text-muted">
                对应“当前仅有一位专家”时主持人的额外指导。
              </p>
              <textarea
                v-model="form.host_single_dha_loop_rules"
                rows="4"
                class="w-full px-3 py-2 bg-input-bg border border-input-border rounded-lg text-primary placeholder-muted focus:outline-none focus:ring-2 focus:ring-input-focus-ring font-mono text-sm"
                placeholder="单专家循环规则"
              />
            </div>

            <div class="rounded-xl border border-border bg-card p-4 space-y-2">
              <div class="text-sm font-medium text-primary">0 成员：主持人 system 提示词模板</div>
              <p class="text-xs text-muted">
                对应 0 成员时主持人回复并推荐专家的 system 提示词。可用变量：`{skill_content}`。
              </p>
              <textarea
                v-model="form.host_zero_member_system_template"
                rows="6"
                class="w-full px-3 py-2 bg-input-bg border border-input-border rounded-lg text-primary placeholder-muted focus:outline-none focus:ring-2 focus:ring-input-focus-ring font-mono text-sm"
                placeholder="0 成员 system 模板"
              />
            </div>

            <div class="rounded-xl border border-border bg-card p-4 space-y-2">
              <div class="text-sm font-medium text-primary">0 成员：主持人 user 提示词模板</div>
              <p class="text-xs text-muted">
                对应 0 成员时主持人回复并推荐专家的 user 提示词。可用变量：`{discussion_goal}`、`{recent_messages}`、`{dha_text}`。
              </p>
              <textarea
                v-model="form.host_zero_member_user_template"
                rows="10"
                class="w-full px-3 py-2 bg-input-bg border border-input-border rounded-lg text-primary placeholder-muted focus:outline-none focus:ring-2 focus:ring-input-focus-ring font-mono text-sm"
                placeholder="0 成员 user 模板"
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

const form = ref({
  host_context_template: '',
  host_next_prompt_rules: '',
  host_after_last_speaker_template: '',
  host_first_speaker_instruction: '',
  host_single_dha_loop_rules: '',
  host_zero_member_system_template: '',
  host_zero_member_user_template: '',
})

async function load() {
  loading.value = true
  try {
    const r = await fetch('/api/settings/host-prompts')
    const j = await r.json().catch(() => ({}))
    if (j?.status === 'ok' && j?.data) {
      const next = {
        host_context_template: String(j.data.host_context_template || ''),
        host_next_prompt_rules: String(j.data.host_next_prompt_rules || ''),
        host_after_last_speaker_template: String(j.data.host_after_last_speaker_template || ''),
        host_first_speaker_instruction: String(j.data.host_first_speaker_instruction || ''),
        host_single_dha_loop_rules: String(j.data.host_single_dha_loop_rules || ''),
        host_zero_member_system_template: String(j.data.host_zero_member_system_template || ''),
        host_zero_member_user_template: String(j.data.host_zero_member_user_template || ''),
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
        host_context_template: form.value.host_context_template,
        host_next_prompt_rules: form.value.host_next_prompt_rules,
        host_after_last_speaker_template: form.value.host_after_last_speaker_template,
        host_first_speaker_instruction: form.value.host_first_speaker_instruction,
        host_single_dha_loop_rules: form.value.host_single_dha_loop_rules,
        host_zero_member_system_template: form.value.host_zero_member_system_template,
        host_zero_member_user_template: form.value.host_zero_member_user_template,
      }),
    })
    const j = await r.json().catch(() => ({}))
    if (j?.status === 'ok') {
      await load()
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
  if (!window.confirm('确定恢复为默认主持人提示词？这将覆盖你当前的修改。')) return
  saving.value = true
  saved.value = false
  try {
    const r = await fetch('/api/settings/host-prompts/reset', { method: 'POST' })
    const j = await r.json().catch(() => ({}))
    if (j?.status === 'ok' && j?.data) {
      form.value = {
        host_context_template: String(j.data.host_context_template || ''),
        host_next_prompt_rules: String(j.data.host_next_prompt_rules || ''),
        host_after_last_speaker_template: String(j.data.host_after_last_speaker_template || ''),
        host_first_speaker_instruction: String(j.data.host_first_speaker_instruction || ''),
        host_single_dha_loop_rules: String(j.data.host_single_dha_loop_rules || ''),
        host_zero_member_system_template: String(j.data.host_zero_member_system_template || ''),
        host_zero_member_user_template: String(j.data.host_zero_member_user_template || ''),
      }
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
