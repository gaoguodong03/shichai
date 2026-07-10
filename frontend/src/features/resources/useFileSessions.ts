import { computed, ref, type ComputedRef, type Ref } from 'vue'
import { apiRequest } from '@/api/base'
import type { ResourceSubModule } from '@/features/shell/mainNavigation'

export type FileSessionSort = 'updated_desc' | 'updated_asc'

export type FileSessionRow = {
  id: string
  title: string
  updated_at: string
  file_count: number
}

export function useFileSessions(options: {
  resourceSubModule: ComputedRef<ResourceSubModule>
  selectedId: Ref<string | null>
}) {
  const fileSessions = ref<FileSessionRow[]>([])
  const fileSessionsLoading = ref(false)
  const fileSessionSearch = ref('')
  const fileSessionSort = ref<FileSessionSort>('updated_desc')

  const visibleFileSessions = computed(() => {
    const q = (fileSessionSearch.value || '').trim().toLowerCase()
    const list = (fileSessions.value || []).filter((s) => {
      if (!q) return true
      const title = (s.title || '').toLowerCase()
      return title.includes(q)
    })
    const arr = [...list]
    if (fileSessionSort.value === 'updated_desc') {
      arr.sort((a, b) => (b.updated_at || '').localeCompare(a.updated_at || ''))
    } else if (fileSessionSort.value === 'updated_asc') {
      arr.sort((a, b) => (a.updated_at || '').localeCompare(b.updated_at || ''))
    }
    return arr
  })

  function syncSelectedFileSession() {
    if (options.resourceSubModule.value !== 'files') return
    const ids = visibleFileSessions.value.map((s) => s.id)
    if (options.selectedId.value && !ids.includes(options.selectedId.value)) {
      options.selectedId.value = ids[0] || null
    } else if (!options.selectedId.value) {
      options.selectedId.value = ids[0] || null
    }
  }

  async function fetchFileSessions() {
    fileSessionsLoading.value = true
    try {
      const r = await apiRequest('/workspaces/sessions-with-files')
      if (r.ok) {
        const j = await r.json()
        fileSessions.value = j?.status === 'ok' && j?.data?.sessions ? j.data.sessions : []
      } else {
        fileSessions.value = await fetchFileSessionsFallback()
      }
      syncSelectedFileSession()
    } catch {
      fileSessions.value = []
    } finally {
      fileSessionsLoading.value = false
    }
  }

  return {
    fileSessions,
    fileSessionsLoading,
    fileSessionSearch,
    fileSessionSort,
    visibleFileSessions,
    fetchFileSessions,
  }
}

async function fetchFileSessionsFallback(): Promise<FileSessionRow[]> {
  const sRes = await apiRequest('/sessions')
  const sJson = await sRes.json()
  const sessions = (sJson?.status === 'ok' ? (sJson?.data?.sessions || []) : []) as Array<{
    id: string
    title?: string
    updated_at?: string
  }>
  const withFiles: FileSessionRow[] = []
  for (const s of sessions) {
    const fr = await apiRequest(`/sessions/${encodeURIComponent(s.id)}/workspace/files`)
    if (!fr.ok) continue
    const fj = await fr.json()
    const entries = (fj?.status === 'ok' ? (fj?.data?.entries || []) : []) as Array<{ is_dir?: boolean }>
    const fileCount = entries.filter((e) => !e.is_dir).length
    if (fileCount > 0) {
      withFiles.push({
        id: s.id,
        title: s.title || '新对话',
        updated_at: s.updated_at || '',
        file_count: fileCount,
      })
    }
  }
  return withFiles
}
