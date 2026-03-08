import { ref, computed, onMounted, onUnmounted } from 'vue'

const STORAGE_KEY = 'dha_theme'
const ACCENT_STORAGE_KEY = 'dha_accent'
const PRESET_STORAGE_KEY = 'dha_theme_preset'

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
  if (preset !== 'default') root.classList.add(`theme-${preset}`)
}

export function useTheme() {
  const preference = ref<ThemePreference>('system')
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
    try {
      localStorage.setItem(STORAGE_KEY, next)
    } catch (_) {}
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
    try {
      localStorage.setItem(ACCENT_STORAGE_KEY, next)
    } catch (_) {}
  }

  function setPreset(next: ThemePreset) {
    preset.value = next
    applyPreset(next)
    try {
      localStorage.setItem(PRESET_STORAGE_KEY, next)
    } catch (_) {}
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

  onMounted(() => {
    let stored: ThemePreference | null = null
    try {
      const s = localStorage.getItem(STORAGE_KEY)
      if (s === 'dark' || s === 'light' || s === 'system') stored = s
    } catch (_) {}
    const next = stored ?? 'system'
    preference.value = next
    const toApply = next === 'system' ? getSystemPreference() : next
    applyTheme(toApply)
    let accentStored: AccentPreference | null = null
    try {
      const a = localStorage.getItem(ACCENT_STORAGE_KEY)
      if (a === 'blue' || a === 'purple' || a === 'green') accentStored = a
    } catch (_) {}
    const accentNext = accentStored ?? 'blue'
    accent.value = accentNext
    applyAccent(accentNext)
    let presetStored: ThemePreset | null = null
    try {
      const p = localStorage.getItem(PRESET_STORAGE_KEY)
      if (p && PRESET_CLASSES.includes(p as ThemePreset)) presetStored = p as ThemePreset
    } catch (_) {}
    const presetNext = presetStored ?? 'default'
    preset.value = presetNext
    applyPreset(presetNext)
    const off = listenSystem()
    if (off) onUnmounted(off)
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
  }
}
