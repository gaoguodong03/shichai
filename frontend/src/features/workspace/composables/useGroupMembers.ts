import { computed, ref, type Ref } from 'vue'
import { apiRequest } from '@/api/base'
import { appAlert, appConfirm } from '@/composables/useAppDialog'
import { formatGroupSkillLabel } from '../groupSkillLabel'

export const VIRTUAL_SCENE_HOST_ID = 'agent-scene-host'

type GroupMemberMessage = {
  role: string
  agent_name?: string
  skill?: string
}

type GroupMemberDetail = {
  id?: string
  agent_names: string[]
  leader_agent_name?: string
  agent_map: Record<string, { name?: string }>
}

type AgentItem = {
  agent_name?: string
  name: string
}

type SkillItem = {
  directory_name: string
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

  function formatSkill(skill?: string) {
    return formatGroupSkillLabel({
      skill,
      skills: skills() || [],
    })
  }

  function isHostBubbleMessage(msg: GroupMemberMessage): boolean {
    if (msg.role === 'host') return true
    if (msg.role !== 'assistant') return false
    const mid = String(msg.agent_name || '').trim()
    if (!mid) return false
    if (mid === VIRTUAL_SCENE_HOST_ID) return true
    const lid = String(groupDetail.value?.leader_agent_name || '').trim()
    if (lid && mid === lid) {
      const sid = msg.skill
      const label = formatSkill(sid)
      if (label.includes('主持')) return true
      if (sid && String(sid).toLowerCase().includes('host')) return true
    }
    return false
  }

  function bubbleDisplayName(msg: GroupMemberMessage): string {
    const aid = String(msg.agent_name || '').trim()
    if (isHostBubbleMessage(msg)) return effectiveHostDisplayName.value
    if (aid) {
      const name = (groupDetail.value?.agent_map || {})[aid]?.name
      if (name && String(name).trim()) return String(name).trim()
    }
    return aid || '—'
  }

  const invitableAgents = computed(() => {
    const inGroup = new Set(groupDetail.value?.agent_names || [])
    return (agentInstances() || [])
      .map((d) => ({ ...d, agent_name: d.agent_name || d.name }))
      .filter((d) => d.agent_name && !inGroup.has(d.agent_name))
  })

  const leaderAgentName = computed(() => VIRTUAL_SCENE_HOST_ID)
  const leaderDisplayName = computed(() => leaderAgentName.value)
  const orderedMemberIds = computed(() => {
    const ids = [...(groupDetail.value?.agent_names || [])]
    const leader = leaderAgentName.value
    const rest = ids.filter((id) => id !== leader)
    return [leader, ...rest]
  })

  function agentIndex(agentName?: string): number {
    const ids = groupDetail.value?.agent_names || []
    const index = ids.indexOf(agentName || '')
    return index >= 0 ? index % AGENT_AVATAR_COLORS.length : 0
  }

  function agentAvatarColor(index: number): string {
    return AGENT_AVATAR_COLORS[index % AGENT_AVATAR_COLORS.length]
  }

  function agentAvatarChar(agentName?: string): string {
    const name = groupDetail.value?.agent_map?.[agentName || '']?.name || agentName || '?'
    return name.slice(0, 1).toUpperCase()
  }

  function expertAvatarUrl(agentName?: string): string | null {
    void agentName
    return null
  }

  function displayGroupSpeakerName(agentName: string): string {
    const id = (agentName || '').trim()
    if (!id) return ''
    if (id === 'host' || id === VIRTUAL_SCENE_HOST_ID) return effectiveHostDisplayName.value || defaultHostDisplayName
    const fromInstances = (agentInstances() || []).find((item) => (item.agent_name || item.name) === id)?.name
    if (fromInstances && fromInstances.trim()) return fromInstances.trim()
    const fromMap = (groupDetail.value?.agent_map || {})[id]?.name
    if (fromMap && fromMap.trim()) return fromMap.trim()
    if (/^agent-[0-9a-f]{6,}$/i.test(id)) return '专家'
    return id
  }

  async function inviteSingleMember(agentName: string) {
    const id = groupDetail.value?.id
    if (!id) return
    try {
      const response = await apiRequest(`/sessions/${encodeURIComponent(id)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ add_agent_names: [agentName] }),
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

  async function removeMember(agentName: string) {
    const id = groupDetail.value?.id
    if (agentName === 'host' || agentName === VIRTUAL_SCENE_HOST_ID) return
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
        body: JSON.stringify({ remove_agent_names: [agentName] }),
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
    leaderDisplayName,
    orderedMemberIds,
    formatSkill,
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
