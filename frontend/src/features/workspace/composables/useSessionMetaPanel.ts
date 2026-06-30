import { computed, nextTick, onUnmounted, ref, watch, type Ref } from 'vue'
import { apiRequest } from '@/api/base'
import { appAlert } from '@/composables/useAppDialog'
import { publishBoolPreference, TOC_WORKSPACE_OPEN_STORAGE_KEY } from './workspacePreferences'

type SessionMetaMessage = {
  message_id?: string
  role: string
  agent_name?: string
  content: string
}

type SessionMetaDetail = {
  id: string
  title: string
  agent_map: Record<string, { name?: string }>
}

type TocSpyEntry = { key: string; el: HTMLElement }

export function useSessionMetaPanel(args: {
  groupDetail: Ref<SessionMetaDetail | null>
  groupDisplayMessages: Ref<SessionMetaMessage[]>
  groupMessagesRef: Ref<HTMLElement | null>
  initialOpen: boolean
  onTitleSaved: () => void
}) {
  const sessionMetaPopoverOpen = ref(args.initialOpen)
  const sessionMetaPopoverRootRef = ref<HTMLElement | null>(null)
  const sessionTitleDraft = ref('')
  const titleSaving = ref(false)
  const tocActiveKey = ref<string>('')

  let sessionMetaOutsideTimer: ReturnType<typeof setTimeout> | null = null
  let tocSpyEntries: TocSpyEntry[] = []
  let tocSpyScrollEl: HTMLElement | null = null
  let tocSpyScrollHandler: ((e: Event) => void) | null = null
  let tocSpyRaf = 0

  const archiveItems = computed(() => {
    const detail = args.groupDetail.value
    const map = detail?.agent_map || {}
    return (args.groupDisplayMessages.value || [])
      .map((m, idx) => ({ m, idx }))
      .filter(({ m }) => m.role === 'assistant' && !!m.agent_name)
      .map(({ m, idx }) => {
        const did = (m.agent_name || '').trim()
        const name = (map[did]?.name || did || '专家').trim()
        return {
          key: (m.message_id || `idx-${idx}`) + '-' + did,
          agent_name: did,
          name,
          message_id: (m.message_id || `idx-${idx}`) as string,
          snippet: toSnippet(String(m.content || ''), 50),
        }
      })
  })

  function scrollToMessage(messageId: string) {
    const el = args.groupMessagesRef.value?.querySelector?.(`[data-message-id="${CSS.escape(messageId)}"]`) as HTMLElement | null
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }
  }

  function toggleSessionMetaPopover() {
    sessionMetaPopoverOpen.value = !sessionMetaPopoverOpen.value
    if (sessionMetaPopoverOpen.value) {
      sessionTitleDraft.value = args.groupDetail.value?.title || ''
    }
    publishBoolPreference(TOC_WORKSPACE_OPEN_STORAGE_KEY, sessionMetaPopoverOpen.value)
  }

  function setSessionMetaPopoverOpenFromPreference(open: boolean) {
    sessionMetaPopoverOpen.value = open
  }

  function closeSessionMetaPopover() {
    sessionMetaPopoverOpen.value = false
    unbindSessionMetaOutsideClick()
  }

  async function saveSessionTitle() {
    const id = args.groupDetail.value?.id
    if (!id) return
    const title = (sessionTitleDraft.value || '').trim()
    if (!title) return
    titleSaving.value = true
    try {
      const r = await apiRequest(`/sessions/${encodeURIComponent(id)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title }),
      })
      const j = await r.json().catch(() => ({}))
      if ((j as { status?: string }).status === 'ok') {
        if (args.groupDetail.value) args.groupDetail.value = { ...args.groupDetail.value, title }
        args.onTitleSaved()
      } else {
        await appAlert({ title: '保存标题失败', message: (j as { detail?: string }).detail || '保存标题失败', variant: 'danger' })
      }
    } catch {
      await appAlert({ title: '保存标题失败', message: '保存标题失败，请检查网络', variant: 'danger' })
    } finally {
      titleSaving.value = false
    }
  }

  function jumpToSessionTopic(messageId: string) {
    scrollToMessage(messageId)
    closeSessionMetaPopover()
  }

  function onDocClickCloseSessionMeta(e: MouseEvent) {
    const root = sessionMetaPopoverRootRef.value
    if (root && !root.contains(e.target as Node)) {
      sessionMetaPopoverOpen.value = false
    }
  }

  function bindSessionMetaOutsideClick() {
    unbindSessionMetaOutsideClick()
    sessionMetaOutsideTimer = setTimeout(() => {
      sessionMetaOutsideTimer = null
      document.addEventListener('click', onDocClickCloseSessionMeta)
    }, 0)
  }

  function unbindSessionMetaOutsideClick() {
    if (sessionMetaOutsideTimer) {
      clearTimeout(sessionMetaOutsideTimer)
      sessionMetaOutsideTimer = null
    }
    document.removeEventListener('click', onDocClickCloseSessionMeta)
  }

  function stopTocScrollSpy() {
    if (tocSpyScrollEl && tocSpyScrollHandler) {
      tocSpyScrollEl.removeEventListener('scroll', tocSpyScrollHandler)
    }
    tocSpyScrollEl = null
    tocSpyScrollHandler = null
    if (tocSpyRaf) cancelAnimationFrame(tocSpyRaf)
    tocSpyRaf = 0
  }

  function rebuildTocSpyEntries() {
    const sc = args.groupMessagesRef.value
    if (!sc) return
    const items = (archiveItems.value || []).map((it) => {
      const el = sc.querySelector(`[data-message-id="${CSS.escape(it.message_id)}"]`) as HTMLElement | null
      return el ? ({ key: it.key, el } as TocSpyEntry) : null
    })
    tocSpyEntries = items.filter(Boolean) as TocSpyEntry[]
    tocSpyEntries.sort((a, b) => (a.el.offsetTop || 0) - (b.el.offsetTop || 0))
  }

  function startTocScrollSpy() {
    const sc = args.groupMessagesRef.value
    if (!sc) return
    tocSpyScrollEl = sc
    const offsetTop = 90

    const updateActiveKey = () => {
      if (tocSpyRaf) cancelAnimationFrame(tocSpyRaf)
      tocSpyRaf = requestAnimationFrame(() => {
        const scRect = sc.getBoundingClientRect()
        let best: TocSpyEntry | null = null
        for (const entry of tocSpyEntries) {
          const rect = entry.el.getBoundingClientRect()
          const relTop = rect.top - scRect.top
          if (relTop <= offsetTop) best = entry
        }
        tocActiveKey.value = best?.key || ''
      })
    }

    tocSpyScrollHandler = updateActiveKey
    sc.addEventListener('scroll', updateActiveKey, { passive: true })
    updateActiveKey()
  }

  watch(
    () => [sessionMetaPopoverOpen.value, archiveItems.value.map((it) => it.key).join('|')],
    async ([open]) => {
      stopTocScrollSpy()
      tocActiveKey.value = ''
      if (!open) return
      await nextTick()
      rebuildTocSpyEntries()
      startTocScrollSpy()
    },
  )

  watch(sessionMetaPopoverOpen, (open) => {
    if (open) {
      bindSessionMetaOutsideClick()
    } else {
      unbindSessionMetaOutsideClick()
    }
  })

  watch(
    () => args.groupDetail.value?.title,
    (title) => {
      if (!sessionMetaPopoverOpen.value) sessionTitleDraft.value = title || ''
    },
  )

  onUnmounted(() => {
    unbindSessionMetaOutsideClick()
    stopTocScrollSpy()
  })

  return {
    sessionMetaPopoverRootRef,
    sessionMetaPopoverOpen,
    toggleSessionMetaPopover,
    setSessionMetaPopoverOpenFromPreference,
    closeSessionMetaPopover,
    sessionTitleDraft,
    saveSessionTitle,
    titleSaving,
    archiveItems,
    tocActiveKey,
    jumpToSessionTopic,
    scrollToMessage,
  }
}

function toSnippet(content: string, limit = 20) {
  const text = (content || '')
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
  if (!text) return '（空）'
  return text.length > limit ? text.slice(0, limit) + '…' : text
}
