import { watch, type ComputedRef, type Ref } from 'vue'
import type { Router } from 'vue-router'
import {
  resourceRoutePath,
  type ModuleId,
  type ResourceSubModule,
  type SettingsCategoryId,
} from './mainNavigation'

type MaybeAsync = Promise<void> | void

export function useMainModuleLifecycle(args: {
  router: Router
  currentModule: ComputedRef<ModuleId>
  resourceSubModule: ComputedRef<ResourceSubModule>
  settingsSection: ComputedRef<SettingsCategoryId>
  selectedId: Ref<string | null>
  resourceMenuExpanded: Ref<boolean>
  ensureMiddleColumnOpen: () => void
  resetResourceSearchesForSectionChange: () => void
  fetchScenarioPresets: () => MaybeAsync
  fetchSkills: () => MaybeAsync
  fetchMCP: () => MaybeAsync
  fetchAgents: () => MaybeAsync
  fetchLLM: () => MaybeAsync
  fetchFileSessions: () => MaybeAsync
  fetchGroupSessions: () => MaybeAsync
}) {
  const {
    router,
    currentModule,
    resourceSubModule,
    settingsSection,
    selectedId,
    resourceMenuExpanded,
    ensureMiddleColumnOpen,
    resetResourceSearchesForSectionChange,
    fetchScenarioPresets,
    fetchSkills,
    fetchMCP,
    fetchAgents,
    fetchLLM,
    fetchFileSessions,
    fetchGroupSessions,
  } = args

  const resourceLoaders: Record<ResourceSubModule, () => MaybeAsync> = {
    scenario: fetchScenarioPresets,
    skill: fetchSkills,
    mcp: fetchMCP,
    agent: fetchAgents,
    llm: fetchLLM,
    files: fetchFileSessions,
  }

  function loadResourceSection(section: ResourceSubModule) {
    return resourceLoaders[section]?.()
  }

  function onNavClick(moduleId: ModuleId) {
    if (moduleId === 'resource' && currentModule.value === 'resource') {
      resourceMenuExpanded.value = !resourceMenuExpanded.value
      return
    }
    if (moduleId === 'settings') {
      resourceMenuExpanded.value = false
      selectedId.value = 'app'
      ensureMiddleColumnOpen()
      void router.push('/settings/app')
      return
    }
    resourceMenuExpanded.value = moduleId === 'resource'
    if (moduleId !== 'resource') selectedId.value = null
    if (moduleId === 'resource') {
      ensureMiddleColumnOpen()
      void router.push('/resources/scenario')
      return
    }
    if (moduleId === 'workspace') void router.push('/workspace')
  }

  function onResourceChildClick(id: ResourceSubModule) {
    resourceMenuExpanded.value = true
    void router.push(resourceRoutePath(id))
  }

  watch(currentModule, (mod) => {
    if (mod !== 'resource') selectedId.value = null
    resourceMenuExpanded.value = mod === 'resource'
    if (mod === 'resource') {
      loadResourceSection(resourceSubModule.value)
    }
    if (mod === 'settings') selectedId.value = settingsSection.value
    if (mod === 'workspace') {
      fetchGroupSessions()
      fetchAgents()
      fetchSkills()
    }
  }, { immediate: true })

  watch(settingsSection, (section) => {
    if (currentModule.value === 'settings') selectedId.value = section
  })

  watch(resourceSubModule, (sub) => {
    resetResourceSearchesForSectionChange()
    if (sub === 'scenario') {
      fetchScenarioPresets()
      return
    }
    selectedId.value = null
    loadResourceSection(sub)
  })

  return {
    onNavClick,
    onResourceChildClick,
  }
}
