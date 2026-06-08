import { ref, type Ref } from 'vue'
import { apiRequest } from '@/api/base'
import { appAlert } from '@/composables/useAppDialog'

type ImportResult = { ok: boolean; message: string }

function isZipFile(file: File) {
  const name = file.name.toLowerCase()
  return name.endsWith('.zip') || file.type === 'application/zip' || file.type === 'application/x-zip-compressed'
}

export function useZipResourceImports(options: {
  selectedId: Ref<string | null>
  fetchSkills: () => Promise<void>
  fetchMCP: () => Promise<void>
}) {
  const skillZipInputRef = ref<HTMLInputElement | null>(null)
  const skillZipImporting = ref(false)
  const skillImportModalOpen = ref(false)
  const pendingSkillZipFile = ref<File | null>(null)
  const skillImportResult = ref<ImportResult | null>(null)
  const mcpZipInputRef = ref<HTMLInputElement | null>(null)
  const mcpZipImporting = ref(false)

  function triggerSkillZipImport() {
    if (skillZipImporting.value) return
    skillZipInputRef.value?.click()
  }

  async function onSkillZipSelected(e: Event) {
    const input = e.target as HTMLInputElement
    const file = input.files?.[0]
    input.value = ''
    if (!file) return
    if (!isZipFile(file)) {
      skillImportResult.value = { ok: false, message: '仅支持导入 ZIP 文件' }
      skillImportModalOpen.value = true
      return
    }
    pendingSkillZipFile.value = file
    skillImportResult.value = null
    skillImportModalOpen.value = true
  }

  function closeSkillImportModal() {
    skillImportModalOpen.value = false
    pendingSkillZipFile.value = null
    skillImportResult.value = null
  }

  function onSkillImportBackdropClick() {
    if (skillZipImporting.value || skillImportResult.value) return
    closeSkillImportModal()
  }

  async function commitSkillZipImport() {
    if (!pendingSkillZipFile.value || skillZipImporting.value) return
    skillImportResult.value = null
    skillZipImporting.value = true
    try {
      const fd = new FormData()
      fd.append('file', pendingSkillZipFile.value)
      fd.append('name_conflict', 'overwrite')
      const r = await apiRequest('/settings/skills/import-zip', {
        method: 'POST',
        body: fd,
      })
      const j = await r.json().catch(() => ({}))
      if (j?.status === 'ok') {
        await options.fetchSkills()
        if (j?.data?.id) options.selectedId.value = j.data.id
        skillImportResult.value = {
          ok: true,
          message: j?.data?.skipped_by_name
            ? `未导入：存在同名技能 "${j?.data?.name || '未知'}"`
            : `导入成功：${j?.data?.name || j?.data?.id || '技能'}`,
        }
      } else {
        skillImportResult.value = { ok: false, message: j?.detail || '导入技能失败' }
      }
    } catch (err) {
      console.error(err)
      skillImportResult.value = { ok: false, message: '导入技能失败，请检查网络或 ZIP 格式' }
    } finally {
      skillZipImporting.value = false
    }
  }

  function triggerMcpZipImport() {
    if (mcpZipImporting.value) return
    mcpZipInputRef.value?.click()
  }

  async function onMcpZipSelected(e: Event) {
    const input = e.target as HTMLInputElement
    const file = input.files?.[0]
    input.value = ''
    if (!file || mcpZipImporting.value) return
    if (!isZipFile(file)) {
      await appAlert({ title: '文件格式不支持', message: '仅支持导入 ZIP 文件', variant: 'warning' })
      return
    }
    mcpZipImporting.value = true
    try {
      const fd = new FormData()
      fd.append('file', file)
      const r = await apiRequest('/settings/mcp/import-zip', {
        method: 'POST',
        body: fd,
      })
      const j = await r.json().catch(() => ({}))
      if (j?.status !== 'ok') {
        throw new Error(j?.detail || '导入工具失败')
      }
      await options.fetchMCP()
      const summary = j?.data?.summary || {}
      await appAlert({
        title: '导入成功',
        message: `新增 ${summary.mcp_added ?? 0} 个，更新 ${summary.mcp_updated ?? 0} 个，跳过 ${summary.mcp_skipped ?? 0} 个`,
        variant: 'success',
      })
    } catch (err) {
      await appAlert({ title: '导入工具失败', message: (err as Error).message || '导入工具失败，请检查网络或 ZIP 格式', variant: 'danger' })
    } finally {
      mcpZipImporting.value = false
    }
  }

  return {
    skillZipInputRef,
    skillZipImporting,
    skillImportModalOpen,
    pendingSkillZipFile,
    skillImportResult,
    mcpZipInputRef,
    mcpZipImporting,
    triggerSkillZipImport,
    onSkillZipSelected,
    closeSkillImportModal,
    onSkillImportBackdropClick,
    commitSkillZipImport,
    triggerMcpZipImport,
    onMcpZipSelected,
  }
}
