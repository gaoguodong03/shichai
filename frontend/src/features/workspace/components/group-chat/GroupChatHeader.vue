<template>
        <header class="group-chat-header">
          <div class="group-chat-header-left">
            <div
              :class="['group-chat-archive-anchor', props.middleColumnOpen === false ? 'group-chat-archive-anchor-collapse' : '']"
            >
              <button
                type="button"
                class="group-chat-header-btn group-chat-header-btn-icononly"
                title="会话列表"
                :aria-label="props.middleColumnOpen === false ? '展开会话列表列' : '收起会话列表列'"
                @click="emit('middle-column-toggle')"
              >
                <svg
                  class="group-chat-svg-icon"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="1.5"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                  aria-hidden="true"
                >
                  <path d="M8 6h13M8 12h13M8 18h13" />
                  <circle cx="4" cy="6" r="1.25" fill="currentColor" stroke="none" />
                  <circle cx="4" cy="12" r="1.25" fill="currentColor" stroke="none" />
                  <circle cx="4" cy="18" r="1.25" fill="currentColor" stroke="none" />
                </svg>
              </button>
            </div>
          </div>

          <div class="group-chat-title-wrap">
            <h1 class="group-chat-title">{{ groupDetail.title || '未命名' }}</h1>
            <div ref="sessionMetaPopoverRootRef" class="group-chat-title-actions-wrap">
              <button
                type="button"
                class="group-chat-header-btn group-chat-header-btn-icononly"
                :class="[sessionMetaPopoverOpen && 'group-chat-header-btn-active']"
                title="会话标题与主题"
                aria-haspopup="dialog"
                :aria-expanded="sessionMetaPopoverOpen"
                @click.stop="toggleSessionMetaPopover"
              >
                <svg
                  class="group-chat-svg-icon"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="1.5"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                  aria-hidden="true"
                >
                  <path d="M4 6h16M4 12h16M4 18h10" />
                </svg>
              </button>
              <div
                v-if="sessionMetaPopoverOpen"
                class="group-chat-session-meta-popover"
                role="dialog"
                aria-label="会话标题与主题"
                @click.stop
              >
                <div class="group-chat-meta-section">
                  <div class="group-chat-meta-label">会话标题</div>
                  <div class="group-chat-meta-title-row">
                    <input
                      v-model="sessionTitleDraft"
                      type="text"
                      class="group-chat-meta-input"
                      placeholder="输入标题"
                      maxlength="120"
                      @keydown.enter.prevent="saveSessionTitle"
                    />
                    <button
                      type="button"
                      class="group-chat-meta-save-btn"
                      :disabled="titleSaving || !(sessionTitleDraft || '').trim()"
                      @click="saveSessionTitle"
                    >
                      {{ titleSaving ? '保存中…' : '保存' }}
                    </button>
                  </div>
                </div>
                <div class="group-chat-meta-section group-chat-meta-section-topics">
                  <div class="group-chat-meta-label">专家发言</div>
                  <div v-if="!archiveItems.length" class="group-chat-meta-empty">暂无专家发言</div>
                  <div v-else class="group-chat-meta-topic-list">
                    <button
                      v-for="it in archiveItems"
                      :key="it.key"
                      type="button"
                      class="group-chat-meta-topic-item"
                      :class="[tocActiveKey === it.key && 'group-chat-meta-topic-item-active']"
                      @click="jumpToSessionTopic(it.message_id)"
                    >
                      <span class="group-chat-meta-topic-name">{{ it.name }}</span>
                      <div class="group-chat-meta-topic-snippet" v-html="renderSnippetMarkdown(it.snippet)" />
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div class="group-chat-header-right">
            <button
              type="button"
              :class="['group-chat-header-btn', showGroupWorkspace && 'group-chat-header-btn-active']"
              @click="toggleGroupWorkspaceOpen"
            >
              <span class="group-chat-svg-icon group-chat-workspace-icon-mask" :style="workspaceIconStyle(folderIconUrl)" aria-hidden="true" />
              文件
            </button>
          </div>
        </header>
</template>

<script setup lang="ts">
import {
  useGroupChatSessionContext,
  useGroupChatWorkspacePanelContext,
} from './groupChatWorkspaceContext'
import { workspaceIconStyle } from '../../workspaceIconStyle'
import folderIconUrl from '@/assets/icons/workspace/folder.svg'

const {
  props,
  emit,
  groupDetail,
  sessionMetaPopoverRootRef,
  sessionMetaPopoverOpen,
  toggleSessionMetaPopover,
  sessionTitleDraft,
  saveSessionTitle,
  titleSaving,
  archiveItems,
  tocActiveKey,
  jumpToSessionTopic,
  renderSnippetMarkdown,
} = useGroupChatSessionContext()

const {
  showGroupWorkspace,
  toggleGroupWorkspaceOpen,
} = useGroupChatWorkspacePanelContext()
</script>
