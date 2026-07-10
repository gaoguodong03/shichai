import { ref, type Ref } from 'vue'
import { apiRequest } from '@/api/base'
import { appAlert } from '@/composables/useAppDialog'

type ImportResult = { ok: boolean; message: string }

function isZipFile(file: File) {
  const name = file.name.toLowerCase()
  return name.endsWith('.zip') || file.type === 'application/zip' || file.type === 'application/x-zip-compressed'
}

function importSummaryLine(label: string, added: number, overwritten: number, failed = 0): string {
  return `${label}：新增 ${Math.max(0, added)} 个，覆盖 ${Math.max(0, overwritten)} 个，失败 ${Math.max(0, failed)} 个`
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
        await options.fetchMCP()
        if (j?.data?.directory_name) options.selectedId.value = j.data.directory_name
        const overwritten = j?.data?.summary?.overwritten_directory_names || []
        const skillAdded = j?.data?.directory_name && !overwritten.length ? 1 : 0
        skillImportResult.value = {
          ok: true,
          message: [
            importSummaryLine('技能', skillAdded, overwritten.length),
            importSummaryLine(
              '工具',
              j?.data?.mcp_added ?? j?.data?.summary?.mcp_added ?? 0,
              j?.data?.mcp_updated ?? j?.data?.summary?.mcp_updated ?? 0,
              j?.data?.mcp_failed ?? j?.data?.summary?.mcp_failed ?? 0,
            ),
          ].join('\n'),
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
        message: importSummaryLine('工具', summary.mcp_added ?? 0, summary.mcp_updated ?? 0, summary.mcp_failed ?? 0),
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
