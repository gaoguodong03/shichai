<template>
  <div
    v-if="suggestedAgents.length && !currentStreaming"
    class="group-chat-suggested-invite-bar"
  >
    <span class="group-chat-suggested-invite-text">
      {{ hostDisplayName }}：点击专家名字选中
      <template v-for="(agent, idx) in suggestedAgents" :key="agent.id">
        <button
          type="button"
          class="group-chat-invite-inline-btn"
          :class="{ 'is-selected': isSelected(agent.id) }"
          :disabled="suggestedInviteLoading"
          @click="$emit('toggle-suggested-agent', agent.id)"
        >
          {{ agent.name }}
        </button>
        <span v-if="idx < suggestedAgents.length - 1" class="group-chat-suggested-sep">、</span>
      </template>
    </span>
    <button
      type="button"
      class="group-chat-invite-suggested-btn"
      :disabled="suggestedInviteLoading || !selectedAgentIds.length"
      @click="$emit('invite-selected-suggested')"
    >
      邀请已填入的专家
    </button>
    <button type="button" class="group-chat-dismiss-suggested-btn" @click="$emit('dismiss-suggested')">忽略</button>
  </div>

  <div v-if="autoSwitchVisible" class="group-chat-suggested-invite-bar">
    <span class="group-chat-suggested-invite-text">
      {{ autoSwitchText }}
    </span>
    <button
      type="button"
      class="group-chat-dismiss-suggested-btn"
      :disabled="autoSwitchIgnoreLoading"
      @click="$emit('ignore-auto-switch')"
    >
      {{ autoSwitchIgnoreLoading ? '暂停中…' : '忽略' }}
    </button>
  </div>

  <div v-if="streamingSpeakerName" class="group-chat-speaker-status-input">
    <span class="group-chat-speaker-status-dot" aria-hidden="true" />
    <span class="group-chat-speaker-status-text">
      正在运行：{{ streamingSpeakerName }}{{ streamingPulse }}
    </span>
  </div>
  <div
    v-else-if="confirmationRequired"
    class="group-chat-speaker-status-input group-chat-speaker-status-paused"
  >
    <span class="group-chat-speaker-status-dot group-chat-speaker-status-dot-muted" aria-hidden="true" />
    <span class="group-chat-speaker-status-text">
      已暂停：等待你的确认
    </span>
    <span class="group-chat-speaker-status-sub">下一位：{{ nextSpeakerText }}</span>
    <span v-if="interruptHint" class="group-chat-speaker-status-sub">{{ interruptHint }}</span>
  </div>
  <div v-else-if="currentStreaming" class="group-chat-speaker-status-input group-chat-speaker-status-ready">
    <span class="group-chat-speaker-status-dot" aria-hidden="true" />
    <span class="group-chat-speaker-status-text">{{ streamingPhase || '正在运行' }}</span>
  </div>
</template>

<script setup lang="ts">
const props = withDefaults(defineProps<{
  suggestedAgents: Array<{ id: string; name: string }>
  hostDisplayName: string
  suggestedInviteLoading: boolean
  selectedAgentIds?: string[]
  autoSwitchVisible: boolean
  autoSwitchText: string
  autoSwitchIgnoreLoading: boolean
  streamingSpeakerName: string
  streamingPulse: string
  confirmationRequired: boolean
  nextSpeakerText: string
  interruptHint: string
  currentStreaming: boolean
  streamingPhase: string
}>(), {
  selectedAgentIds: () => [],
})

defineEmits<{
  'toggle-suggested-agent': [id: string]
  'invite-selected-suggested': []
  'dismiss-suggested': []
  'ignore-auto-switch': []
}>()

function isSelected(id: string): boolean {
  return (props.selectedAgentIds || []).includes(id)
}
</script>
