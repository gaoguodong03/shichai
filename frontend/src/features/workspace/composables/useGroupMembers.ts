import { computed, ref, type Ref } from 'vue'
import { apiRequest } from '@/api/base'
import { appAlert, appConfirm } from '@/composables/useAppDialog'
import { expertAvatarDisplayUrl } from '@/constants/expertAvatars'

export const VIRTUAL_SCENE_HOST_ID = 'agent-scene-host'

type GroupMemberMessage = {
  role: string
  agent_id?: string
  skill_id?: string
}

type GroupMemberDetail = {
  id?: string
  agent_ids: string[]
  leader_agent_id?: string
  agent_map: Record<string, { name?: string; avatar_url?: string }>
}

type AgentItem = {
  agent_id: string
  name: string
  avatar_url?: string
}

type SkillItem = {
  id: string
  name: string
}

const AGENT_AVATAR_COLORS = [
  'var(--color-agent-box-1)',
  'var(--color-agent-box-2)',
  'var(--color-agent-box-3)',
  'var(--color-agent-box-4)',
  'var(--color-agent-box-5)',
  'var(--color-agent-box-6)',
  'var(--color-agent-box-7)',
  'var(--color-agent-box-0)',
]

export function useGroupMembers(args: {
  groupDetail: Ref<GroupMemberDetail | null>
  agentInstances: () => AgentItem[]
  skills: () => SkillItem[]
  effectiveHostDisplayName: Ref<string>
  defaultHostDisplayName: string
  loadGroupDetail: () => Promise<void> | void
  emitAgentAdded: () => void
}) {
  const {
    groupDetail,
    agentInstances,
    skills,
    effectiveHostDisplayName,
    defaultHostDisplayName,
    loadGroupDetail,
    emitAgentAdded,
  } = args

  const showAddMemberModal = ref(false)

  function formatSkillId(skillId?: string) {
    if (!skillId) return ''
    if (skillId === 'default') return '默认'
    const hit = (skills() || []).find((s) => s.id === skillId)
    const label = (hit?.name || '').trim()
    if (label) return label
    return skillId
  }

  function isHostBubbleMessage(msg: GroupMemberMessage): boolean {
    if (msg.role === 'host') return true
    if (msg.role !== 'assistant') return false
    const mid = String(msg.agent_id || '').trim()
    if (!mid) return false
    if (mid === VIRTUAL_SCENE_HOST_ID) return true
    const lid = String(groupDetail.value?.leader_agent_id || '').trim()
    if (lid && mid === lid) {
      const sid = msg.skill_id
      const label = formatSkillId(sid)
      if (label.includes('主持')) return true
      if (sid && String(sid).toLowerCase().includes('host')) return true
    }
    return false
  }

  function bubbleDisplayName(msg: GroupMemberMessage): string {
    const aid = String(msg.agent_id || '').trim()
    if (isHostBubbleMessage(msg)) return effectiveHostDisplayName.value
    if (aid) {
      const name = (groupDetail.value?.agent_map || {})[aid]?.name
      if (name && String(name).trim()) return String(name).trim()
    }
    return aid || '—'
  }

  const invitableAgents = computed(() => {
    const inGroup = new Set(groupDetail.value?.agent_ids || [])
    return (agentInstances() || []).filter((d) => !inGroup.has(d.agent_id))
  })

  const leaderAgentId = computed(() => (groupDetail.value?.leader_agent_id || '').trim())
  const leaderDisplayId = computed(() => leaderAgentId.value || 'host')
  const orderedMemberIds = computed(() => {
    const ids = [...(groupDetail.value?.agent_ids || [])]
    const leader = leaderDisplayId.value
    const rest = ids.filter((id) => id !== leader)
    return [leader, ...rest]
  })

  function agentIndex(agentId?: string): number {
    const ids = groupDetail.value?.agent_ids || []
    const index = ids.indexOf(agentId || '')
    return index >= 0 ? index % AGENT_AVATAR_COLORS.length : 0
  }

  function agentAvatarColor(index: number): string {
    return AGENT_AVATAR_COLORS[index % AGENT_AVATAR_COLORS.length]
  }

  function agentAvatarChar(agentId?: string): string {
    const name = groupDetail.value?.agent_map?.[agentId || '']?.name || agentId || '?'
    return name.slice(0, 1).toUpperCase()
  }

  function expertAvatarUrl(agentId?: string): string | null {
    if (!agentId) return null
    const fromList = (agentInstances() || []).find((item) => item.agent_id === agentId)?.avatar_url
    const listUrl = fromList && String(fromList).trim()
    if (listUrl) return expertAvatarDisplayUrl(listUrl)
    const fromMap = groupDetail.value?.agent_map?.[agentId]?.avatar_url
    const mapUrl = fromMap && String(fromMap).trim()
    return expertAvatarDisplayUrl(mapUrl)
  }

  function displayGroupSpeakerName(agentId: string): string {
    const id = (agentId || '').trim()
    if (!id) return ''
    if (id === 'host' || id === VIRTUAL_SCENE_HOST_ID) return effectiveHostDisplayName.value || defaultHostDisplayName
    const fromInstances = (agentInstances() || []).find((item) => item.agent_id === id)?.name
    if (fromInstances && fromInstances.trim()) return fromInstances.trim()
    const fromMap = (groupDetail.value?.agent_map || {})[id]?.name
    if (fromMap && fromMap.trim()) return fromMap.trim()
    if (/^agent-[0-9a-f]{6,}$/i.test(id)) return '专家'
    return id
  }

  async function inviteSingleMember(agentId: string) {
    const id = groupDetail.value?.id
    if (!id) return
    try {
      const response = await apiRequest(`/sessions/${encodeURIComponent(id)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ add_agent_ids: [agentId] }),
      })
      const payload = await response.json().catch(() => ({}))
      if ((payload as { status?: string }).status === 'ok') {
        emitAgentAdded()
        await loadGroupDetail()
      } else {
        await appAlert({ title: '邀请失败', message: (payload as { detail?: string }).detail || '邀请失败', variant: 'danger' })
      }
    } catch {
      await appAlert({ title: '邀请失败', message: '邀请失败，请检查网络', variant: 'danger' })
    }
  }

  async function removeMember(agentId: string) {
    const id = groupDetail.value?.id
    const leader = (groupDetail.value?.leader_agent_id || '').trim()
    if (agentId === 'host') return
    if (leader && agentId === leader) return
    if (!id) return
    const ok = await appConfirm({
      title: '移出成员',
      message: '确定将该成员移出群聊？',
      variant: 'danger',
      confirmText: '移出',
    })
    if (!ok) return
    try {
      const response = await apiRequest(`/sessions/${encodeURIComponent(id)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ remove_agent_ids: [agentId] }),
      })
      const payload = await response.json().catch(() => ({}))
      if ((payload as { status?: string }).status === 'ok') {
        emitAgentAdded()
        await loadGroupDetail()
      } else {
        await appAlert({ title: '移出失败', message: (payload as { detail?: string }).detail || '移出失败', variant: 'danger' })
      }
    } catch {
      await appAlert({ title: '移出失败', message: '移出失败，请检查网络', variant: 'danger' })
    }
  }

  return {
    showAddMemberModal,
    invitableAgents,
    leaderDisplayId,
    orderedMemberIds,
    formatSkillId,
    isHostBubbleMessage,
    bubbleDisplayName,
    agentIndex,
    agentAvatarColor,
    agentAvatarChar,
    expertAvatarUrl,
    displayGroupSpeakerName,
    inviteSingleMember,
    removeMember,
    VIRTUAL_SCENE_HOST_ID,
  }
}
