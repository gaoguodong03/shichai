<template>
  <div class="space-y-4 rounded-xl border border-border-light bg-bg-subtle/40 p-4">
    <div>
      <label class="block text-sm font-medium text-primary mb-1">公共调用参数（可选）</label>
      <p class="text-xs text-muted">留空表示使用模型/网关默认值。厂商专属参数请写在下方 extra_body。</p>
    </div>
    <div class="grid grid-cols-1 md:grid-cols-3 gap-3">
      <div>
        <label class="block text-xs text-muted mb-1">温度 temperature</label>
        <input v-model.trim="model.temperature" type="number" step="0.01" min="0" placeholder="如 0.7" class="llm-param-input" />
      </div>
      <div>
        <label class="block text-xs text-muted mb-1">核采样 top_p</label>
        <input v-model.trim="model.top_p" type="number" step="0.01" min="0" max="1" placeholder="如 0.95" class="llm-param-input" />
      </div>
      <div>
        <label class="block text-xs text-muted mb-1">最大输出 max_tokens</label>
        <input v-model.trim="model.max_tokens" type="number" step="1" min="1" placeholder="如 2000" class="llm-param-input" />
      </div>
      <div>
        <label class="block text-xs text-muted mb-1">存在惩罚 presence_penalty</label>
        <input v-model.trim="model.presence_penalty" type="number" step="0.01" min="-2" max="2" placeholder="-2 到 2" class="llm-param-input" />
      </div>
      <div>
        <label class="block text-xs text-muted mb-1">频率惩罚 frequency_penalty</label>
        <input v-model.trim="model.frequency_penalty" type="number" step="0.01" min="-2" max="2" placeholder="-2 到 2" class="llm-param-input" />
      </div>
      <div>
        <label class="block text-xs text-muted mb-1">随机种子 seed</label>
        <input v-model.trim="model.seed" type="number" step="1" placeholder="可选整数" class="llm-param-input" />
      </div>
    </div>
    <div class="pt-2 border-t border-border-light space-y-2">
      <div>
        <label class="block text-sm font-medium text-primary mb-1">模型专属参数 extra_body（JSON）</label>
        <p class="text-xs text-muted mb-2">
          按目标模型官方文档自由填写，例如 Qwen 的
          <code class="text-[11px]">{"enable_thinking": false}</code>
          、DeepSeek 的
          <code class="text-[11px]">{"thinking": {"type": "disabled"}}</code>
          。系统不会按厂商自动补参。
        </p>
        <textarea
          v-model="model.extra_body"
          rows="8"
          spellcheck="false"
          placeholder='{"enable_thinking": false}'
          class="llm-param-input font-mono text-xs leading-5"
        />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { ModelParams } from './llmSettingsTypes'

const model = defineModel<ModelParams>('params', { required: true })
</script>

<style scoped>
.llm-param-input {
  width: 100%;
  border-radius: 0.5rem;
  border: 1px solid var(--color-input-border);
  background: var(--color-input-bg);
  padding: 0.5rem 0.75rem;
  color: var(--color-text);
}

.llm-param-input::placeholder {
  color: var(--color-text-muted);
}

.llm-param-input:focus {
  outline: none;
  box-shadow: 0 0 0 2px var(--color-input-focus-ring);
}
</style>
