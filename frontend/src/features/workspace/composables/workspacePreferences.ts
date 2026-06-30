export const USER_PREF_UPDATED_EVENT_NAME = 'agent-user-pref-updated'
export const SESSION_PRESETS_UPDATED_EVENT_NAME = 'agent-session-presets-updated'
export const HOST_NAME_UPDATED_EVENT_NAME = 'agent-host-display-name-updated'
export const USER_STORAGE_KEY = 'agent_user'
export const WORKSPACE_OPEN_STORAGE_KEY = 'agent_user_pref_workspace_open_v1'
export const TOC_WORKSPACE_OPEN_STORAGE_KEY = 'agent_user_pref_toc_workspace_open_v1'

export function loadBoolPreference(storageKey: string, defaultValue = false): boolean {
  try {
    const raw = localStorage.getItem(storageKey)
    if (raw === 'true') return true
    if (raw === 'false') return false
  } catch {
    // ignore storage failures
  }
  return defaultValue
}

export function persistBoolPreference(storageKey: string, value: boolean) {
  try {
    localStorage.setItem(storageKey, value ? 'true' : 'false')
  } catch {
    // ignore storage failures
  }
}

export function publishBoolPreference(storageKey: string, value: boolean) {
  persistBoolPreference(storageKey, value)
  window.dispatchEvent(
    new CustomEvent(USER_PREF_UPDATED_EVENT_NAME, {
      detail: { key: storageKey, value },
    }),
  )
}
