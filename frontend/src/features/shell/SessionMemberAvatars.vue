<template>
  <div class="mt-0.5 flex items-center gap-1">
    <template v-if="agentIds.length > 0">
      <div class="flex -space-x-1">
        <span
          v-for="avatar in visibleAvatars"
          :key="avatar.id"
          class="inline-flex items-center justify-center w-5 h-5 rounded-full text-[10px] font-semibold shrink-0 ring-1 ring-sidebar overflow-hidden"
          :class="avatar.imgUrl ? '' : 'text-text-inverse'"
          :style="avatar.imgUrl ? {} : { backgroundColor: avatar.color }"
        >
          <img
            v-if="avatar.imgUrl"
            :src="avatar.imgUrl"
            alt=""
            class="w-full h-full object-cover"
            width="20"
            height="20"
            decoding="async"
          />
          <template v-else>{{ avatar.char }}</template>
        </span>
      </div>
      <span class="truncate text-xs text-muted">
        {{ agentIds.length }} 位专家 · {{ formatSessionDate(updatedAt) }}
      </span>
    </template>
    <span v-else class="truncate text-xs text-muted">0 位专家 · {{ formatSessionDate(updatedAt) }}</span>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { expertAvatarDisplayUrl } from '@/constants/expertAvatars'
import { formatSessionDate } from './sessionListDisplay'

type SessionAvatarAgent = {
  agent_id: string
  name?: string
  avatar_url?: string
}

const AGENT_AVATAR_COLORS = [
  'var(--color-agent-box-0)',
  'var(--color-agent-box-1)',
  'var(--color-agent-box-2)',
  'var(--color-agent-box-3)',
  'var(--color-agent-box-4)',
  'var(--color-agent-box-5)',
  'var(--color-agent-box-6)',
  'var(--color-agent-box-7)',
]

const props = defineProps<{
  agentIds?: string[]
  agentInstances: SessionAvatarAgent[]
  updatedAt?: string
}>()

function agentAvatarColorForId(agentId: string, agentInstances: SessionAvatarAgent[]): string {
  const idx = Math.max(
    0,
    (agentInstances || []).findIndex((d) => d.agent_id === agentId),
  )
  return AGENT_AVATAR_COLORS[idx % AGENT_AVATAR_COLORS.length]
}

function agentAvatarCharForId(agentId: string, agentById: Map<string, SessionAvatarAgent>): string {
  const found = agentById.get(agentId)
  const name = (found?.name || agentId || '?').trim()
  return name ? name.slice(0, 1).toUpperCase() : '?'
}

function agentAvatarImgUrlForSession(agentId: string, agentById: Map<string, SessionAvatarAgent>): string | null {
  return expertAvatarDisplayUrl(agentById.get(agentId)?.avatar_url)
}

const agentIds = computed(() => props.agentIds || [])
const visibleAgentIds = computed(() => agentIds.value.slice(0, 3))
const agentById = computed(() => new Map((props.agentInstances || []).map((agent) => [agent.agent_id, agent])))
const visibleAvatars = computed(() => visibleAgentIds.value.map((id) => ({
  id,
  imgUrl: agentAvatarImgUrlForSession(id, agentById.value),
  color: agentAvatarColorForId(id, props.agentInstances),
  char: agentAvatarCharForId(id, agentById.value),
})))
</script>
