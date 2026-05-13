<template>
          <div
            v-if="showGroupWorkspace"
            class="group-chat-resizer"
            @mousedown="onGroupWorkspaceResizeMouseDown"
          />
          <aside
            v-if="showGroupWorkspace"
            class="group-chat-workspace"
            :style="{ width: groupWorkspaceWidth + 'px', minWidth: groupWorkspaceWidth + 'px' }"
          >
            <div class="group-chat-workspace-toolbar">
              <span class="group-chat-workspace-title">工作区</span>
              <div class="group-chat-workspace-toolbar-actions">
                <button
                  v-if="groupWorkspacePath"
                  type="button"
                  class="group-chat-workspace-back"
                  :disabled="groupWorkspaceUploading"
                  @click="goGroupWorkspaceUp"
                >
                  上一级
                </button>
                <button
                  v-if="groupWorkspacePath"
                  type="button"
                  class="group-chat-workspace-back"
                  :disabled="groupWorkspaceUploading"
                  @click="groupWorkspaceGoRoot"
                >
                  根目录
                </button>
                <button
                  type="button"
                  class="group-chat-workspace-toolbar-sm"
                  title="新建文件夹"
                  aria-label="新建文件夹"
                  :disabled="groupWorkspaceUploading"
                  @click="createGroupWorkspaceDir"
                >
                  <svg class="group-chat-workspace-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M4 7h4l2 3h10v8a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V9a2 2 0 0 1 2-2z" />
                    <path d="M12 11v6" />
                    <path d="M9 14h6" />
                  </svg>
                </button>
                <button
                  type="button"
                  class="group-chat-workspace-toolbar-sm"
                  title="新建文件"
                  aria-label="新建文件"
                  :disabled="groupWorkspaceUploading"
                  @click="createGroupWorkspaceFile"
                >
                  <svg class="group-chat-workspace-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                    <polyline points="14 2 14 8 20 8" />
                    <path d="M12 12v4" />
                    <path d="M10 14h4" />
                  </svg>
                </button>
                <button
                  type="button"
                  class="group-chat-workspace-toolbar-sm"
                  title="上传文件"
                  aria-label="上传文件"
                  :disabled="groupWorkspaceUploading"
                  @click="groupWorkspaceUploadInputRef?.click()"
                >
                  <svg class="group-chat-workspace-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M12 16V4" />
                    <path d="M8 8l4-4 4 4" />
                    <path d="M4 16v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2" />
                  </svg>
                </button>
                <button
                  type="button"
                  class="group-chat-workspace-toolbar-sm"
                  :title="groupWorkspacePreviewCollapsed ? '展开预览' : '收起预览'"
                  aria-label="切换预览"
                  :disabled="groupWorkspaceUploading"
                  @click="toggleWorkspacePreview()"
                >
                  <svg
                    class="group-chat-workspace-icon"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="1.6"
                    stroke-linecap="round"
                    stroke-linejoin="round"
                  >
                    <rect x="3" y="4" width="18" height="16" rx="2" />
                    <path v-if="!groupWorkspacePreviewCollapsed" d="M11 8l-3 4 3 4" />
                    <path v-else d="M13 8l3 4-3 4" />
                    <path d="M12 4v16" />
                  </svg>
                </button>
                <input
                  ref="groupWorkspaceUploadInputRef"
                  type="file"
                  class="hidden"
                  :disabled="groupWorkspaceUploading"
                  @change="onGroupWorkspaceUpload"
                />
              </div>
            </div>
            <div v-if="groupWorkspaceUploading" class="group-chat-uploading-notice group-chat-workspace-uploading-notice" role="status" aria-live="polite">
              <span class="group-chat-uploading-spinner" aria-hidden="true" />
              <span>
                正在上传 {{ groupWorkspaceUploadingName || '本地文件' }}{{ groupWorkspaceUploadProgress !== null ? `（${groupWorkspaceUploadProgress}%）` : '' }}，上传完成前请勿继续操作。
              </span>
            </div>
            <div class="group-chat-workspace-body" :class="{ 'group-chat-workspace-body-busy': groupWorkspaceUploading }">
              <div
                class="group-chat-workspace-list-col"
                :style="{
                  flex: groupWorkspacePreviewCollapsed ? '1 1 0%' : undefined,
                  flexBasis: groupWorkspacePreviewCollapsed ? 'auto' : groupWorkspaceListWidth + 'px',
                  maxWidth: groupWorkspacePreviewCollapsed ? '100%' : undefined,
                  borderRight: groupWorkspacePreviewCollapsed ? 'none' : undefined
                }"
              >
                <p v-if="groupWorkspacePath" class="group-chat-workspace-path-hint" :title="groupWorkspacePath">当前：{{ groupWorkspacePath }}</p>
                <p v-if="groupWorkspaceLoading" class="group-chat-workspace-muted">加载中…</p>
                <p v-else-if="groupWorkspaceError" class="group-chat-workspace-error">{{ groupWorkspaceError }}</p>
                <ul v-else class="group-chat-workspace-list">
                  <li v-for="e in groupWorkspaceEntries" :key="e.path" class="group-chat-workspace-item group-chat-workspace-item-row">
                    <button
                      v-if="e.is_dir"
                      type="button"
                      class="group-chat-workspace-item-btn group-chat-workspace-item-btn-main"
                      :disabled="groupWorkspaceUploading"
                      @click="groupWorkspaceEnterDir(e)"
                    >
                      <svg class="group-chat-workspace-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
                      <span class="truncate">{{ e.name }}</span>
                    </button>
                    <button
                      v-else
                      type="button"
                      class="group-chat-workspace-item-btn group-chat-workspace-item-btn-main"
                      :class="{ 'group-chat-workspace-item-selected': groupWorkspacePreviewPath === e.path }"
                      :disabled="groupWorkspaceUploading"
                      @click="previewWorkspaceFile(e)"
                    >
                      <svg class="group-chat-workspace-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>
                      <span class="truncate">{{ e.name }}</span>
                    </button>
                    <div class="group-chat-workspace-item-actions">
                      <button
                        v-if="!e.is_dir"
                        type="button"
                        class="group-chat-workspace-item-action"
                        title="下载"
                        :disabled="groupWorkspaceUploading"
                        @click.stop="downloadGroupWorkspaceFile(e)"
                      >↓</button>
                      <button
                        v-if="!e.is_dir"
                        type="button"
                        class="group-chat-workspace-item-action"
                        title="重命名"
                        :disabled="groupWorkspaceUploading"
                        @click.stop="renameGroupWorkspaceEntry(e)"
                      >R</button>
                      <button
                        type="button"
                        class="group-chat-workspace-item-action group-chat-workspace-item-action-danger"
                        :title="e.is_dir ? '删除空目录' : '删除文件'"
                        :disabled="groupWorkspaceUploading"
                        @click.stop="deleteGroupWorkspaceEntry(e)"
                      >×</button>
                    </div>
                  </li>
                  <li v-if="!groupWorkspaceEntries.length && !groupWorkspaceLoading" class="group-chat-workspace-muted">空</li>
                </ul>
              </div>
              <div
                v-if="!groupWorkspacePreviewCollapsed"
                class="group-chat-workspace-resizer"
                @mousedown="groupWorkspaceUploading ? undefined : onWorkspaceInnerResizeMouseDown($event)"
              />
              <div
                v-if="!groupWorkspacePreviewCollapsed"
                class="group-chat-workspace-preview-col"
              >
              <div v-if="groupWorkspacePreviewPath" class="group-chat-workspace-preview">
                <div class="group-chat-workspace-preview-header">
                  <span class="group-chat-workspace-preview-title">{{ groupWorkspacePreviewName }}</span>
                  <div class="group-chat-workspace-preview-actions">
                    <template v-if="isTextFile(groupWorkspacePreviewName) && !groupWorkspacePreviewLoading">
                      <template v-if="!groupWorkspacePreviewEditing">
                        <button
                          type="button"
                          class="group-chat-workspace-preview-edit-btn"
                          :disabled="groupWorkspaceUploading"
                          @click="downloadGroupWorkspaceFile({ name: groupWorkspacePreviewName, path: groupWorkspacePreviewPath })"
                        >
                          下载
                        </button>
                        <button type="button" class="group-chat-workspace-preview-edit-btn" :disabled="groupWorkspaceUploading" @click="startWorkspacePreviewEdit">编辑</button>
                      </template>
                      <template v-else>
                        <button type="button" class="group-chat-workspace-preview-save-btn" :disabled="groupWorkspaceUploading" @click="saveWorkspacePreviewEdit">保存</button>
                        <button type="button" class="group-chat-workspace-toolbar-sm" :disabled="groupWorkspaceUploading" @click="cancelWorkspacePreviewEdit">取消</button>
                      </template>
                    </template>
                  </div>
                </div>
                <div v-if="groupWorkspacePreviewLoading" class="group-chat-workspace-preview-loading">加载中…</div>
                <textarea
                  v-else-if="groupWorkspacePreviewEditing"
                  v-model="groupWorkspacePreviewEditContent"
                  class="group-chat-workspace-preview-textarea"
                  spellcheck="false"
                />
                <div v-else-if="groupWorkspacePreviewIsImage" class="group-chat-workspace-preview-image-wrap">
                  <img
                    v-if="groupWorkspacePreviewImageUrl"
                    :src="groupWorkspacePreviewImageUrl"
                    :alt="groupWorkspacePreviewName || '图片预览'"
                    class="group-chat-workspace-preview-image"
                  />
                  <pre v-else class="group-chat-workspace-preview-content">{{ groupWorkspacePreviewContent }}</pre>
                </div>
                <pre v-else class="group-chat-workspace-preview-content">{{ groupWorkspacePreviewContent }}</pre>
              </div>
              <div v-else class="group-chat-workspace-preview-placeholder">选择左侧文件以预览</div>
              </div>
            </div>
          </aside>
