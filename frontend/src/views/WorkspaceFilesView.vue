<template>
  <div class="flex flex-col h-full bg-page">
    <header class="px-4 py-3 border-b border-border bg-card flex items-center justify-between gap-3">
      <div class="min-w-0">
        <h1 class="text-base font-semibold text-primary truncate">文件</h1>
        <p class="text-xs text-muted truncate">会话：{{ sessionTitle || sessionId || '未选择' }}</p>
      </div>
      <div class="flex items-center gap-2">
        <button
          type="button"
          class="inline-flex items-center justify-center px-3 py-1.5 text-sm font-medium rounded-lg border border-input-border bg-card text-primary hover:bg-list-hover disabled:opacity-50"
          @click="refreshAll"
          :disabled="loading || !sessionId"
        >
          刷新
        </button>
        <button
          type="button"
          class="inline-flex items-center justify-center px-3 py-1.5 text-sm font-medium rounded-lg border border-input-border bg-card text-primary hover:bg-list-hover disabled:opacity-50"
          @click="createFile"
          :disabled="loading || !sessionId"
        >
          新建文件
        </button>
        <button
          type="button"
          class="inline-flex items-center justify-center px-3 py-1.5 text-sm font-medium rounded-lg border border-input-border bg-card text-primary hover:bg-list-hover disabled:opacity-50"
          @click="createFolder"
          :disabled="loading || !sessionId"
        >
          创建文件夹
        </button>
        <button
          type="button"
          class="inline-flex items-center justify-center px-3 py-1.5 text-sm font-medium rounded-lg border border-input-border bg-card text-primary hover:bg-list-hover disabled:opacity-50"
          @click="uploadInputRef?.click()"
          :disabled="loading || !sessionId"
        >
          上传文件
        </button>
        <input ref="uploadInputRef" type="file" class="hidden" @change="onUpload" />
      </div>
    </header>

    <div v-if="!sessionId" class="flex-1 flex items-center justify-center text-sm text-muted">
      请选择左侧会话
    </div>

    <div v-else class="flex-1 min-h-0 flex">
      <aside class="w-72 border-r border-border bg-sidebar overflow-y-auto">
        <div class="px-3 py-2 border-b border-border/40 sticky top-0 bg-sidebar z-10">
          <div class="text-xs text-muted truncate">当前目录：{{ currentDir || '/' }}</div>
          <div class="mt-2 flex items-center gap-2">
            <button
              type="button"
              class="px-2 py-1 text-xs rounded border border-input-border text-primary hover:bg-list-hover disabled:opacity-50"
              :disabled="!currentDir"
              @click="goUpDir"
            >
              上一级
            </button>
          </div>
        </div>
        <div v-if="loading" class="px-3 py-4 text-sm text-muted">加载中...</div>
        <div v-else-if="error" class="px-3 py-4 text-sm text-danger">{{ error }}</div>
        <div v-else-if="!entries.length" class="px-3 py-4 text-sm text-muted">该目录为空</div>
        <button
          v-else
          v-for="e in entries"
          :key="e.path"
          type="button"
          class="w-full px-3 py-2.5 text-left text-sm transition-colors border-b border-border/40"
          :class="selectedPath === e.path ? 'bg-accent-subtle text-accent-subtle-text' : 'hover:bg-list-hover text-primary'"
          @click="onEntryClick(e)"
        >
          <div class="truncate font-medium">
            <span class="mr-1 text-muted">{{ e.is_dir ? '[DIR]' : '[FILE]' }}</span>
            {{ e.name }}
          </div>
          <div class="truncate text-xs text-muted mt-0.5">{{ e.path }}</div>
        </button>
      </aside>

      <main class="flex-1 min-w-0 min-h-0">
        <div v-if="!selectedPath" class="h-full flex items-center justify-center text-sm text-muted">
          选择文件后可预览与编辑
        </div>
        <div v-else class="h-full flex flex-col min-h-0">
          <div class="px-3 py-2 border-b border-border bg-card flex items-center justify-end gap-2">
            <button
              type="button"
              class="px-3 py-1.5 text-sm rounded-lg border border-danger text-danger hover:bg-danger-subtle"
              @click="deleteSelectedFile"
            >
              删除文件
            </button>
          </div>
          <div class="flex-1 min-h-0">
            <FileDetailView
              :workspace-id="sessionId"
              :path="selectedPath"
              @renamed="onRenamed"
            />
          </div>
        </div>
      </main>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import FileDetailView from './FileDetailView.vue'

