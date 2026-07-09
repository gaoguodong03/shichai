import { onMounted, onUnmounted, type Ref } from 'vue'
import {
  HOST_NAME_UPDATED_EVENT_NAME,
  loadBoolPreference,
  publishBoolPreference,
  SESSION_PRESETS_UPDATED_EVENT_NAME,
  TOC_WORKSPACE_OPEN_STORAGE_KEY,
  USER_PREF_UPDATED_EVENT_NAME,
  WORKSPACE_OPEN_STORAGE_KEY,
} from './workspacePreferences'

export function useWorkspaceContentLifecycle(args: {
  showGroupWorkspace: Ref<boolean>
  expandedToolKey: Ref<string | null>
  setSessionMetaPopoverOpenFromPreference: (open: boolean) => void
  loadShortcutPresets: () => unknown
  loadHostDisplayName: () => unknown
  cleanupGroupStreamRuntime: () => void
}) {
  const {
    showGroupWorkspace,
    expandedToolKey,
    setSessionMetaPopoverOpenFromPreference,
    loadShortcutPresets,
    loadHostDisplayName,
    cleanupGroupStreamRuntime,
  } = args

  showGroupWorkspace.value = loadBoolPreference(WORKSPACE_OPEN_STORAGE_KEY)

  function toggleGroupWorkspaceOpen() {
    showGroupWorkspace.value = !showGroupWorkspace.value
    publishBoolPreference(WORKSPACE_OPEN_STORAGE_KEY, showGroupWorkspace.value)
  }

  function closeMembersDropdown(e: MouseEvent) {
    const el = e.target as HTMLElement
    if (!el?.closest?.('.group-chat-tool-tag-wrap')) expandedToolKey.value = null
  }

  function onUserPrefUpdated(ev: Event) {
    const e = ev as CustomEvent<{ key?: string; value?: unknown }>
    const key = e.detail?.key
    if (key === WORKSPACE_OPEN_STORAGE_KEY) {
      showGroupWorkspace.value = !!e.detail?.value
    }
    if (key === TOC_WORKSPACE_OPEN_STORAGE_KEY) {
      setSessionMetaPopoverOpenFromPreference(!!e.detail?.value)
    }
  }

  function onSessionPresetsUpdated() {
    loadShortcutPresets()
  }

  function onHostDisplayNameUpdated() {
    loadHostDisplayName()
  }

  onMounted(() => {
    document.addEventListener('click', closeMembersDropdown)
    window.addEventListener(USER_PREF_UPDATED_EVENT_NAME, onUserPrefUpdated as EventListener)
    window.addEventListener(SESSION_PRESETS_UPDATED_EVENT_NAME, onSessionPresetsUpdated)
    window.addEventListener(HOST_NAME_UPDATED_EVENT_NAME, onHostDisplayNameUpdated as EventListener)
    loadShortcutPresets()
    loadHostDisplayName()
  })

  onUnmounted(() => {
    document.removeEventListener('click', closeMembersDropdown)
    cleanupGroupStreamRuntime()
    window.removeEventListener(USER_PREF_UPDATED_EVENT_NAME, onUserPrefUpdated as EventListener)
    window.removeEventListener(SESSION_PRESETS_UPDATED_EVENT_NAME, onSessionPresetsUpdated)
    window.removeEventListener(HOST_NAME_UPDATED_EVENT_NAME, onHostDisplayNameUpdated as EventListener)
  })

  return { toggleGroupWorkspaceOpen }
}
