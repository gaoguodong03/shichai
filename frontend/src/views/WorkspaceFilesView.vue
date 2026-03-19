<template>
  <div class="flex flex-col h-full bg-page">
    <header class="px-4 py-3 border-b border-border bg-card flex items-center justify-between gap-3">
      <div class="min-w-0">
        <h1 class="text-base font-semibold text-primary truncate">文件工作区</h1>
        <p class="text-xs text-muted truncate">会话：{{ sessionTitle || sessionId || '未选择' }}</p>
      </div>
      <div class="flex items-center gap-2">
        <button
          type="button"
          class="px-3 py-1.5 text-sm rounded-lg border border-input-border text-primary hover:bg-list-hover"
          @click="refreshAll"
          :disabled="loading || !sessionId"
        >
          刷新
        </button>
        <button
          type="button"
          class="px-3 py-1.5 text-sm rounded-lg bg-accent text-text-inverse hover:opacity-90"
          @click="createFile"
          :disabled="loading || !sessionId"
        >
          新建文件
        </button>
        <button
          type="button"
          class="px-3 py-1.5 text-sm rounded-lg border border-input-border text-primary hover:bg-list-hover"
          @click="createFolder"
          :disabled="loading || !sessionId"
        >
          创建文件夹
        </button>
        <button
          type="button"
          class="px-3 py-1.5 text-sm rounded-lg bg-accent-subtle text-accent-subtle-text hover:opacity-90"
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
        <div v-if="loading" class="px-3 py-4 text-sm text-muted">加载中...</div>
        <div v-else-if="error" class="px-3 py-4 text-sm text-danger">{{ error }}</div>
        <div v-else-if="!allFiles.length" class="px-3 py-4 text-sm text-muted">该会话暂无文件</div>
        <button
          v-else
          v-for="f in allFiles"
          :key="f.path"
          type="button"
          class="w-full px-3 py-2.5 text-left text-sm transition-colors border-b border-border/40"
          :class="selectedPath === f.path ? 'bg-accent-subtle text-accent-subtle-text' : 'hover:bg-list-hover text-primary'"
          @click="selectedPath = f.path"
        >
          <div class="truncate font-medium">{{ f.name }}</div>
          <div class="truncate text-xs text-muted mt-0.5">{{ f.path }}</div>
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

type FlatFile = { name: string; path: string }

const props = defineProps<{
  sessionId: string | null
  sessionTitle?: string
}>()

const loading = ref(false)
const error = ref('')
const allFiles = ref<FlatFile[]>([])
const selectedPath = ref('')
const uploadInputRef = ref<HTMLInputElement | null>(null)

async function listDir(path: string): Promise<{ name: string; path: string; is_dir?: boolean }[]> {
  const id = props.sessionId
  if (!id) return []
  const query = path ? `?path=${encodeURIComponent(path)}` : ''
  const r = await fetch(`/api/workspaces/${encodeURIComponent(id)}/files${query}`)
  const j = await r.json()
  if (j?.status !== 'ok') throw new Error(j?.detail || '加载失败')
  return (j?.data?.entries || []) as { name: string; path: string; is_dir?: boolean }[]
}

async function loadAllFiles() {
  const id = props.sessionId
  allFiles.value = []
  selectedPath.value = ''
  if (!id) return
  loading.value = true
  error.value = ''
  try {
    const queue: string[] = ['']
    const files: FlatFile[] = []
    while (queue.length > 0) {
      const current = queue.shift() || ''
      const entries = await listDir(current)
      for (const e of entries) {
        if (e.is_dir) queue.push(e.path)
        else files.push({ name: e.name, path: e.path })
      }
    }
    files.sort((a, b) => a.path.localeCompare(b.path))
    allFiles.value = files
    selectedPath.value = files[0]?.path || ''
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载失败'
  } finally {
    loading.value = false
  }
}

async function refreshAll() {
  await loadAllFiles()
}

async function createFile() {
  const id = props.sessionId
  if (!id) return
  const filename = window.prompt('新建文件名（如 note.md）', 'note.md')?.trim()
  if (!filename) return
  const r = await fetch(`/api/workspaces/${encodeURIComponent(id)}/files`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ filename, content: '' }),
  })
  const j = await r.json()
  if (j?.status !== 'ok') {
    alert(j?.detail || '新建文件失败')
    return
  }
  await loadAllFiles()
  if (j?.data?.path) selectedPath.value = j.data.path
}

async function createFolder() {
  const id = props.sessionId
  if (!id) return
  const dirname = window.prompt('新建文件夹名称', '新文件夹')?.trim()
  if (!dirname) return
  const r = await fetch(`/api/workspaces/${encodeURIComponent(id)}/files/mkdir`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ dirname }),
  })
  const j = await r.json()
  if (j?.status !== 'ok') {
    alert(j?.detail || '创建文件夹失败')
    return
  }
  await loadAllFiles()
}

async function onUpload(ev: Event) {
  const id = props.sessionId
  const input = ev.target as HTMLInputElement
  if (!id || !input.files?.length) return
  const fd = new FormData()
  fd.append('file', input.files[0])
  try {
    const r = await fetch(`/api/workspaces/${encodeURIComponent(id)}/files/upload`, {
      method: 'POST',
      body: fd,
    })
    const j = await r.json()
    if (j?.status !== 'ok') {
      alert(j?.detail || '上传失败')
      return
    }
    await loadAllFiles()
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
  await loadAllFiles()
}

function onRenamed(newPath: string) {
  selectedPath.value = newPath
  loadAllFiles()
}

watch(() => props.sessionId, () => {
  loadAllFiles()
}, { immediate: true })
</script>