type Entry = { name: string; path: string; is_dir?: boolean }

const props = defineProps<{
  sessionId: string | null
  sessionTitle?: string
}>()

const loading = ref(false)
const error = ref('')
const entries = ref<Entry[]>([])
const selectedPath = ref('')
const currentDir = ref('')
const uploadInputRef = ref<HTMLInputElement | null>(null)

async function listDir(path: string): Promise<Entry[]> {
  const id = props.sessionId
  if (!id) return []
  const query = path ? `?path=${encodeURIComponent(path)}` : ''
  const r = await fetch(`/api/workspaces/${encodeURIComponent(id)}/files${query}`)
  const j = await r.json()
  if (j?.status !== 'ok') throw new Error(j?.detail || '加载失败')
  return (j?.data?.entries || []) as Entry[]
}

async function loadDir(path = '') {
  const id = props.sessionId
  entries.value = []
  selectedPath.value = ''
  if (!id) return
  loading.value = true
  error.value = ''
  try {
    const list = await listDir(path)
    list.sort((a, b) => {
      if (!!a.is_dir !== !!b.is_dir) return a.is_dir ? -1 : 1
      return a.name.localeCompare(b.name)
    })
    entries.value = list
    currentDir.value = path
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载失败'
  } finally {
    loading.value = false
  }
}

async function refreshAll() {
  await loadDir(currentDir.value)
}

function goUpDir() {
  const p = currentDir.value
  if (!p) return
  const parent = p.replace(/\/?[^/]+\/?$/, '').replace(/\/$/, '')
  loadDir(parent)
}

function onEntryClick(e: Entry) {
  if (e.is_dir) {
    loadDir(e.path)
    return
  }
  selectedPath.value = e.path
}

async function createFile() {
  const id = props.sessionId
  if (!id) return
  const filename = window.prompt('新建文件名（如 note.md）', 'note.md')?.trim()
  if (!filename) return
  const query = currentDir.value ? `?path=${encodeURIComponent(currentDir.value)}` : ''
  const r = await fetch(`/api/workspaces/${encodeURIComponent(id)}/files${query}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ filename, content: '' }),
  })
  const j = await r.json()
  if (j?.status !== 'ok') {
    alert(j?.detail || '新建文件失败')
    return
  }
  await loadDir(currentDir.value)
  if (j?.data?.path) selectedPath.value = j.data.path
}

async function createFolder() {
  const id = props.sessionId
  if (!id) return
  const dirname = window.prompt('新建文件夹名称', '新文件夹')?.trim()
  if (!dirname) return
  const query = currentDir.value ? `?path=${encodeURIComponent(currentDir.value)}` : ''
  const r = await fetch(`/api/workspaces/${encodeURIComponent(id)}/files/mkdir${query}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ dirname }),
  })
  const j = await r.json()
  if (j?.status !== 'ok') {
    alert(j?.detail || '创建文件夹失败')
    return
  }
  await loadDir(currentDir.value)
}

async function onUpload(ev: Event) {
  const id = props.sessionId
  const input = ev.target as HTMLInputElement
  if (!id || !input.files?.length) return
  const fd = new FormData()
  fd.append('file', input.files[0])
  try {
    const query = currentDir.value ? `?path=${encodeURIComponent(currentDir.value)}` : ''
    const r = await fetch(`/api/workspaces/${encodeURIComponent(id)}/files/upload${query}`, {
      method: 'POST',
      body: fd,
    })
    const j = await r.json()
    if (j?.status !== 'ok') {
      alert(j?.detail || '上传失败')
      return
    }
    await loadDir(currentDir.value)
    if (j?.data?.path) selectedPath.value = j.data.path
  } finally {
    input.value = ''
  }
}

async function deleteSelectedFile() {
  const id = props.sessionId
  const path = selectedPath.value
  if (!id || !path) return
  if (!window.confirm(`确定删除文件「${path}」？`)) return
  const r = await fetch(`/api/workspaces/${encodeURIComponent(id)}/files/content?path=${encodeURIComponent(path)}`, {
    method: 'DELETE',
  })
  const j = await r.json()
  if (j?.status !== 'ok') {
    alert(j?.detail || '删除失败')
    return
  }
  await loadDir(currentDir.value)
}

function onRenamed(newPath: string) {
  selectedPath.value = newPath
  loadDir(currentDir.value)
}

watch(() => props.sessionId, () => {
  currentDir.value = ''
  loadDir('')
}, { immediate: true })
</script>
