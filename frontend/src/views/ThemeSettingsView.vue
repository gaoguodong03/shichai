<template>
  <div class="flex flex-col h-full bg-page overflow-y-auto">
    <header class="bg-card px-4 py-3 flex-shrink-0">
      <h1 class="text-lg font-semibold text-primary">配色</h1>
    </header>
    <div class="flex-1 overflow-y-auto p-4 space-y-6">
      <section class="space-y-4">
        <h2 class="text-base font-medium text-primary py-1 bg-list-hover rounded-t px-2 -mx-2 mt-0">主题</h2>
        <div class="flex flex-wrap gap-3">
          <label class="flex items-center gap-2 cursor-pointer">
            <input
              v-model="preference"
              type="radio"
              value="light"
              class="rounded-full border-border accent-accent focus:ring-2 focus:ring-input-focus-ring focus:ring-offset-0"
            />
            <span class="text-primary">浅色</span>
          </label>
          <label class="flex items-center gap-2 cursor-pointer">
            <input
              v-model="preference"
              type="radio"
              value="dark"
              class="rounded-full border-border accent-accent focus:ring-2 focus:ring-input-focus-ring focus:ring-offset-0"
            />
            <span class="text-primary">深色</span>
          </label>
          <label class="flex items-center gap-2 cursor-pointer">
            <input
              v-model="preference"
              type="radio"
              value="system"
              class="rounded-full border-border accent-accent focus:ring-2 focus:ring-input-focus-ring focus:ring-offset-0"
            />
            <span class="text-primary">跟随系统</span>
          </label>
        </div>
        <p class="mt-1 text-xs text-muted">当前为 {{ theme === 'dark' ? '深色' : '浅色' }}。</p>
      </section>

      <section class="space-y-4">
        <h2 class="text-base font-medium text-primary py-1 bg-list-hover rounded-t px-2 -mx-2 mt-0">强调色</h2>
        <div class="flex flex-wrap gap-3">
          <label
            v-for="opt in accentOptions"
            :key="opt.value"
            class="flex items-center gap-2 cursor-pointer"
          >
            <input
              v-model="accent"
              type="radio"
              :value="opt.value"
              class="rounded-full border-border accent-accent focus:ring-2 focus:ring-input-focus-ring focus:ring-offset-0"
            />
            <span class="text-primary">{{ opt.label }}</span>
          </label>
        </div>
        <p class="mt-1 text-xs text-muted">按钮、链接、选中等使用该颜色。</p>
      </section>

      <section class="space-y-4">
        <h2 class="text-base font-medium text-primary py-1 bg-list-hover rounded-t px-2 -mx-2 mt-0">配色方案</h2>
        <p class="text-sm text-muted">选择一套整体配色，影响背景、侧栏、卡片等。</p>
        <div class="grid grid-cols-2 sm:grid-cols-3 gap-3">
          <button
            v-for="p in presetOptions"
            :key="p.value"
            type="button"
            :class="[
              'rounded-xl p-4 text-left border-2 transition-colors',
              preset === p.value
                ? 'border-accent bg-accent-subtle text-accent-subtle-text'
                : 'border-border bg-card text-primary hover:bg-list-hover'
            ]"
            @click="setPreset(p.value)"
          >
            <span class="font-medium block">{{ p.label }}</span>
            <span class="text-xs text-muted mt-0.5 block">{{ p.desc }}</span>
          </button>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { watch, inject } from 'vue'
import { useTheme } from '@/composables/useTheme'
import type { ThemePreset } from '@/composables/useTheme'

const themeApi = inject<ReturnType<typeof useTheme>>('theme') ?? useTheme()
const { preference, theme, accent, preset, setPreference, setAccent, setPreset } = themeApi

const accentOptions = [
  { value: 'blue' as const, label: '蓝' },
  { value: 'purple' as const, label: '紫' },
  { value: 'green' as const, label: '绿' },
]

const presetOptions: { value: ThemePreset; label: string; desc: string }[] = [
  { value: 'default', label: '默认', desc: '系统灰 + 蓝' },
  { value: 'warm', label: '暖光', desc: '米黄暖调' },
  { value: 'cool', label: '冷光', desc: '浅灰冷调' },
  { value: 'forest', label: '森林', desc: '绿意自然' },
  { value: 'ocean', label: '海洋', desc: '青蓝清爽' },
  { value: 'sunset', label: '日落', desc: '橙粉暖色' },
  { value: 'contrast', label: '高对比', desc: '深色高对比' },
]

watch(preference, (val) => setPreference(val), { immediate: false })
watch(accent, (val) => setAccent(val), { immediate: false })
</script>
