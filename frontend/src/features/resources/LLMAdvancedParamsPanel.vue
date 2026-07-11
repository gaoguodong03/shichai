<template>
  <div class="space-y-4 rounded-xl border border-border-light bg-bg-subtle/40 p-4">
    <div>
      <label class="block text-sm font-medium text-primary mb-1">调用参数（可选）</label>
      <p class="text-xs text-muted">仅开放官网明确支持的字段；留空表示使用厂商默认值。</p>
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
    <div v-if="isQwenLike" class="grid grid-cols-1 md:grid-cols-2 gap-3 pt-2 border-t border-border-light">
      <div>
        <label class="block text-xs text-muted mb-1">Qwen/百炼思考模式 enable_thinking</label>
        <select v-model="model.enable_thinking" class="llm-param-input">
          <option value="">默认</option>
          <option value="true">开启</option>
          <option value="false">关闭</option>
        </select>
      </div>
      <div>
        <label class="block text-xs text-muted mb-1">思考预算 thinking_budget</label>
        <input v-model.trim="model.thinking_budget" type="number" step="1" min="0" placeholder="如 50" class="llm-param-input" />
      </div>
    </div>
    <div v-if="isDeepSeekLike || isGlmLike" class="grid grid-cols-1 md:grid-cols-2 gap-3 pt-2 border-t border-border-light">
      <div>
        <label class="block text-xs text-muted mb-1">思考模式 thinking</label>
        <select v-model="model.thinking" class="llm-param-input">
          <option value="">默认</option>
          <option value="true">开启</option>
          <option value="false">关闭</option>
        </select>
      </div>
      <div v-if="isGlmLike">
        <label class="block text-xs text-muted mb-1">采样 do_sample</label>
        <select v-model="model.do_sample" class="llm-param-input">
          <option value="">默认</option>
          <option value="true">开启</option>
          <option value="false">关闭</option>
        </select>
      </div>
    </div>
    <div v-if="isGeminiLike || isClaudeLike" class="grid grid-cols-1 md:grid-cols-2 gap-3 pt-2 border-t border-border-light">
      <div>
        <label class="block text-xs text-muted mb-1">Top K</label>
        <input v-model.trim="model.top_k" type="number" step="1" min="0" placeholder="如 20" class="llm-param-input" />
      </div>
      <div v-if="isGeminiLike">
        <label class="block text-xs text-muted mb-1">Gemini 思考级别 thinkingLevel</label>
        <select v-model="model.gemini_thinking_level" class="llm-param-input">
          <option value="">默认</option>
          <option value="low">low</option>
        </select>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { ModelParams } from './llmSettingsTypes'

defineProps<{
  isQwenLike: boolean
  isDeepSeekLike: boolean
  isGlmLike: boolean
  isGeminiLike: boolean
  isClaudeLike: boolean
}>()

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
