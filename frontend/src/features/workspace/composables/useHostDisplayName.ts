import { apiRequest } from '@/api/base'
import { computed, ref, type Ref } from 'vue'
import type { GroupDetail } from './useGroupDetailLoader'

export const DEFAULT_HOST_DISPLAY_NAME = '四九'

export function useHostDisplayName(groupDetail: Ref<GroupDetail | null>) {
  const hostDisplayName = ref(DEFAULT_HOST_DISPLAY_NAME)
  const effectiveHostDisplayName = computed(() => {
    const hostName = String(groupDetail.value?.host?.name || '').trim()
    if (hostName) return hostName
    return (hostDisplayName.value || DEFAULT_HOST_DISPLAY_NAME).trim() || DEFAULT_HOST_DISPLAY_NAME
  })

  async function loadHostDisplayName() {
    try {
      const r = await apiRequest('/settings/host-profile')
      const j = await r.json().catch(() => ({}))
      const data = (j as { data?: { name?: string } })?.data
      const next = String(data?.name || '').trim()
      hostDisplayName.value = next || DEFAULT_HOST_DISPLAY_NAME
    } catch {
      hostDisplayName.value = DEFAULT_HOST_DISPLAY_NAME
    }
  }

  return {
    effectiveHostDisplayName,
    hostDisplayName,
    loadHostDisplayName,
  }
}
