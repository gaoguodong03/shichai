<template>
  <div
    v-if="suggestedDhas.length && !currentStreaming"
    class="group-chat-suggested-invite-bar"
  >
    <span class="group-chat-suggested-invite-text">
      {{ hostDisplayName }} 建议邀请
      <template v-for="(dha, idx) in suggestedDhas" :key="dha.id">
        <button
          type="button"
          class="group-chat-invite-inline-btn"
          :disabled="suggestedInviteLoading"
          @click="$emit('invite-one-suggested', dha.id)"
        >
          {{ dha.name }}
        </button>
        <span v-if="idx < suggestedDhas.length - 1" class="group-chat-suggested-sep">、</span>
      </template>
      加入讨论
    </span>
    <button
      type="button"
      class="group-chat-invite-suggested-btn"
      :disabled="suggestedInviteLoading"
      @click="$emit('invite-suggested')"
    >
      全部邀请
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
    v-else-if="waitingForUser"
    class="group-chat-speaker-status-input group-chat-speaker-status-paused"
  >
    <span class="group-chat-speaker-status-dot group-chat-speaker-status-dot-muted" aria-hidden="true" />
    <span class="group-chat-speaker-status-text">已暂停：等待你的确认</span>
    <span class="group-chat-speaker-status-sub">下一位：{{ nextSpeakerText }}</span>
    <span v-if="interruptHint" class="group-chat-speaker-status-sub">{{ interruptHint }}</span>
  </div>
  <div v-else-if="currentStreaming" class="group-chat-speaker-status-input group-chat-speaker-status-ready">
    <span class="group-chat-speaker-status-dot" aria-hidden="true" />
    <span class="group-chat-speaker-status-text">{{ streamingPhase || '正在运行' }}</span>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  suggestedDhas: Array<{ id: string; name: string }>
  hostDisplayName: string
  suggestedInviteLoading: boolean
  autoSwitchVisible: boolean
  autoSwitchText: string
  autoSwitchIgnoreLoading: boolean
  streamingSpeakerName: string
  streamingPulse: string
  waitingForUser: boolean
  nextSpeakerText: string
  interruptHint: string
  currentStreaming: boolean
  streamingPhase: string
}>()

defineEmits<{
  'invite-one-suggested': [id: string]
  'invite-suggested': []
  'dismiss-suggested': []
  'ignore-auto-switch': []
}>()
</script>
