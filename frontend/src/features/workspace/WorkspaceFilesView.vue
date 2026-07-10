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
          class="inline-flex items-center justify-center gap-1.5 px-3 py-1.5 text-sm font-medium rounded-lg border border-input-border bg-card text-primary hover:bg-list-hover disabled:opacity-50"
          @click="refreshAll"
          :disabled="loading || !sessionId"
        >
          <span class="workspace-file-asset-icon" :style="workspaceIconStyle(refreshIconUrl)" aria-hidden="true" />
          刷新
        </button>
        <button
          type="button"
          class="inline-flex items-center justify-center gap-1.5 px-3 py-1.5 text-sm font-medium rounded-lg border border-input-border bg-card text-primary hover:bg-list-hover disabled:opacity-50"
          @click="createFile"
          :disabled="loading || !sessionId"
        >
          <span class="workspace-file-asset-icon" :style="workspaceIconStyle(newFileIconUrl)" aria-hidden="true" />
          新建文件
        </button>
        <button
          type="button"
          class="inline-flex items-center justify-center gap-1.5 px-3 py-1.5 text-sm font-medium rounded-lg border border-input-border bg-card text-primary hover:bg-list-hover disabled:opacity-50"
          @click="createFolder"
          :disabled="loading || !sessionId"
        >
          <span class="workspace-file-asset-icon" :style="workspaceIconStyle(newFolderIconUrl)" aria-hidden="true" />
          新建文件夹
        </button>
        <button
          type="button"
          class="inline-flex items-center justify-center gap-1.5 px-3 py-1.5 text-sm font-medium rounded-lg border border-input-border bg-card text-primary hover:bg-list-hover disabled:opacity-50"
          @click="uploadInputRef?.click()"
          :disabled="loading || uploading || !sessionId"
        >
          <span class="workspace-file-asset-icon" :style="workspaceIconStyle(uploadIconUrl)" aria-hidden="true" />
          {{ uploading ? '上传中…' : '上传文件' }}
        </button>
        <input ref="uploadInputRef" type="file" class="hidden" @change="onUpload" />
      </div>
    </header>
    <div v-if="uploading" class="px-4 py-2 border-b border-border bg-card text-xs text-muted truncate">
      正在上传 {{ uploadingName || '本地文件' }}{{ uploadProgressText }}
    </div>

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
          <div class="truncate font-medium flex items-center gap-1.5">
            <span
              class="workspace-file-asset-icon text-muted"
              :style="workspaceIconStyle(e.is_dir ? folderIconUrl : fileIconUrl)"
              aria-hidden="true"
            />
            {{ e.name }}
          </div>
          <div class="truncate text-xs text-muted mt-0.5">{{ e.path }}</div>
        </button>
      </aside>

      <main class="flex-1 min-w-0 min-h-0">
        <div v-if="!selectedPath" class="h-full flex items-center justify-center text-sm text-muted">
          选择文件后可预览与编辑
        </div>
        <FileDetailView
          v-else
          :workspace-id="sessionId"
          :path="selectedPath"
          @renamed="onRenamed"
          @delete-file="deleteSelectedFile"
        />
      </main>
    </div>
  </div>
</template>

<script setup lang="ts">
import { apiRequest } from '@/api/base'
import { computed, ref, watch } from 'vue'
import { appAlert, appConfirm, appPrompt } from '@/composables/useAppDialog'
import FileDetailView from './FileDetailView.vue'
import { uploadWorkspaceFile } from './workspaceUpload'
import { workspaceIconStyle } from './workspaceIconStyle'
import newFileIconUrl from '@/assets/icons/workspace/new-file.svg'
import newFolderIconUrl from '@/assets/icons/workspace/new-folder.svg'
import fileIconUrl from '@/assets/icons/workspace/file.svg'
import folderIconUrl from '@/assets/icons/workspace/folder.svg'
import refreshIconUrl from '@/assets/icons/workspace/refresh.svg'
import uploadIconUrl from '@/assets/icons/workspace/upload.svg'

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
const uploading = ref(false)
const uploadingName = ref('')
const uploadProgress = ref<number | null>(null)
const uploadProgressText = computed(() => (uploadProgress.value === null ? '' : `（${uploadProgress.value}%）`))

