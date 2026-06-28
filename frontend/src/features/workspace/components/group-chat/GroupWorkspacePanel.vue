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
                <div v-if="groupWorkspacePath" class="group-chat-workspace-path-actions" aria-label="路径导航">
                  <button
                    type="button"
                    class="group-chat-workspace-back"
                    :disabled="groupWorkspaceUploading"
                    @click="goGroupWorkspaceUp"
                  >
                    上一级
                  </button>
                  <button
                    type="button"
                    class="group-chat-workspace-back"
                    :disabled="groupWorkspaceUploading"
                    @click="groupWorkspaceGoRoot"
                  >
                    根目录
                  </button>
                </div>
                <div class="group-chat-workspace-file-actions" aria-label="文件操作">
                  <button
                    type="button"
                    class="group-chat-workspace-toolbar-sm"
                    title="刷新工作区"
                    aria-label="刷新工作区"
                    :disabled="groupWorkspaceUploading || groupWorkspaceLoading"
                    @click="loadGroupWorkspace"
                  >
                    <span class="group-chat-workspace-icon group-chat-workspace-icon-mask" :style="workspaceIconStyle(refreshIconUrl)" aria-hidden="true" />
                  </button>
                  <button
                    type="button"
                    class="group-chat-workspace-toolbar-sm"
                    title="新建文件夹"
                    aria-label="新建文件夹"
                    :disabled="groupWorkspaceUploading"
                    @click="createGroupWorkspaceDir"
                  >
                    <span class="group-chat-workspace-icon group-chat-workspace-icon-mask" :style="workspaceIconStyle(newFolderIconUrl)" aria-hidden="true" />
                  </button>
                  <button
                    type="button"
                    class="group-chat-workspace-toolbar-sm"
                    title="新建文件"
                    aria-label="新建文件"
                    :disabled="groupWorkspaceUploading"
                    @click="createGroupWorkspaceFile"
                  >
                    <span class="group-chat-workspace-icon group-chat-workspace-icon-mask" :style="workspaceIconStyle(newFileIconUrl)" aria-hidden="true" />
                  </button>
                  <button
                    type="button"
                    class="group-chat-workspace-toolbar-sm"
                    title="上传文件"
                    aria-label="上传文件"
                    :disabled="groupWorkspaceUploading"
                    @click="groupWorkspaceUploadInputRef?.click()"
                  >
                    <span class="group-chat-workspace-icon group-chat-workspace-icon-mask" :style="workspaceIconStyle(uploadIconUrl)" aria-hidden="true" />
                  </button>
                  <button
                    type="button"
                    class="group-chat-workspace-toolbar-sm"
                    :title="groupWorkspacePreviewCollapsed ? '展开预览' : '收起预览'"
                    aria-label="切换预览"
                    :disabled="groupWorkspaceUploading"
                    @click="toggleWorkspacePreview()"
                  >
                    <span class="group-chat-workspace-icon group-chat-workspace-icon-mask" :style="workspaceIconStyle(previewIconUrl)" aria-hidden="true" />
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
                      <span class="group-chat-workspace-svg group-chat-workspace-icon-mask" :style="workspaceIconStyle(folderIconUrl)" aria-hidden="true" />
                      <span class="truncate" :title="e.name">{{ e.name }}</span>
                    </button>
                    <button
                      v-else
                      type="button"
                      class="group-chat-workspace-item-btn group-chat-workspace-item-btn-main"
                      :class="{ 'group-chat-workspace-item-selected': groupWorkspacePreviewPath === e.path }"
                      :disabled="groupWorkspaceUploading"
                      @click="previewWorkspaceFile(e)"
                    >
                      <span class="group-chat-workspace-svg group-chat-workspace-icon-mask" :style="workspaceIconStyle(fileIconUrl)" aria-hidden="true" />
                      <span class="truncate" :title="e.name">{{ e.name }}</span>
                    </button>
                    <div class="group-chat-workspace-item-actions">
                      <button
                        v-if="!e.is_dir"
                        type="button"
                        class="group-chat-workspace-item-action"
                        title="下载"
                        aria-label="下载"
                        :disabled="groupWorkspaceUploading"
                        @click.stop="downloadGroupWorkspaceFile(e)"
                      >
                        <span class="group-chat-workspace-action-icon group-chat-workspace-icon-mask" :style="workspaceIconStyle(downloadIconUrl)" aria-hidden="true" />
                      </button>
                      <button
                        v-if="!e.is_dir"
                        type="button"
                        class="group-chat-workspace-item-action"
                        title="重命名"
                        aria-label="重命名"
                        :disabled="groupWorkspaceUploading"
                        @click.stop="renameGroupWorkspaceEntry(e)"
                      >
                        <span class="group-chat-workspace-action-icon group-chat-workspace-icon-mask" :style="workspaceIconStyle(renameIconUrl)" aria-hidden="true" />
                      </button>
                      <button
                        type="button"
                        class="group-chat-workspace-item-action group-chat-workspace-item-action-danger"
                        :title="e.is_dir ? '删除空目录' : '删除文件'"
                        :aria-label="e.is_dir ? '删除空目录' : '删除文件'"
                        :disabled="groupWorkspaceUploading"
                        @click.stop="deleteGroupWorkspaceEntry(e)"
                      >
                        <span class="group-chat-workspace-action-icon group-chat-workspace-icon-mask" :style="workspaceIconStyle(deleteIconUrl)" aria-hidden="true" />
                      </button>
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
                  <span class="group-chat-workspace-preview-title" :title="groupWorkspacePreviewName">{{ groupWorkspacePreviewName }}</span>
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
                <div
                  v-else-if="groupWorkspacePreviewIsMarkdown"
                  class="group-chat-workspace-preview-content group-chat-workspace-preview-markdown"
                  v-html="groupWorkspacePreviewMarkdownHtml"
                />
                <pre v-else class="group-chat-workspace-preview-content">{{ groupWorkspacePreviewContent }}</pre>
              </div>
              <div v-else class="group-chat-workspace-preview-placeholder">选择左侧文件以预览</div>
              </div>
            </div>
          </aside>
</template>

<script setup lang="ts">
import { useGroupChatWorkspacePanelContext } from './groupChatWorkspaceContext'
import { workspaceIconStyle } from '../../workspaceIconStyle'
import deleteIconUrl from '@/assets/icons/workspace/delete.svg'
import downloadIconUrl from '@/assets/icons/workspace/download.svg'
import newFileIconUrl from '@/assets/icons/workspace/new-file.svg'
import newFolderIconUrl from '@/assets/icons/workspace/new-folder.svg'
import fileIconUrl from '@/assets/icons/workspace/file.svg'
import folderIconUrl from '@/assets/icons/workspace/folder.svg'
import previewIconUrl from '@/assets/icons/workspace/preview.svg'
import refreshIconUrl from '@/assets/icons/workspace/refresh.svg'
import renameIconUrl from '@/assets/icons/workspace/rename.svg'
import uploadIconUrl from '@/assets/icons/workspace/upload.svg'

const {
  showGroupWorkspace,
  onGroupWorkspaceResizeMouseDown,
  groupWorkspaceWidth,
  groupWorkspacePath,
  loadGroupWorkspace,
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
  groupWorkspacePreviewIsMarkdown,
  groupWorkspacePreviewMarkdownHtml,
  groupWorkspacePreviewImageUrl,
  groupWorkspacePreviewContent,
} = useGroupChatWorkspacePanelContext()
</script>