</template>

<script setup lang="ts">
import { useGroupChatWorkspaceContext } from './groupChatWorkspaceContext'

const {
  showGroupWorkspace,
  onGroupWorkspaceResizeMouseDown,
  groupWorkspaceWidth,
  groupWorkspacePath,
  goGroupWorkspaceUp,
  groupWorkspaceGoRoot,
  createGroupWorkspaceDir,
  createGroupWorkspaceFile,
  groupWorkspaceUploadInputRef,
  groupWorkspaceUploading,
  groupWorkspaceUploadingName,
  groupWorkspaceUploadProgress,
  onGroupWorkspaceUpload,
  groupWorkspacePreviewCollapsed,
  toggleWorkspacePreview,
  groupWorkspaceLoading,
  groupWorkspaceError,
  groupWorkspaceEntries,
  groupWorkspaceEnterDir,
  groupWorkspacePreviewPath,
  previewWorkspaceFile,
  downloadGroupWorkspaceFile,
  renameGroupWorkspaceEntry,
  deleteGroupWorkspaceEntry,
  onWorkspaceInnerResizeMouseDown,
  groupWorkspaceListWidth,
  groupWorkspacePreviewName,
  isTextFile,
  groupWorkspacePreviewLoading,
  groupWorkspacePreviewEditing,
  startWorkspacePreviewEdit,
  saveWorkspacePreviewEdit,
  cancelWorkspacePreviewEdit,
  groupWorkspacePreviewEditContent,
  groupWorkspacePreviewIsImage,
  groupWorkspacePreviewImageUrl,
  groupWorkspacePreviewContent,
} = useGroupChatWorkspaceContext()
</script>