async function listDir(path: string): Promise<Entry[]> {
  const id = props.sessionId
  if (!id) return []
  const query = path ? `?path=${encodeURIComponent(path)}` : ''
  const r = await apiRequest(`/sessions/${encodeURIComponent(id)}/workspace/files${query}`)
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
    const list = (await listDir(path)).filter((e) => {
      const name = String(e?.name || '')
      if (name === '__pycache__') return false
      if (/\.(pyc|pyo)$/i.test(name)) return false
      return true
    })
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
  const filename = (await appPrompt({
    title: '新建文件',
    message: '请输入文件名。',
    defaultValue: 'note.md',
    placeholder: 'note.md',
    required: true,
  }))?.trim()
  if (!filename) return
  const query = currentDir.value ? `?path=${encodeURIComponent(currentDir.value)}` : ''
  const r = await apiRequest(`/sessions/${encodeURIComponent(id)}/workspace/files${query}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ filename, content: '' }),
  })
  const j = await r.json()
  if (j?.status !== 'ok') {
    await appAlert({ title: '新建文件失败', message: j?.detail || '新建文件失败', variant: 'danger' })
    return
  }
  await loadDir(currentDir.value)
  if (j?.data?.path) selectedPath.value = j.data.path
}

async function createFolder() {
  const id = props.sessionId
  if (!id) return
  const dirname = (await appPrompt({
    title: '新建文件夹',
    message: '请输入文件夹名称。',
    defaultValue: '新文件夹',
    required: true,
  }))?.trim()
  if (!dirname) return
  const query = currentDir.value ? `?path=${encodeURIComponent(currentDir.value)}` : ''
  const r = await apiRequest(`/sessions/${encodeURIComponent(id)}/workspace/files/mkdir${query}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ dirname }),
  })
  const j = await r.json()
  if (j?.status !== 'ok') {
    await appAlert({ title: '新建文件夹失败', message: j?.detail || '新建文件夹失败', variant: 'danger' })
    return
  }
  await loadDir(currentDir.value)
}

async function onUpload(ev: Event) {
  const id = props.sessionId
  const input = ev.target as HTMLInputElement
  if (!id || !input.files?.length || uploading.value) return
  const file = input.files[0]
  uploading.value = true
  uploadingName.value = file.name || '本地文件'
  uploadProgress.value = null
  try {
    const j = await uploadWorkspaceFile(id, file, currentDir.value, ({ percent }) => {
      uploadProgress.value = percent
    })
    if (j?.status !== 'ok') {
      await appAlert({ title: '上传失败', message: j?.detail || '上传失败', variant: 'danger' })
      return
    }
    await loadDir(currentDir.value)
    if (j?.data?.path) selectedPath.value = j.data.path
  } catch (e) {
    await appAlert({ title: '上传失败', message: e instanceof Error ? e.message : '上传失败，请检查网络或后端', variant: 'danger' })
  } finally {
    uploading.value = false
    uploadingName.value = ''
    uploadProgress.value = null
    input.value = ''
  }
}

async function deleteSelectedFile() {
  const id = props.sessionId
  const path = selectedPath.value
  if (!id || !path) return
  const ok = await appConfirm({
    title: '删除文件',
    message: `确定删除文件「${path}」？`,
    variant: 'danger',
    confirmText: '删除',
  })
  if (!ok) return
  const r = await apiRequest(`/sessions/${encodeURIComponent(id)}/workspace/files/content?path=${encodeURIComponent(path)}`, {
    method: 'DELETE',
  })
  const j = await r.json()
  if (j?.status !== 'ok') {
    await appAlert({ title: '删除失败', message: j?.detail || '删除失败', variant: 'danger' })
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

<style scoped>
.workspace-file-asset-icon {
  width: 1rem;
  height: 1rem;
  display: inline-block;
  flex-shrink: 0;
  background-color: currentColor;
  mask: var(--workspace-icon-url) center / contain no-repeat;
  -webkit-mask: var(--workspace-icon-url) center / contain no-repeat;
}
</style>
