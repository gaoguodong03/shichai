<template>
  <div class="rounded-xl border border-border bg-card shadow-sm overflow-hidden">
    <div class="px-4 pt-3 pb-2 flex items-center justify-between gap-2">
      <label class="block text-xs font-medium text-muted">正文（Markdown）</label>
      <span class="text-xs text-muted">{{ editMode ? '编辑中' : '预览' }}</span>
    </div>
    <div
      v-if="!editMode"
      class="skill-markdown-preview themed-scrollbar px-4 py-3 text-sm text-primary max-h-[24rem] overflow-auto break-words"
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

<style scoped>
.skill-markdown-preview {
  line-height: 1.7;
  overflow-wrap: anywhere;
}

.skill-markdown-preview :deep(> :first-child) {
  margin-top: 0;
}

.skill-markdown-preview :deep(> :last-child) {
  margin-bottom: 0;
}

.skill-markdown-preview :deep(h1),
.skill-markdown-preview :deep(h2) {
  border-bottom: 1px solid var(--color-border-light);
  padding-bottom: 0.4rem;
}

.skill-markdown-preview :deep(h1) {
  margin: 0 0 1rem;
  font-size: 1.5rem;
  font-weight: 700;
  line-height: 1.35;
}

.skill-markdown-preview :deep(h2) {
  margin: 1.5rem 0 0.75rem;
  font-size: 1.25rem;
  font-weight: 700;
  line-height: 1.4;
}

.skill-markdown-preview :deep(h3) {
  margin: 1.25rem 0 0.625rem;
  font-size: 1.125rem;
  font-weight: 650;
  line-height: 1.45;
}

.skill-markdown-preview :deep(h4),
.skill-markdown-preview :deep(h5),
.skill-markdown-preview :deep(h6) {
  margin: 1rem 0 0.5rem;
  font-weight: 650;
  line-height: 1.5;
}

.skill-markdown-preview :deep(p) {
  margin: 0 0 0.75rem;
}

.skill-markdown-preview :deep(ul),
.skill-markdown-preview :deep(ol) {
  margin: 0 0 0.75rem 1.5rem;
  padding-left: 0.5rem;
}

.skill-markdown-preview :deep(ul) {
  list-style: disc;
}

.skill-markdown-preview :deep(ol) {
  list-style: decimal;
}

.skill-markdown-preview :deep(li) {
  margin: 0.25rem 0;
  padding-left: 0.125rem;
}

.skill-markdown-preview :deep(li > ul),
.skill-markdown-preview :deep(li > ol) {
  margin-top: 0.25rem;
  margin-bottom: 0.25rem;
}

.skill-markdown-preview :deep(blockquote) {
  margin: 0 0 0.75rem;
  border-left: 0.25rem solid var(--color-border);
  border-radius: 0 0.375rem 0.375rem 0;
  background: var(--color-list-hover);
  padding: 0.625rem 0.875rem;
  color: var(--color-text-muted);
}

.skill-markdown-preview :deep(blockquote > :last-child) {
  margin-bottom: 0;
}

.skill-markdown-preview :deep(hr) {
  margin: 1.25rem 0;
  border: 0;
  border-top: 1px solid var(--color-border-light);
}

.skill-markdown-preview :deep(pre) {
  margin: 0 0 0.875rem;
  overflow: auto;
  border: 1px solid var(--color-border-light);
  border-radius: 0.5rem;
  background: var(--color-list-hover);
  padding: 0.75rem 0.875rem;
  line-height: 1.55;
}

.skill-markdown-preview :deep(code) {
  border: 1px solid var(--color-border-light);
  border-radius: 0.25rem;
  background: var(--color-list-hover);
  padding: 0.1rem 0.3rem;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
  font-size: 0.875em;
}

.skill-markdown-preview :deep(pre code) {
  border: 0;
  border-radius: 0;
  background: transparent;
  padding: 0;
  font-size: inherit;
}

.skill-markdown-preview :deep(table) {
  display: block;
  width: max-content;
  max-width: 100%;
  margin: 0 0 0.875rem;
  overflow-x: auto;
  border-collapse: collapse;
}

.skill-markdown-preview :deep(th),
.skill-markdown-preview :deep(td) {
  border: 1px solid var(--color-border-light);
  padding: 0.5rem 0.75rem;
  text-align: left;
  vertical-align: top;
}

.skill-markdown-preview :deep(th) {
  background: var(--color-list-hover);
  font-weight: 650;
}

.skill-markdown-preview :deep(a) {
  color: var(--color-accent);
  text-decoration: underline;
  text-underline-offset: 0.15em;
}

.skill-markdown-preview :deep(img) {
  max-width: 100%;
  height: auto;
  margin: 0 0 0.875rem;
  border-radius: 0.5rem;
}
</style>
