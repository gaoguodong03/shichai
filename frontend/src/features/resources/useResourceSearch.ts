import { ref } from 'vue'

export type ResourceSearchKind = 'scenario' | 'agent' | 'skill' | 'mcp' | 'llm'

export function normalizedResourceQuery(value: string) {
  return (value || '').trim().toLowerCase()
}

export function useResourceSearch() {
  const showScenarioSearch = ref(false)
  const showAgentSearch = ref(false)
  const showSkillSearch = ref(false)
  const showMcpSearch = ref(false)
  const showLlmSearch = ref(false)
  const scenarioSearch = ref('')
  const agentSearch = ref('')
  const skillSearch = ref('')
  const mcpSearch = ref('')
  const llmSearch = ref('')

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
    if (kind === 'llm') {
      showLlmSearch.value = !showLlmSearch.value
      if (!showLlmSearch.value) llmSearch.value = ''
    }
  }

  function resetResourceSearchesForSectionChange() {
    showAgentSearch.value = false
    showSkillSearch.value = false
    showMcpSearch.value = false
    showLlmSearch.value = false
    agentSearch.value = ''
    skillSearch.value = ''
    mcpSearch.value = ''
    llmSearch.value = ''
    scenarioSearch.value = ''
  }

  return {
    showScenarioSearch,
    showAgentSearch,
    showSkillSearch,
    showMcpSearch,
    showLlmSearch,
    scenarioSearch,
    agentSearch,
    skillSearch,
    mcpSearch,
    llmSearch,
    toggleSearch,
    resetResourceSearchesForSectionChange,
  }
}
