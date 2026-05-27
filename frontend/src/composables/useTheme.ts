import { ref, computed, onMounted, onUnmounted } from 'vue'

const STORAGE_KEY = 'dha_theme'
const ACCENT_STORAGE_KEY = 'dha_accent'
const PRESET_STORAGE_KEY = 'dha_theme_preset'
const LOGIN_STORAGE_KEY = 'dha_logged_in'
const USER_STORAGE_KEY = 'dha_user'
const USER_ID_STORAGE_KEY = 'dha_user_id'

export const THEME_AUTH_CHANGED_EVENT = 'dha-theme-auth-changed'

export type Theme = 'light' | 'dark'
export type ThemePreference = 'light' | 'dark' | 'system'
export type AccentPreference = 'blue' | 'purple' | 'green'
export type ThemePreset = 'default' | 'warm' | 'cool' | 'forest' | 'ocean' | 'sunset' | 'contrast'

const PRESET_CLASSES: ThemePreset[] = ['default', 'warm', 'cool', 'forest', 'ocean', 'sunset', 'contrast']

function getSystemPreference(): Theme {
  if (typeof window === 'undefined' || !window.matchMedia) return 'light'
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

function applyTheme(theme: Theme) {
  const root = document.documentElement
  if (theme === 'dark') {
    root.classList.add('dark')
  } else {
    root.classList.remove('dark')
  }
}

function applyAccent(accent: AccentPreference) {
  const root = document.documentElement
  root.classList.remove('accent-blue', 'accent-purple', 'accent-green')
  root.classList.add(`accent-${accent}`)
}

function applyPreset(preset: ThemePreset) {
  const root = document.documentElement
  PRESET_CLASSES.forEach((c) => root.classList.remove(`theme-${c}`))
  root.classList.add(`theme-${preset}`)
}

function safeGetItem(key: string): string | null {
  try {
    return localStorage.getItem(key)
  } catch (_) {
    return null
  }
}

function safeSetItem(key: string, value: string) {
  try {
    localStorage.setItem(key, value)
  } catch (_) {}
}

function currentThemeScope(): string | null {
  if (safeGetItem(LOGIN_STORAGE_KEY) !== 'true') return null
  const user = (safeGetItem(USER_ID_STORAGE_KEY) || safeGetItem(USER_STORAGE_KEY) || '').trim()
  return user || null
}

function scopedStorageKey(key: string): string | null {
  const scope = currentThemeScope()
  if (!scope) return null
  return `${key}:${encodeURIComponent(scope)}`
}

export function useTheme() {
  const preference = ref<ThemePreference>('light')
  const accent = ref<AccentPreference>('blue')
  const preset = ref<ThemePreset>('default')

  const theme = computed<Theme>(() => {
    if (preference.value === 'system') return getSystemPreference()
    return preference.value
  })

  function setPreference(next: ThemePreference) {
    preference.value = next
    const toApply = next === 'system' ? getSystemPreference() : next
    applyTheme(toApply)
    const key = scopedStorageKey(STORAGE_KEY)
    if (key) safeSetItem(key, next)
  }

  function setTheme(next: Theme) {
    const pref: ThemePreference = next === 'dark' ? 'dark' : 'light'
    setPreference(pref)
  }

  function toggleTheme() {
    const next = theme.value === 'dark' ? 'light' : 'dark'
    setPreference(next)
  }

  function setAccent(next: AccentPreference) {
    accent.value = next
    applyAccent(next)
    const key = scopedStorageKey(ACCENT_STORAGE_KEY)
    if (key) safeSetItem(key, next)
  }

  function setPreset(next: ThemePreset) {
    preset.value = next
    applyPreset(next)
    const key = scopedStorageKey(PRESET_STORAGE_KEY)
    if (key) safeSetItem(key, next)
  }

  function listenSystem() {
    if (typeof window === 'undefined' || !window.matchMedia) return
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    const handler = () => {
      if (preference.value === 'system') applyTheme(getSystemPreference())
    }
    mq.addEventListener('change', handler)
    return () => mq.removeEventListener('change', handler)
  }

  function loadThemeForCurrentUser() {
    let stored: ThemePreference | null = null
    const storageKey = scopedStorageKey(STORAGE_KEY)
    const s = storageKey ? safeGetItem(storageKey) : null
    if (s === 'dark' || s === 'light' || s === 'system') stored = s
    const next = stored ?? 'light'
    preference.value = next
    const toApply = next === 'system' ? getSystemPreference() : next
    applyTheme(toApply)

    let accentStored: AccentPreference | null = null
    const accentKey = scopedStorageKey(ACCENT_STORAGE_KEY)
    const a = accentKey ? safeGetItem(accentKey) : null
    if (a === 'blue' || a === 'purple' || a === 'green') accentStored = a
    const accentNext = accentStored ?? 'blue'
    accent.value = accentNext
    applyAccent(accentNext)

    let presetStored: ThemePreset | null = null
    const presetKey = scopedStorageKey(PRESET_STORAGE_KEY)
    const p = presetKey ? safeGetItem(presetKey) : null
    if (p && PRESET_CLASSES.includes(p as ThemePreset)) presetStored = p as ThemePreset
    const presetNext = presetStored ?? 'default'
    preset.value = presetNext
    applyPreset(presetNext)
  }

  onMounted(() => {
    loadThemeForCurrentUser()
    const off = listenSystem()
    const onAuthChanged = () => loadThemeForCurrentUser()
    window.addEventListener(THEME_AUTH_CHANGED_EVENT, onAuthChanged)
    onUnmounted(() => {
      if (off) off()
      window.removeEventListener(THEME_AUTH_CHANGED_EVENT, onAuthChanged)
    })
  })

  return {
    theme,
    preference,
    accent,
    preset,
    setPreference,
    setTheme,
    setAccent,
    setPreset,
    toggleTheme,
    listenSystem,
    loadThemeForCurrentUser,
  }
}
