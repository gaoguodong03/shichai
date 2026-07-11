import { computed, type Ref } from 'vue'
import type { GroupDetail } from './useGroupDetailLoader'

export function useGroupTargetAgent(
  groupDetail: Ref<GroupDetail | null>,
  groupTargetAgentName: Ref<string | null>,
) {
  const groupTargetAgentDisplayName = computed(() => {
    const id = String(groupTargetAgentName.value || '').trim()
    if (!id) return ''
    return groupDetail.value?.agent_map?.[id]?.name || id
  })

  function clearGroupTargetAgentName() {
    groupTargetAgentName.value = null
  }

  return {
    clearGroupTargetAgentName,
    groupTargetAgentDisplayName,
  }
}
