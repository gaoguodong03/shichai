<template>
  <div class="rounded-xl border border-border bg-card px-4 py-3 shadow-sm">
    <label class="block text-xs font-medium text-muted mb-1">正文（Markdown）</label>
    <textarea
      :value="body"
      rows="12"
      placeholder="SKILL.md 正文内容"
      :disabled="!editMode"
      class="w-full px-3 py-2 text-sm border border-input-border rounded-lg bg-input-bg text-primary resize-y min-h-[14rem] themed-scrollbar focus:outline-none focus:ring-2 focus:ring-input-focus-ring"
      @input="$emit('update:body', ($event.target as HTMLTextAreaElement).value)"
    />
  </div>
</template>

<script setup lang="ts">
defineProps<{
  body: string
  editMode: boolean
}>()

defineEmits<{
  (event: 'update:body', value: string): void
}>()
</script>
