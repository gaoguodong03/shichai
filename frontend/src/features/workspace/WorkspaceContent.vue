<template>
  <div class="workspace-right-content">
    <!-- 会话（带主持人，可选专家）：讨论目标/提示词、skill/系统调用展示、主题变量 -->
    <div v-if="groupDetail" class="workspace-right-inner workspace-group-root group-chat-theme">
      <div :key="'group-' + (groupDetail?.id ?? '')" class="workspace-group-wrap flex flex-col min-h-0">
        <GroupChatHeader />
        <div class="flex-1 min-h-0 flex overflow-visible">
          <div class="group-chat-main flex-1 min-h-0 flex flex-col overflow-visible">
            <div class="group-chat-main-row">
              <div class="group-chat-main-right">
                <GroupChatMessages />
                <GroupChatComposer />
              </div>
            </div>
          </div>
          <GroupWorkspacePanel />
        </div>
      </div>
    </div>

    <!-- 有选中 id 但尚未加载出 groupDetail：加载中 / 错误 / 恢复态 -->
    <div v-else-if="selectedGroupSessionId" class="workspace-right-inner workspace-group-root">
      <div v-if="groupLoading && !groupDetail" class="workspace-state workspace-state-loading">
        <div class="workspace-state-dots"><span /><span /><span /></div>
        <p class="workspace-state-text">加载会话中…</p>
      </div>
      <div v-else-if="groupError" class="workspace-state workspace-state-error">
        <p class="workspace-state-title">无法加载会话</p>
        <p class="workspace-state-text">{{ groupError }}</p>
        <button type="button" class="workspace-state-btn" @click="() => loadGroupDetail()">重试</button>
      </div>
      <div v-else class="workspace-state workspace-state-loading">
        <div class="workspace-state-dots"><span /><span /><span /></div>
        <p class="workspace-state-text">加载中…</p>
      </div>
    </div>

    <!-- 未选会话：空态 -->
    <div v-else class="workspace-state workspace-state-empty">
      <div class="workspace-empty-icon" aria-hidden="true">
        <svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
          <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
        </svg>
      </div>
      <h2 class="workspace-empty-title">选择会话开始协作</h2>
      <p class="workspace-empty-desc">
        在左侧选择已有会话，或点击「新建会话」新建新会话（默认仅主持人，可在会话内邀请专家）。
      </p>
      <p class="workspace-empty-hint">
        会话内可使用工作区、邀请专家等能力。
      </p>
    </div>
  </div>
</template>

<script setup lang="ts">
import hostLogoUrl from '@/assets/49logo.png'
import GroupChatHeader from './components/group-chat/GroupChatHeader.vue'
import GroupChatMessages from './components/group-chat/GroupChatMessages.vue'
import GroupChatComposer from './components/group-chat/GroupChatComposer.vue'
import GroupWorkspacePanel from './components/group-chat/GroupWorkspacePanel.vue'
import {
  type WorkspaceContentEmit,
  type WorkspaceContentProps,
  useWorkspaceContentProviders,
} from './composables/useWorkspaceContentProviders'

const props = defineProps<WorkspaceContentProps>()
const emit = defineEmits<WorkspaceContentEmit>()

const { groupDetail, groupLoading, groupError, loadGroupDetail, createSessionFromScenarioPreset } = useWorkspaceContentProviders({
  props,
  emit,
  hostLogoUrl,
})

defineExpose({ refresh: loadGroupDetail, createSessionFromScenarioPreset })
</script>

<style src="./WorkspaceContent.css"></style>
