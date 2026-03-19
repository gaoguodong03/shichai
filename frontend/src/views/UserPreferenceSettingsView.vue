<template>
  <div class="flex flex-col h-full bg-page overflow-y-auto">
    <header class="bg-card px-4 py-3 flex-shrink-0">
      <h1 class="text-lg font-semibold text-primary">用户喜好</h1>
    </header>
    <div class="flex-1 overflow-y-auto p-4 space-y-6">
      <section class="space-y-4">
        <h2 class="text-base font-medium text-primary py-1 bg-list-hover rounded-t px-2 -mx-2 mt-0">
          工作区
        </h2>
        <button
          type="button"
          :class="[
            'w-full rounded-xl border px-4 py-3 text-left transition-colors',
            workspaceOpen ? 'border-accent bg-accent-subtle text-accent-subtle-text' : 'bg-card border-border text-primary hover:bg-list-hover'
          ]"
          @click="workspaceOpen = !workspaceOpen"
        >
          默认展开：{{ workspaceOpen ? '开启' : '关闭' }}
        </button>
      </section>

      <section class="space-y-4">
        <h2 class="text-base font-medium text-primary py-1 bg-list-hover rounded-t px-2 -mx-2 mt-0">
          TOC
        </h2>
        <button
          type="button"
          :class="[
            'w-full rounded-xl border px-4 py-3 text-left transition-colors',
            tocWorkspaceOpen ? 'border-accent bg-accent-subtle text-accent-subtle-text' : 'bg-card border-border text-primary hover:bg-list-hover'
          ]"
          @click="tocWorkspaceOpen = !tocWorkspaceOpen"
        >
          工作区悬浮 TOC 默认：{{ tocWorkspaceOpen ? '展开' : '关闭' }}
        </button>

        <p class="text-xs text-muted">
          影响“归档侧边目录”（工作区右侧悬浮目录）在打开会话时的默认状态。
        </p>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, onMounted } from 'vue'

const USER_PREF_UPDATED_EVENT_NAME = 'dha-user-pref-updated'

const WORKSPACE_OPEN_STORAGE_KEY = 'dha_user_pref_workspace_open_v1'
const TOC_WORKSPACE_OPEN_STORAGE_KEY = 'dha_user_pref_toc_workspace_open_v1'

function loadBoolFromLocalStorage(storageKey: string): boolean {
  try {
    const raw = localStorage.getItem(storageKey)
    if (raw === 'true') return true
    if (raw === 'false') return false
  } catch {
    // ignore
  }
  return false
}

function saveBoolToLocalStorage(storageKey: string, next: boolean) {
  try {
    localStorage.setItem(storageKey, next ? 'true' : 'false')
  } catch {
    // ignore
  }
}

const workspaceOpen = ref(false)
const tocWorkspaceOpen = ref(false)

onMounted(() => {
  workspaceOpen.value = loadBoolFromLocalStorage(WORKSPACE_OPEN_STORAGE_KEY)
  tocWorkspaceOpen.value = loadBoolFromLocalStorage(TOC_WORKSPACE_OPEN_STORAGE_KEY)
})

watch(workspaceOpen, (v) => {
  saveBoolToLocalStorage(WORKSPACE_OPEN_STORAGE_KEY, v)
  window.dispatchEvent(
    new CustomEvent(USER_PREF_UPDATED_EVENT_NAME, {
      detail: { key: WORKSPACE_OPEN_STORAGE_KEY, value: v },
    })
  )
})

watch(tocWorkspaceOpen, (v) => {
  saveBoolToLocalStorage(TOC_WORKSPACE_OPEN_STORAGE_KEY, v)
  window.dispatchEvent(
    new CustomEvent(USER_PREF_UPDATED_EVENT_NAME, {
      detail: { key: TOC_WORKSPACE_OPEN_STORAGE_KEY, value: v },
    })
  )
})
</script>

