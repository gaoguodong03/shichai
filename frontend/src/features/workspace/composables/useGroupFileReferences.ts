import { apiRequest } from '@/api/base'
import { appAlert } from '@/composables/useAppDialog'
import { ref, type Ref } from 'vue'
import { uploadWorkspaceFile } from '../workspaceUpload'

export type AttachedFile = { name: string; path: string }
type FileEntry = { name: string; path: string; is_dir: boolean }

function appendUniqueFile(files: Ref<AttachedFile[]>, file: AttachedFile) {
  if (!files.value.find((item) => item.path === file.path)) {
    files.value.push(file)
  }
}

function parentPath(path: string): string {
  const normalized = path.replace(/\/+$/, '')
  return normalized.includes('/') ? normalized.slice(0, normalized.lastIndexOf('/')) : ''
}

function childPath(basePath: string, childName: string): string {
  return basePath ? `${basePath}/${childName}` : childName
}

function clearFileReferenceFromPrompt(prompt: Ref<string>, file: AttachedFile) {
  const targets = new Set(
    [file.name, file.path, file.path.split('/').pop()]
      .map((value) => String(value || '').trim())
      .filter(Boolean),
  )
  if (!targets.size || !prompt.value) return

  let changed = false
  const kept = String(prompt.value)
    .split(/\r?\n/)
    .filter((line) => {
      const match = line.trim().match(/^【文件引用：(.+)】$/)
      if (!match) return true
      const parts = match[1].split('｜').map((value) => value.trim()).filter(Boolean)
      if (!parts.some((part) => targets.has(part))) return true
      changed = true
      return false
    })

  if (changed) {
    prompt.value = kept.join('\n').replace(/\n{3,}/g, '\n\n').trim()
  }
}

export function useGroupFileReferences(args: {
  sessionId: () => string | undefined
  prompt: Ref<string>
  loadWorkspace: () => Promise<unknown>
}) {
  const { sessionId, prompt, loadWorkspace } = args

  const showInsertFileModal = ref(false)
  const insertFileRef = ref<HTMLElement | null>(null)
  const insertFileBrowsePath = ref('')
  const insertFileEntries = ref<FileEntry[]>([])
  const insertFileLoading = ref(false)
  const insertLocalFileInputRef = ref<HTMLInputElement | null>(null)
  const insertLocalFileUploading = ref(false)
  const insertLocalFileUploadingName = ref('')
  const insertLocalFileUploadProgress = ref<number | null>(null)
  const attachedFiles = ref<AttachedFile[]>([])

  function triggerInsertLocalFile() {
    if (insertLocalFileUploading.value) return
    insertLocalFileInputRef.value?.click()
  }

  async function onInsertLocalFile(ev: Event) {
    const input = ev.target as HTMLInputElement
    const id = sessionId()
    if (!id || !input.files?.length || insertLocalFileUploading.value) return
    const file = input.files[0]
    insertLocalFileUploading.value = true
    insertLocalFileUploadingName.value = file.name || '本地文件'
    insertLocalFileUploadProgress.value = null
    try {
      const result = await uploadWorkspaceFile(id, file, '', ({ percent }) => {
        insertLocalFileUploadProgress.value = percent
      })
      if (result?.status === 'ok' && result?.data?.path) {
        await loadWorkspace()
        const relPath = result.data.path
        appendUniqueFile(attachedFiles, {
          name: file.name || relPath.split('/').pop() || relPath,
          path: relPath,
        })
        showInsertFileModal.value = false
      } else {
        await appAlert({ title: '上传失败', message: result?.detail || '上传失败', variant: 'danger' })
      }
    } catch (error) {
      await appAlert({ title: '上传失败', message: error instanceof Error ? error.message : '上传失败，请检查网络或后端', variant: 'danger' })
    } finally {
      insertLocalFileUploading.value = false
      insertLocalFileUploadingName.value = ''
      insertLocalFileUploadProgress.value = null
      input.value = ''
    }
  }

  async function loadInsertFileEntries() {
    const id = sessionId()
    if (!id) {
      insertFileEntries.value = []
      return
    }
    insertFileLoading.value = true
    insertFileEntries.value = []
    try {
      const query = insertFileBrowsePath.value ? `?path=${encodeURIComponent(insertFileBrowsePath.value)}` : ''
      const response = await apiRequest(`/workspaces/${encodeURIComponent(id)}/files${query}`)
      const payload = await response.json().catch(() => null)
      const raw = (payload?.status === 'ok' && Array.isArray(payload?.data?.entries)) ? payload.data.entries : []
      insertFileEntries.value = (raw as { name: string; path: string; is_dir?: boolean }[])
        .map((entry) => ({
          name: entry.name,
          path: entry.path,
          is_dir: !!entry.is_dir,
        }))
        .sort((a, b) => {
          if (a.is_dir !== b.is_dir) return a.is_dir ? -1 : 1
          return a.name.localeCompare(b.name)
        })
    } finally {
      insertFileLoading.value = false
    }
  }

  async function openInsertFileModal() {
    insertFileBrowsePath.value = ''
    showInsertFileModal.value = true
    await loadInsertFileEntries()
  }

  function insertFileEnterDir(entry: FileEntry) {
    if (!entry.is_dir) return
    insertFileBrowsePath.value = childPath(insertFileBrowsePath.value, entry.name)
    loadInsertFileEntries()
  }

  function insertFileGoUp() {
    if (!insertFileBrowsePath.value) return
    insertFileBrowsePath.value = parentPath(insertFileBrowsePath.value)
    loadInsertFileEntries()
  }

  function insertFileContent(entry: { name: string; path: string }) {
    appendUniqueFile(attachedFiles, { name: entry.name, path: entry.path })
    showInsertFileModal.value = false
  }

  function removeAttachedFile(path: string) {
    const removed = attachedFiles.value.find((file) => file.path === path)
    attachedFiles.value = attachedFiles.value.filter((file) => file.path !== path)
    if (removed) clearFileReferenceFromPrompt(prompt, removed)
  }

  function clearAttachedFiles() {
    attachedFiles.value = []
  }

  function setAttachedFiles(files: AttachedFile[]) {
    attachedFiles.value = [...files]
  }

  function buildMessageWithFileReferences(base: string): string {
    const fileRefs = attachedFiles.value.length
      ? '\n\n' + attachedFiles.value.map((file) => `【文件引用：${file.name}｜${file.path}】`).join('\n')
      : ''
    return `${base}${fileRefs}`.trim()
  }

  return {
    showInsertFileModal,
    insertFileRef,
    insertFileBrowsePath,
    insertFileEntries,
    insertFileLoading,
    insertLocalFileInputRef,
    insertLocalFileUploading,
    insertLocalFileUploadingName,
    insertLocalFileUploadProgress,
    attachedFiles,
    triggerInsertLocalFile,
    onInsertLocalFile,
    openInsertFileModal,
    insertFileEnterDir,
    insertFileGoUp,
    insertFileContent,
    removeAttachedFile,
    clearAttachedFiles,
    setAttachedFiles,
    buildMessageWithFileReferences,
  }
}
