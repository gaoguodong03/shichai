<template>
  <div class="flex items-center justify-between gap-2 mb-2 flex-shrink-0">
    <span class="text-xs text-muted truncate">{{ path }}</span>
    <div class="flex gap-2">
      <button
        @click="$emit('toggle-preview')"
        class="inline-flex items-center justify-center px-2 py-1 text-xs font-medium rounded border border-input-border bg-card text-primary hover:bg-list-hover"
      >
        {{ previewMode ? '编辑源文件' : '预览渲染' }}
      </button>
      <button
        @click="$emit('save')"
        :disabled="saving"
        class="inline-flex items-center justify-center px-2 py-1 text-xs font-medium rounded border border-input-border bg-card text-primary hover:bg-list-hover disabled:opacity-50"
      >
        {{ saving ? '保存中...' : '保存' }}
      </button>
      <button
        @click="$emit('delete')"
        class="inline-flex items-center justify-center px-2 py-1 text-xs font-medium rounded border border-input-border bg-card text-primary hover:bg-list-hover"
      >
        删除文件
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  path: string
  previewMode: boolean
  saving: boolean
}>()

defineEmits<{
  (event: 'toggle-preview'): void
  (event: 'save'): void
  (event: 'delete'): void
}>()
</script>
