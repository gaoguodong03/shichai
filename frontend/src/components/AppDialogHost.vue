<template>
  <Teleport to="body">
    <div
      v-if="active"
      class="app-dialog-overlay"
      role="presentation"
      @click.self="cancelDialog"
    >
      <section
        class="app-dialog"
        role="dialog"
        aria-modal="true"
        :aria-labelledby="titleId"
        :aria-describedby="messageId"
        @keydown.esc.prevent="cancelDialog"
      >
        <div class="app-dialog-header">
          <span class="app-dialog-mark" :class="`app-dialog-mark-${active.variant || 'info'}`" aria-hidden="true" />
          <h2 :id="titleId" class="app-dialog-title">{{ active.title || defaultTitle }}</h2>
        </div>
        <p :id="messageId" class="app-dialog-message">{{ active.message }}</p>
        <label v-if="active.mode === 'prompt'" class="app-dialog-field">
          <span v-if="active.label" class="app-dialog-label">{{ active.label }}</span>
          <input
            ref="inputRef"
            v-model="promptValue"
            class="app-dialog-input"
            type="text"
            :placeholder="active.placeholder || ''"
            @keydown.enter.prevent="confirmDialog"
          />
        </label>
        <div class="app-dialog-actions">
          <button
            v-if="active.mode !== 'alert'"
            ref="cancelRef"
            type="button"
            class="app-dialog-button app-dialog-button-secondary"
            @click="cancelDialog"
          >
            {{ active.cancelText || '取消' }}
          </button>
          <button
            ref="confirmRef"
            type="button"
            class="app-dialog-button app-dialog-button-primary"
            :class="active.variant === 'danger' && 'app-dialog-button-danger'"
            :disabled="active.mode === 'prompt' && active.required && !promptValue.trim()"
            @click="confirmDialog"
          >
            {{ active.confirmText || '确认' }}
          </button>
        </div>
      </section>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { settleAppDialog, useAppDialogState } from '@/composables/useAppDialog'

const dialogState = useAppDialogState()
const active = computed(() => dialogState.active)
const promptValue = ref('')
const inputRef = ref<HTMLInputElement | null>(null)
const confirmRef = ref<HTMLButtonElement | null>(null)
const cancelRef = ref<HTMLButtonElement | null>(null)
const titleId = computed(() => active.value ? `app-dialog-title-${active.value.id}` : 'app-dialog-title')
const messageId = computed(() => active.value ? `app-dialog-message-${active.value.id}` : 'app-dialog-message')
const defaultTitle = computed(() => active.value?.mode === 'alert' ? '提示' : '请确认')

watch(active, async (dialog) => {
  if (!dialog) return
  promptValue.value = dialog.defaultValue || ''
  await nextTick()
  if (dialog.mode === 'prompt') {
    inputRef.value?.focus()
    inputRef.value?.select()
  } else if (dialog.mode === 'alert') {
    confirmRef.value?.focus()
  } else {
    cancelRef.value?.focus()
  }
})

function cancelDialog() {
  if (!active.value) return
  if (active.value.mode === 'alert') {
    settleAppDialog(true)
    return
  }
  settleAppDialog(active.value.mode === 'confirm' ? false : null)
}

function confirmDialog() {
  const dialog = active.value
  if (!dialog) return
  if (dialog.mode === 'prompt') {
    const value = promptValue.value
    if (dialog.required && !value.trim()) return
    settleAppDialog(value)
    return
  }
  settleAppDialog(true)
}
</script>
