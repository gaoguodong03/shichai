import { computed } from 'vue'
import type { RouteLocationNormalizedLoaded } from 'vue-router'

export type ModuleId = 'workspace' | 'resource' | 'settings'
export type ResourceSubModule = 'scenario' | 'agent' | 'skill' | 'mcp' | 'llm' | 'files'
export type SettingsCategoryId = 'app' | 'theme' | 'secrets' | 'account-security' | 'sandbox'

export const resourceChildren: { id: ResourceSubModule; label: string }[] = [
  { id: 'scenario', label: '场景' },
  { id: 'agent', label: '专家' },
  { id: 'skill', label: '技能' },
  { id: 'mcp', label: '工具' },
  { id: 'llm', label: '模型' },
  { id: 'files', label: '文件' },
]

export const settingsCategories: { id: SettingsCategoryId; label: string }[] = [
  { id: 'app', label: '全局' },
  { id: 'theme', label: '配色' },
  { id: 'secrets', label: '密钥' },
  { id: 'account-security', label: '账号' },
  { id: 'sandbox', label: '沙箱' },
]

export function resourceRoutePath(id: ResourceSubModule) {
  return `/resources/${id}`
}

export function settingsRoutePath(id: SettingsCategoryId) {
  return `/settings/${id}`
}

export function useMainRouteState(route: RouteLocationNormalizedLoaded) {
  const currentModule = computed<ModuleId>(() => {
    if (route.path.startsWith('/resources')) return 'resource'
    if (route.path.startsWith('/settings')) return 'settings'
    return 'workspace'
  })

  const resourceSubModule = computed<ResourceSubModule>(() => {
    const section = String(route.params.section || 'scenario')
    return section === 'agent' || section === 'skill' || section === 'mcp' || section === 'llm' || section === 'files'
      ? section
      : 'scenario'
  })

  const settingsSection = computed<SettingsCategoryId>(() => {
    const section = String(route.params.section || 'app')
    return section === 'theme' || section === 'secrets' || section === 'account-security' || section === 'sandbox'
      ? section
      : 'app'
  })

  return {
    currentModule,
    resourceSubModule,
    settingsSection,
  }
}
