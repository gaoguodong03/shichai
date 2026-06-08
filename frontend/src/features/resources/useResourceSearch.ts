import { ref } from 'vue'

export type ResourceSearchKind = 'scenario' | 'agent' | 'skill' | 'mcp'

export function normalizedResourceQuery(value: string) {
  return (value || '').trim().toLowerCase()
}

export function useResourceSearch() {
  const showScenarioSearch = ref(false)
  const showAgentSearch = ref(false)
  const showSkillSearch = ref(false)
  const showMcpSearch = ref(false)
  const scenarioSearch = ref('')
  const agentSearch = ref('')
  const skillSearch = ref('')
  const mcpSearch = ref('')

  function toggleSearch(kind: ResourceSearchKind) {
    if (kind === 'scenario') {
      showScenarioSearch.value = !showScenarioSearch.value
      if (!showScenarioSearch.value) scenarioSearch.value = ''
    }
    if (kind === 'agent') {
      showAgentSearch.value = !showAgentSearch.value
      if (!showAgentSearch.value) agentSearch.value = ''
    }
    if (kind === 'skill') {
      showSkillSearch.value = !showSkillSearch.value
      if (!showSkillSearch.value) skillSearch.value = ''
    }
    if (kind === 'mcp') {
      showMcpSearch.value = !showMcpSearch.value
      if (!showMcpSearch.value) mcpSearch.value = ''
    }
  }

  function resetResourceSearchesForSectionChange() {
    showAgentSearch.value = false
    showSkillSearch.value = false
    showMcpSearch.value = false
    agentSearch.value = ''
    skillSearch.value = ''
    mcpSearch.value = ''
    scenarioSearch.value = ''
  }

  return {
    showScenarioSearch,
    showAgentSearch,
    showSkillSearch,
    showMcpSearch,
    scenarioSearch,
    agentSearch,
    skillSearch,
    mcpSearch,
    toggleSearch,
    resetResourceSearchesForSectionChange,
  }
}
