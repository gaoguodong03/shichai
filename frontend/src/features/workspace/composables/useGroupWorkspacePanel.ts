import { computed, onUnmounted, ref, watch, type Ref } from 'vue'
import { uploadWorkspaceFile } from '../workspaceUpload'

type WorkspaceEntry = { name: string; path: string; is_dir: boolean }

export function useGroupWorkspacePanel(workspaceId: Ref<string>) {
  const showGroupWorkspace = ref(false)
  const groupWorkspacePath = ref('')
  const groupWorkspaceEntries = ref<WorkspaceEntry[]>([])
  const groupWorkspaceLoading = ref(false)
  const groupWorkspaceError = ref('')
  const groupWorkspacePreviewPath = ref('')
  const groupWorkspacePreviewName = ref('')
  const groupWorkspacePreviewContent = ref('')
  const groupWorkspacePreviewImageUrl = ref('')
  const groupWorkspacePreviewLoading = ref(false)
  const groupWorkspacePreviewEditing = ref(false)
  const groupWorkspacePreviewEditContent = ref('')
  const groupWorkspaceUploadInputRef = ref<HTMLInputElement | null>(null)
  const groupWorkspaceUploading = ref(false)
  const groupWorkspaceUploadingName = ref('')
  const groupWorkspaceUploadProgress = ref<number | null>(null)
  const groupWorkspaceWidth = ref(360)
  const groupWorkspaceListWidth = ref(192)
  const groupWorkspacePreviewCollapsed = ref(true)
  const isResizingWorkspace = ref(false)
  const isResizingWorkspaceInner = ref(false)
  const lastExpandedWorkspaceWidth = ref(672)
  let groupWorkspacePreviewObjectUrl: string | null = null
  let workspaceResizeStartX = 0
  let workspaceResizeStartWidth = 360
  let workspaceInnerResizeStartX = 0
  let workspaceInnerResizeStartWidth = 192

  function revokeGroupWorkspacePreviewBlob() {
    if (groupWorkspacePreviewObjectUrl) {
      try {
        URL.revokeObjectURL(groupWorkspacePreviewObjectUrl)
      } catch {
        // ignore
      }
      groupWorkspacePreviewObjectUrl = null
    }
  }

  function clearGroupWorkspacePreviewState() {
    revokeGroupWorkspacePreviewBlob()
    groupWorkspacePreviewPath.value = ''
    groupWorkspacePreviewName.value = ''
    groupWorkspacePreviewContent.value = ''
    groupWorkspacePreviewImageUrl.value = ''
    groupWorkspacePreviewEditing.value = false
  }

  function resetGroupWorkspacePanel() {
    clearGroupWorkspacePreviewState()
    groupWorkspacePath.value = ''
  }

  async function loadGroupWorkspace() {
    const id = workspaceId.value
    if (!id) return
    groupWorkspaceLoading.value = true
    groupWorkspaceError.value = ''
    try {
      const path = groupWorkspacePath.value ? `?path=${encodeURIComponent(groupWorkspacePath.value)}` : ''
      const r = await fetch(`/api/workspaces/${encodeURIComponent(id)}/files${path}`)
      const j = await r.json().catch(() => null)
      if (j?.status === 'ok' && Array.isArray(j?.data?.entries)) {
        groupWorkspaceEntries.value = j.data.entries.map((e: { name: string; path: string; is_dir?: boolean }) => ({
          name: e.name,
          path: e.path,
          is_dir: !!e.is_dir,
        }))
      } else {
        groupWorkspaceEntries.value = []
        groupWorkspaceError.value = j?.detail || '加载失败'
      }
    } catch {
      groupWorkspaceError.value = '网络错误'
      groupWorkspaceEntries.value = []
    } finally {
      groupWorkspaceLoading.value = false
    }
  }

  async function refreshGroupWorkspaceAfterExternalChange() {
    if (!showGroupWorkspace.value || !workspaceId.value) return
    const preview = groupWorkspacePreviewPath.value && !groupWorkspacePreviewEditing.value && !groupWorkspacePreviewCollapsed.value
      ? { name: groupWorkspacePreviewName.value, path: groupWorkspacePreviewPath.value }
      : null
    await loadGroupWorkspace()
    if (preview?.path) {
      await previewWorkspaceFile(preview)
    }
  }

  function groupWorkspaceGoRoot() {
    clearGroupWorkspacePreviewState()
    groupWorkspacePath.value = ''
    loadGroupWorkspace()
  }

  function groupWorkspaceEnterDir(e: WorkspaceEntry) {
    clearGroupWorkspacePreviewState()
    groupWorkspacePath.value = groupWorkspacePath.value ? `${groupWorkspacePath.value}/${e.name}` : e.name
    loadGroupWorkspace()
  }

  function goGroupWorkspaceUp() {
    if (!groupWorkspacePath.value) return
    const cur = groupWorkspacePath.value.replace(/\/+$/, '')
    const parent = cur.includes('/') ? cur.slice(0, cur.lastIndexOf('/')) : ''
    clearGroupWorkspacePreviewState()
    groupWorkspacePath.value = parent
    loadGroupWorkspace()
  }

  function groupWorkspaceDownloadUrl(filePath: string) {
    const id = workspaceId.value
    if (!id) return '#'
    return `/api/workspaces/${encodeURIComponent(id)}/files/download?path=${encodeURIComponent(filePath)}`
  }

  async function downloadGroupWorkspaceFile(e: { name: string; path: string; is_dir?: boolean }) {
    if (!e?.path || e.is_dir) return
    const url = groupWorkspaceDownloadUrl(e.path)
    if (!url || url === '#') return

    try {
      const r = await fetch(url)
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      const blob = await r.blob()
      const objUrl = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = objUrl
      a.download = e.name || e.path.split('/').pop() || 'download'
      a.rel = 'noopener'
      a.style.display = 'none'
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(objUrl)
    } catch {
      alert('下载失败，请检查网络或登录状态')
    }
  }

  async function createGroupWorkspaceDir() {
    const id = workspaceId.value
    if (!id) return
    const name = window.prompt('新建文件夹名称', '新文件夹')?.trim()
    if (!name) return
    try {
      const pathParam = groupWorkspacePath.value ? `?path=${encodeURIComponent(groupWorkspacePath.value)}` : ''
      const r = await fetch(`/api/workspaces/${encodeURIComponent(id)}/files/mkdir${pathParam}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ dirname: name }),
      })
      const j = await r.json().catch(() => ({}))
      if (j?.status === 'ok') {
        await loadGroupWorkspace()
      } else {
        alert((j as { detail?: string }).detail || '新建文件夹失败')
      }
    } catch {
      alert('新建文件夹失败，请检查网络或后端')
    }
  }

  async function createGroupWorkspaceFile() {
    const id = workspaceId.value
    if (!id) return
    const defaultName = groupWorkspacePath.value ? 'note.md' : 'novel-workflow-tasks.md'
    const name = window.prompt('新建文件名（相对当前目录，如 novel-workflow-tasks.md）', defaultName)?.trim()
    if (!name) return
    try {
      const pathParam = groupWorkspacePath.value ? `?path=${encodeURIComponent(groupWorkspacePath.value)}` : ''
      const r = await fetch(`/api/workspaces/${encodeURIComponent(id)}/files${pathParam}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filename: name, content: '' }),
      })
      const j = await r.json().catch(() => ({}))
      if (j?.status === 'ok') {
        await loadGroupWorkspace()
      } else {
        alert((j as { detail?: string }).detail || '新建文件失败')
      }
    } catch {
      alert('新建文件失败，请检查网络或后端')
    }
  }

  async function onGroupWorkspaceUpload(ev: Event) {
    const input = ev.target as HTMLInputElement
    const id = workspaceId.value
    if (!id || !input.files?.length || groupWorkspaceUploading.value) return
    const file = input.files[0]
    groupWorkspaceUploading.value = true
    groupWorkspaceUploadingName.value = file.name || '本地文件'
    groupWorkspaceUploadProgress.value = null
    try {
      const j = await uploadWorkspaceFile(id, file, groupWorkspacePath.value, ({ percent }) => {
        groupWorkspaceUploadProgress.value = percent
      })
      if (j?.status === 'ok') {
        await loadGroupWorkspace()
      } else {
        alert((j as { detail?: string }).detail || '上传失败')
      }
    } catch (e) {
      alert(e instanceof Error ? e.message : '上传失败，请检查网络或后端')
    } finally {
      groupWorkspaceUploading.value = false
      groupWorkspaceUploadingName.value = ''
      groupWorkspaceUploadProgress.value = null
      input.value = ''
    }
  }

  async function renameGroupWorkspaceEntry(e: WorkspaceEntry) {
    if (e.is_dir) return
    const id = workspaceId.value
    if (!id) return
    const name = window.prompt('重命名为', e.name)?.trim()
    if (name == null || name === '' || name === e.name) return
    try {
      const r = await fetch(`/api/workspaces/${encodeURIComponent(id)}/files/rename?path=${encodeURIComponent(e.path)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ new_name: name }),
      })
      const j = await r.json().catch(() => ({}))
      if (j?.status === 'ok') {
        if (groupWorkspacePreviewPath.value === e.path) clearGroupWorkspacePreviewState()
        await loadGroupWorkspace()
      } else {
        alert((j as { detail?: string }).detail || '重命名失败')
      }
    } catch {
      alert('重命名失败，请检查网络或后端')
    }
  }

  async function deleteGroupWorkspaceEntry(e: WorkspaceEntry) {
    const id = workspaceId.value
    if (!id) return
    const label = e.is_dir ? `目录「${e.name}」` : `文件「${e.name}」`
    const msg = e.is_dir
      ? '确定要删除该空目录吗？非空目录请先清空内容。'
      : `确定要删除 ${label} 吗？此操作不可恢复。`
    if (!window.confirm(msg)) return
    try {
      const r = await fetch(`/api/workspaces/${encodeURIComponent(id)}/files/content?path=${encodeURIComponent(e.path)}`, {
        method: 'DELETE',
      })
      const j = await r.json().catch(() => ({}))
      if (j?.status === 'ok') {
        if (groupWorkspacePreviewPath.value === e.path) clearGroupWorkspacePreviewState()
        await loadGroupWorkspace()
      } else {
        alert((j as { detail?: string }).detail || '删除失败')
      }
    } catch {
      alert('删除失败，请检查网络或后端')
    }
  }

  const textExt = ['.md', '.txt', '.json', '.jsonl', '.py', '.js', '.ts', '.vue', '.html', '.css', '.yaml', '.yml', '.xml', '.csv', '.log', '.docx']
  const imageExt = ['.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp', '.svg']
  function isTextFile(name: string) {
    const ext = name.includes('.') ? name.slice(name.lastIndexOf('.')).toLowerCase() : ''
    return textExt.includes(ext)
  }
  function isImageFile(name: string) {
    const ext = name.includes('.') ? name.slice(name.lastIndexOf('.')).toLowerCase() : ''
    return imageExt.includes(ext)
  }

  const groupWorkspacePreviewIsImage = computed(() => isImageFile(groupWorkspacePreviewName.value))

  function startWorkspacePreviewEdit() {
    groupWorkspacePreviewEditContent.value = groupWorkspacePreviewContent.value
    groupWorkspacePreviewEditing.value = true
  }

  function cancelWorkspacePreviewEdit() {
    groupWorkspacePreviewEditing.value = false
  }

  async function saveWorkspacePreviewEdit() {
    const id = workspaceId.value
    if (!id || !groupWorkspacePreviewPath.value) return
    try {
      const r = await fetch(`/api/workspaces/${encodeURIComponent(id)}/files/content?path=${encodeURIComponent(groupWorkspacePreviewPath.value)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: groupWorkspacePreviewEditContent.value }),
      })
      const j = await r.json().catch(() => ({}))
      if ((j as { status?: string }).status === 'ok') {
        groupWorkspacePreviewContent.value = groupWorkspacePreviewEditContent.value
        groupWorkspacePreviewEditing.value = false
      } else {
        alert((j as { detail?: string }).detail || '保存失败')
      }
    } catch {
      alert('保存失败，请检查网络或后端')
    }
  }

  async function previewWorkspaceFile(e: { name: string; path: string }) {
    if (groupWorkspacePreviewCollapsed.value) {
      groupWorkspacePreviewCollapsed.value = false
      groupWorkspaceWidth.value = lastExpandedWorkspaceWidth.value || 672
    }
    revokeGroupWorkspacePreviewBlob()
    groupWorkspacePreviewPath.value = e.path
    groupWorkspacePreviewName.value = e.name
    groupWorkspacePreviewContent.value = ''
    groupWorkspacePreviewImageUrl.value = ''
    groupWorkspacePreviewEditing.value = false
    if (isImageFile(e.name)) {
      groupWorkspacePreviewLoading.value = true
      try {
        const url = groupWorkspaceDownloadUrl(e.path)
        const r = await fetch(url)
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        const blob = await r.blob()
        const objUrl = URL.createObjectURL(blob)
        groupWorkspacePreviewObjectUrl = objUrl
        groupWorkspacePreviewImageUrl.value = objUrl
      } catch {
        groupWorkspacePreviewContent.value = '[ 图片预览失败，请使用上方「下载」查看 ]'
        groupWorkspacePreviewImageUrl.value = ''
      } finally {
        groupWorkspacePreviewLoading.value = false
      }
      return
    }
    if (!isTextFile(e.name)) {
      groupWorkspacePreviewContent.value = '[ 非文本文件，请点击「下载」查看 ]'
      return
    }
    groupWorkspacePreviewLoading.value = true
    try {
      const url = groupWorkspaceDownloadUrl(e.path)
      const r = await fetch(url)
      const text = await r.text()
      groupWorkspacePreviewContent.value = text || '(空)'
    } catch {
      groupWorkspacePreviewContent.value = '[ 加载失败 ]'
    } finally {
      groupWorkspacePreviewLoading.value = false
    }
  }

  function onGroupWorkspaceResizeMouseDown(e: MouseEvent) {
    e.preventDefault()
    isResizingWorkspace.value = true
    workspaceResizeStartX = e.clientX
    workspaceResizeStartWidth = groupWorkspaceWidth.value
    window.addEventListener('mousemove', onGroupWorkspaceResizeMouseMove)
    window.addEventListener('mouseup', onGroupWorkspaceResizeMouseUp)
  }

  function onGroupWorkspaceResizeMouseMove(e: MouseEvent) {
    if (!isResizingWorkspace.value) return
    const delta = workspaceResizeStartX - e.clientX
    const next = Math.min(840, Math.max(320, workspaceResizeStartWidth + delta))
    groupWorkspaceWidth.value = next
  }

  function onGroupWorkspaceResizeMouseUp() {
    if (!isResizingWorkspace.value) return
    isResizingWorkspace.value = false
    window.removeEventListener('mousemove', onGroupWorkspaceResizeMouseMove)
    window.removeEventListener('mouseup', onGroupWorkspaceResizeMouseUp)
  }

  function onWorkspaceInnerResizeMouseDown(e: MouseEvent) {
    e.preventDefault()
    if (groupWorkspacePreviewCollapsed.value) return
    isResizingWorkspaceInner.value = true
    workspaceInnerResizeStartX = e.clientX
    workspaceInnerResizeStartWidth = groupWorkspaceListWidth.value
    window.addEventListener('mousemove', onWorkspaceInnerResizeMouseMove)
    window.addEventListener('mouseup', onWorkspaceInnerResizeMouseUp)
  }

  function onWorkspaceInnerResizeMouseMove(e: MouseEvent) {
    if (!isResizingWorkspaceInner.value) return
    const delta = e.clientX - workspaceInnerResizeStartX
    const next = Math.min(320, Math.max(140, workspaceInnerResizeStartWidth + delta))
    groupWorkspaceListWidth.value = next
  }

  function onWorkspaceInnerResizeMouseUp() {
    if (!isResizingWorkspaceInner.value) return
    isResizingWorkspaceInner.value = false
    window.removeEventListener('mousemove', onWorkspaceInnerResizeMouseMove)
    window.removeEventListener('mouseup', onWorkspaceInnerResizeMouseUp)
  }

  function toggleWorkspacePreview() {
    if (!groupWorkspacePreviewCollapsed.value) {
      lastExpandedWorkspaceWidth.value = groupWorkspaceWidth.value
      groupWorkspaceWidth.value = Math.max(320, groupWorkspaceListWidth.value + 40)
      groupWorkspacePreviewCollapsed.value = true
    } else {
      groupWorkspacePreviewCollapsed.value = false
      groupWorkspaceWidth.value = lastExpandedWorkspaceWidth.value || 672
    }
  }

  watch(
    () => [showGroupWorkspace.value, workspaceId.value] as const,
    ([show, id]) => {
      if (show && id) {
        groupWorkspacePath.value = ''
        clearGroupWorkspacePreviewState()
        loadGroupWorkspace()
      }
    },
  )

  onUnmounted(() => {
    revokeGroupWorkspacePreviewBlob()
    window.removeEventListener('mousemove', onGroupWorkspaceResizeMouseMove)
    window.removeEventListener('mouseup', onGroupWorkspaceResizeMouseUp)
    window.removeEventListener('mousemove', onWorkspaceInnerResizeMouseMove)
    window.removeEventListener('mouseup', onWorkspaceInnerResizeMouseUp)
  })

  return {
    showGroupWorkspace,
    groupWorkspacePath,
    groupWorkspaceEntries,
    groupWorkspaceLoading,
    groupWorkspaceError,
    groupWorkspacePreviewPath,
    groupWorkspacePreviewName,
    groupWorkspacePreviewContent,
    groupWorkspacePreviewImageUrl,
    groupWorkspacePreviewLoading,
    groupWorkspacePreviewEditing,
    groupWorkspacePreviewEditContent,
    groupWorkspaceUploadInputRef,
    groupWorkspaceUploading,
    groupWorkspaceUploadingName,
    groupWorkspaceUploadProgress,
    groupWorkspaceWidth,
    groupWorkspaceListWidth,
    groupWorkspacePreviewCollapsed,
    groupWorkspacePreviewIsImage,
    loadGroupWorkspace,
    refreshGroupWorkspaceAfterExternalChange,
    resetGroupWorkspacePanel,
    groupWorkspaceGoRoot,
    groupWorkspaceEnterDir,
    goGroupWorkspaceUp,
    downloadGroupWorkspaceFile,
    createGroupWorkspaceDir,
    createGroupWorkspaceFile,
    onGroupWorkspaceUpload,
    renameGroupWorkspaceEntry,
    deleteGroupWorkspaceEntry,
    isTextFile,
    startWorkspacePreviewEdit,
    cancelWorkspacePreviewEdit,
    saveWorkspacePreviewEdit,
    previewWorkspaceFile,
    onGroupWorkspaceResizeMouseDown,
    onWorkspaceInnerResizeMouseDown,
    toggleWorkspacePreview,
  }
}
