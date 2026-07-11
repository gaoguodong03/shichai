<template>
  <div ref="menuRoot" class="px-3 pt-3 pb-3 flex-shrink-0 relative">
    <button
      type="button"
      aria-haspopup="menu"
      :aria-expanded="menuOpen ? 'true' : 'false'"
      @click.stop="toggleMenu"
      :class="[
        'w-full px-3 py-3 rounded-xl text-sm font-semibold flex items-center justify-center gap-1 transition-colors shadow-sm',
        creatingSession
          ? 'opacity-70 pointer-events-none bg-nav-selected-bg text-nav-selected-text'
          : 'bg-nav-selected-bg text-nav-selected-text hover:bg-nav-hover-bg'
      ]"
    >
      <span class="main-sidebar-asset-icon" :style="resourceIconStyle(resourceNewIconUrl)" aria-hidden="true" />
      <span>新建会话</span>
    </button>
    <div
      v-if="menuOpen"
      class="new-session-menu"
      role="menu"
      aria-label="新建会话"
      @click.stop
    >
      <button
        type="button"
        role="menuitem"
        class="new-session-menu-item"
        :disabled="creatingSession"
        @click="createBlank"
      >
        <span class="new-session-menu-item-title">空会话</span>
      </button>
      <div class="new-session-menu-divider" />
      <div v-if="scenarioLoading" class="new-session-menu-status">场景加载中...</div>
      <div v-else-if="!visibleScenarios.length" class="new-session-menu-status">暂无场景</div>
      <button
        v-else
        v-for="scenario in visibleScenarios"
        :key="scenario.name"
        type="button"
        role="menuitem"
        class="new-session-menu-item"
        @click="createFromScenario(scenario)"
      >
        <span class="new-session-menu-item-title">{{ scenario.name || '未命名场景' }}</span>
        <span class="new-session-menu-item-meta">{{ (scenario.agent_names || []).length }} 位专家</span>
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import resourceNewIconUrl from '@/assets/icons/resources/new.svg'
import { resourceIconStyle } from '@/features/resources/resourceIconStyle'
import type { ScenarioHostConfig } from '@/features/resources/useScenarioEditor'

type NewSessionScenario = {
  name: string
  agent_names: string[]
  host?: ScenarioHostConfig
  description?: string
  system_prompt?: string
}

const props = defineProps<{
  creatingSession: boolean
  scenarioLoading: boolean
  scenarios: NewSessionScenario[]
}>()

const emit = defineEmits<{
  (event: 'load-scenarios'): void
  (event: 'create-blank'): void
  (event: 'create-scenario', scenario: NewSessionScenario): void
}>()

const menuRoot = ref<HTMLElement | null>(null)
const menuOpen = ref(false)
const visibleScenarios = computed(() =>
  (props.scenarios || []).filter((scenario) => (scenario.name || '').trim() || (scenario.agent_names || []).length),
)

function closeMenu() {
  menuOpen.value = false
}

function toggleMenu() {
  if (props.creatingSession) return
  menuOpen.value = !menuOpen.value
  if (menuOpen.value) emit('load-scenarios')
}

function createBlank() {
  closeMenu()
  emit('create-blank')
}

function createFromScenario(scenario: NewSessionScenario) {
  closeMenu()
  emit('create-scenario', scenario)
}

function onDocumentClick(event: MouseEvent) {
  if (!menuOpen.value) return
  const root = menuRoot.value
  if (root && event.target instanceof Node && root.contains(event.target)) return
  closeMenu()
}

function onDocumentKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') closeMenu()
}

onMounted(() => {
  document.addEventListener('click', onDocumentClick)
  document.addEventListener('keydown', onDocumentKeydown)
})

onBeforeUnmount(() => {
  document.removeEventListener('click', onDocumentClick)
  document.removeEventListener('keydown', onDocumentKeydown)
})
</script>
