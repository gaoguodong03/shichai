<template>
  <div class="rounded-xl border border-border bg-card shadow-sm overflow-hidden">
    <div class="px-4 pt-3 pb-2 flex items-center justify-between gap-2">
      <label class="block text-xs font-medium text-muted">正文（Markdown）</label>
      <span class="text-xs text-muted">{{ editMode ? '编辑中' : '预览' }}</span>
    </div>
    <div
      v-if="!editMode"
      class="skill-markdown-preview themed-scrollbar px-4 py-3 text-sm text-primary max-h-[24rem] overflow-auto"
      v-html="previewHtml"
    />
    <textarea
      v-else
      :value="body"
      rows="18"
      class="w-full px-4 py-3 text-sm font-mono border-0 bg-transparent themed-scrollbar focus:ring-0 resize-y min-h-[14rem]"
      placeholder="SKILL.md 正文内容"
      @input="$emit('update:body', ($event.target as HTMLTextAreaElement).value)"
    />
  </div>
</template>

<script setup lang="ts">
defineProps<{
  body: string
  editMode: boolean
  previewHtml: string
}>()

defineEmits<{
  (event: 'update:body', value: string): void
}>()
</script>
