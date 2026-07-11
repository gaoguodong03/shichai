<template>
  <header class="px-4 py-3 border-b border-border bg-card flex-shrink-0">
    <div class="flex items-center justify-between gap-3">
      <div class="min-w-[12rem]">
        <h1 class="text-base font-semibold text-primary truncate">技能</h1>
        <p class="text-xs text-muted truncate">技能：{{ skill.name || skill.directory_name }}</p>
      </div>
      <div class="flex flex-shrink-0 items-center gap-2">
        <button
          v-if="activeTab !== 'main' && !isDraftSkill"
          type="button"
          class="inline-flex items-center justify-center px-3 py-1.5 text-sm font-medium rounded-lg border border-input-border bg-card text-primary hover:bg-list-hover disabled:opacity-50"
          :disabled="partsLoading"
          @click="$emit('add-part-file')"
        >
          新建文件
        </button>
        <button
          v-if="activeTab !== 'main' && !isDraftSkill"
          type="button"
          class="inline-flex items-center justify-center px-3 py-1.5 text-sm font-medium rounded-lg border border-input-border bg-card text-primary hover:bg-list-hover disabled:opacity-50"
          :disabled="partsLoading"
          @click="$emit('add-part-folder')"
        >
          新建文件夹
        </button>
        <button
          v-if="!isDraftSkill"
          type="button"
          class="inline-flex items-center justify-center px-4 py-2 text-sm font-medium rounded-lg bg-list-hover text-primary border border-border-light hover:bg-nav-hover-bg disabled:opacity-50"
          :disabled="exporting"
          @click="$emit('export-zip')"
        >
          {{ exporting ? '导出中…' : '导出' }}
        </button>
        <button
          type="button"
          class="inline-flex items-center justify-center px-4 py-2 text-sm font-medium rounded-lg bg-accent text-text-inverse hover:bg-accent-hover disabled:opacity-50"
          :disabled="saving || deleting || contentLoading"
          @click="$emit('edit-save')"
        >
          {{ editMode ? (saving ? '保存中...' : '保存') : '编辑' }}
        </button>
        <button
          type="button"
          class="inline-flex items-center justify-center px-4 py-2 text-sm font-medium rounded-lg bg-danger-subtle text-danger hover:opacity-90 disabled:opacity-50"
          :disabled="deleting || saving"
          @click="$emit('delete-skill')"
        >
          {{ deleting ? '删除中...' : '删除' }}
        </button>
      </div>
    </div>
  </header>
</template>

<script setup lang="ts">
import type { PartType } from '@/features/resources/skillDetailTypes'

defineProps<{
  skill: { directory_name: string; name: string }
  activeTab: 'main' | PartType
  isDraftSkill: boolean
  partsLoading: boolean
  exporting: boolean
  editMode: boolean
  saving: boolean
  deleting: boolean
  contentLoading: boolean
}>()

defineEmits<{
  (event: 'add-part-file'): void
  (event: 'add-part-folder'): void
  (event: 'export-zip'): void
  (event: 'edit-save'): void
  (event: 'delete-skill'): void
}>()
</script>
