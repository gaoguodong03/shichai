import { computed, nextTick, ref, type Ref } from 'vue'

export type AtMentionOption = {
  type: 'agent'
  id: string
  label: string
}

type MentionGroupDetail = {
  agent_names: string[]
  agent_map: Record<string, { name?: string }>
}

const AT_END_REG = /[\s，。、；：！？,.\-;:!?（）【】《》""''\[\]{}]/

export function useGroupAtMentions(args: {
  groupDetail: Ref<MentionGroupDetail | null>
  groupDiscussionGoal: Ref<string | null>
  groupTargetAgentName: Ref<string | null>
  sendGroupMessage: () => void | Promise<void>
}) {
  const {
    groupDetail,
    groupDiscussionGoal,
    groupTargetAgentName,
    sendGroupMessage,
  } = args

  const showAtDropdown = ref(false)
  const atSource = ref<'goal'>('goal')
  const atFilter = ref('')
  const atInsertStart = ref(0)
  const atSelectionEnd = ref(0)
  const atSelectedIndex = ref(0)
  const goalTextareaRef = ref<HTMLTextAreaElement | null>(null)
  const groupInputIsComposing = ref(false)

  const atMentionOptions = computed(() => {
    const detail = groupDetail.value
    const ids = detail?.agent_names || []
    const map = detail?.agent_map || {}
    const list = ids.map((id) => ({ type: 'agent' as const, id, label: map[id]?.name || id }))
    const query = (atFilter.value || '').trim().toLowerCase()
    if (!query) return list
    return list.filter((option) =>
      (option.label || '').toLowerCase().includes(query) || (option.id || '').toLowerCase().includes(query),
    )
  })

  function openAtDropdown(source: 'goal', value: string, insertStart: number, selectionEnd: number) {
    atSource.value = source
    atInsertStart.value = insertStart
    atSelectionEnd.value = selectionEnd
    atFilter.value = value.slice(insertStart + 1, selectionEnd)
    atSelectedIndex.value = 0
    showAtDropdown.value = true
  }

  function onAtInput(source: 'goal', e: Event) {
    const el = e.target as HTMLTextAreaElement
    const value = el.value
    const start = el.selectionStart ?? 0
    const end = el.selectionEnd ?? start
    const lastAt = value.lastIndexOf('@', end - 1)
    if (lastAt === -1 || (lastAt > 0 && /[\w\u4e00-\u9fa5]/.test(value[lastAt - 1]))) {
      showAtDropdown.value = false
      return
    }
    const segment = value.slice(lastAt + 1, end)
    if (segment && AT_END_REG.test(segment)) {
      showAtDropdown.value = false
      return
    }
    openAtDropdown(source, value, lastAt, end)
  }

  function selectMention(opt: AtMentionOption) {
    const raw = groupDiscussionGoal.value ?? ''
    const before = raw.slice(0, atInsertStart.value).replace(/\s+$/g, '')
    const after = raw.slice(atSelectionEnd.value).replace(/^\s+/g, '')
    const nextValue = before && after ? `${before} ${after}` : `${before}${after}`
    groupTargetAgentName.value = opt.id
    showAtDropdown.value = false

    groupDiscussionGoal.value = nextValue

    nextTick(() => {
      const textarea = goalTextareaRef.value
      textarea?.focus()
      const newPos = before.length + (before && after ? 1 : 0)
      textarea?.setSelectionRange(newPos, newPos)
    })
  }

  function onAtKeydown(_source: 'goal', e: KeyboardEvent) {
    if (!showAtDropdown.value || atMentionOptions.value.length === 0) return
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      atSelectedIndex.value = (atSelectedIndex.value + 1) % atMentionOptions.value.length
      return
    }
    if (e.key === 'ArrowUp') {
      e.preventDefault()
      atSelectedIndex.value = (atSelectedIndex.value - 1 + atMentionOptions.value.length) % atMentionOptions.value.length
      return
    }
    if (e.key === 'Escape') {
      showAtDropdown.value = false
    }
  }

  function onGroupCompositionStart() {
    groupInputIsComposing.value = true
  }

  function onGroupCompositionEnd() {
    setTimeout(() => {
      groupInputIsComposing.value = false
    }, 0)
  }

  function onGroupInputEnter(e: KeyboardEvent) {
    if ((e as KeyboardEvent & { isComposing?: boolean })?.isComposing || groupInputIsComposing.value) {
      return
    }
    if (showAtDropdown.value && atMentionOptions.value[atSelectedIndex.value]) {
      selectMention(atMentionOptions.value[atSelectedIndex.value])
      return
    }
    void sendGroupMessage()
  }

  function closeAtDropdownOnBlur() {
    setTimeout(() => {
      showAtDropdown.value = false
    }, 150)
  }

  return {
    goalTextareaRef,
    onAtInput,
    onAtKeydown,
    onGroupInputEnter,
    onGroupCompositionStart,
    onGroupCompositionEnd,
    closeAtDropdownOnBlur,
    showAtDropdown,
    atSource,
    atMentionOptions,
    atSelectedIndex,
    selectMention,
  }
}
