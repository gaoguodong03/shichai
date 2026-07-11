<template>
  <aside class="w-64 flex-shrink-0 border-r border-border bg-sidebar overflow-y-auto">
    <div class="px-3 py-2 border-b border-border/40 sticky top-0 bg-sidebar z-10">
      <div class="text-xs text-muted truncate">当前目录：{{ currentSidebarDir }}</div>
      <div class="mt-2 flex items-center gap-2">
        <button
          type="button"
          class="px-2 py-1 text-xs rounded border border-input-border bg-card text-primary hover:bg-list-hover disabled:opacity-50"
          :disabled="activeTab === 'main'"
          @click="$emit('go-up')"
        >
          上一级
        </button>
      </div>
    </div>
    <div class="p-2 space-y-1">
      <div v-if="activeTab !== 'main' && partsLoading" class="px-2 py-2 text-sm text-muted">加载中...</div>
      <div v-else-if="!sidebarEntries.length" class="px-2 py-2 text-sm text-muted">暂无文件</div>
      <button
        v-else
        v-for="entry in sidebarEntries"
        :key="entry.key"
        type="button"
        class="w-full px-3 py-2.5 text-left text-base transition-colors border-b border-border/40"
        :class="entry.active
          ? 'bg-accent-subtle text-accent-subtle-text'
          : 'hover:bg-list-hover text-primary'"
        @click="$emit('entry-click', entry)"
      >
        <div class="skill-sidebar-entry-title">
          <span
            class="skill-sidebar-entry-icon"
            :style="resourceIconStyle(entry.isDir ? skillFolderIconUrl : skillFileIconUrl)"
            aria-hidden="true"
          />
          <span class="truncate">{{ entry.name }}</span>
        </div>
      </button>
    </div>
  </aside>
</template>

<script setup lang="ts">
import skillFileIconUrl from '@/assets/icons/workspace/file.svg'
import skillFolderIconUrl from '@/assets/icons/workspace/folder.svg'
import { resourceIconStyle } from '@/features/resources/resourceIconStyle'
import type { PartType, SkillPartSidebarEntry } from '@/features/resources/skillDetailTypes'

defineProps<{
  currentSidebarDir: string
  activeTab: 'main' | PartType
  partsLoading: boolean
  sidebarEntries: SkillPartSidebarEntry[]
}>()

defineEmits<{
  (event: 'go-up'): void
  (event: 'entry-click', entry: SkillPartSidebarEntry): void
}>()
</script>
