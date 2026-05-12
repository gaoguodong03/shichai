<template>
  <div class="flex flex-col h-full bg-page overflow-y-auto">
    <div class="flex-1 overflow-y-auto p-4 themed-scrollbar">
      <div class="max-w-5xl w-full mx-auto space-y-6">
      <section class="space-y-4">
        <h2 class="text-base font-medium text-primary py-1 bg-list-hover rounded-t px-2 -mx-2 mt-0">主题</h2>
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
            @click="onSelectPreset(p.value)"
          >
            <span class="font-medium block">{{ p.label }}</span>
            <span class="text-xs text-muted mt-0.5 block">{{ p.desc }}</span>
          </button>
        </div>
      </section>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { inject } from 'vue'
import { useTheme } from '@/composables/useTheme'
import type { ThemePreset } from '@/composables/useTheme'

const themeApi = inject<ReturnType<typeof useTheme>>('theme') ?? useTheme()
const { preset, setPreset, setPreference } = themeApi

const presetOptions: { value: ThemePreset; label: string; desc: string }[] = [
  { value: 'default', label: '白色', desc: '浅色默认' },
  { value: 'warm', label: '浅暖', desc: '米黄暖调' },
  { value: 'cool', label: '浅蓝', desc: '冷色浅调' },
  { value: 'contrast', label: '纯黑', desc: '纯黑底 + 白字' },
  { value: 'forest', label: '深绿', desc: '深色底 + 白字' },
  { value: 'ocean', label: '深青', desc: '深色底 + 白字' },
]

function onSelectPreset(next: ThemePreset) {
  const darkPresets: ThemePreset[] = ['forest', 'ocean', 'contrast']
  setPreference(darkPresets.includes(next) ? 'dark' : 'light')
  setPreset(next)
}
</script>
