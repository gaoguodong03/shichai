<template>
  <div class="mt-0.5 flex items-center gap-1">
    <template v-if="agentNames.length > 0">
      <div class="flex -space-x-1">
        <span
          v-for="avatar in visibleAvatars"
          :key="avatar.id"
          class="inline-flex items-center justify-center w-5 h-5 rounded-full text-[10px] font-semibold shrink-0 ring-1 ring-sidebar overflow-hidden text-text-inverse"
          :style="{ backgroundColor: avatar.color }"
        >
          {{ avatar.char }}
        </span>
      </div>
      <span class="truncate text-xs text-muted">
        {{ agentNames.length }} 位专家 · {{ formatSessionDate(updatedAt) }}
      </span>
    </template>
    <span v-else class="truncate text-xs text-muted">0 位专家 · {{ formatSessionDate(updatedAt) }}</span>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { formatSessionDate } from './sessionListDisplay'

type SessionAvatarAgent = {
  name: string
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
  agentNames?: string[]
  agentInstances: SessionAvatarAgent[]
  updatedAt?: string
}>()

function agentAvatarColorForId(agentName: string, agentInstances: SessionAvatarAgent[]): string {
  const idx = Math.max(
    0,
    (agentInstances || []).findIndex((d) => d.name === agentName),
  )
  return AGENT_AVATAR_COLORS[idx % AGENT_AVATAR_COLORS.length]
}

function agentAvatarCharForId(agentName: string, agentByName: Map<string, SessionAvatarAgent>): string {
  const found = agentByName.get(agentName)
  const name = (found?.name || agentName || '?').trim()
  return name ? name.slice(0, 1).toUpperCase() : '?'
}

const agentNames = computed(() => props.agentNames || [])
const visibleAgentNames = computed(() => agentNames.value.slice(0, 3))
const agentByName = computed(() => new Map((props.agentInstances || []).map((agent) => [agent.name, agent])))
const visibleAvatars = computed(() => visibleAgentNames.value.map((id) => ({
  id,
  color: agentAvatarColorForId(id, props.agentInstances),
  char: agentAvatarCharForId(id, agentByName.value),
})))
</script>
