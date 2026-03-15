<template>
  <div class="workspace-pane flex flex-col flex-1 min-h-0 bg-page">
    <header class="bg-card px-4 py-2.5 flex items-center justify-between gap-3 flex-shrink-0">
      <h1 class="text-lg font-semibold text-primary truncate min-w-0">{{ sessionTitle || '群聊' }}</h1>
      <div class="flex items-center gap-2 flex-shrink-0">
        <button
          type="button"
          :class="[
            'flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-medium rounded-lg border transition-colors',
            showWorkspaceViewer ? 'border-accent bg-accent-subtle text-accent-subtle-text' : 'border-input-border text-muted hover:bg-list-hover'
          ]"
          @click="toggleWorkspaceViewer"
        >
          工作区
        </button>
        <button
          type="button"
          class="flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-medium rounded-lg border border-input-border text-muted hover:bg-list-hover"
          @click="showInviteDha = true"
          :title="sessionMembers.length ? `当前 ${sessionMembers.length} 名成员，点击查看并邀请更多` : '查看成员并邀请 DHA'"
        >
          成员与邀请
          <span v-if="sessionMembers.length" class="text-[10px] text-muted">({{ sessionMembers.length }})</span>
        </button>
      </div>
    </header>

    <!-- 消息列表 + 工作区侧栏：用 displayedMessages 保证顺序与逐条出现 -->
    <div class="flex-1 min-h-0 flex">
      <!-- 左侧：消息 -->
      <div ref="messagesContainerRef" class="flex-1 overflow-y-auto px-6 sm:px-8 py-6 space-y-6">
        <template v-for="(msg, index) in displayedMessages" :key="msg.message_id || index">
          <div
            :data-message-index="index"
            :class="['flex', msg.role === 'user' ? 'justify-end' : 'justify-start']"
          >
            <!-- 用户消息 -->
            <div
              v-if="msg.role === 'user'"
              class="max-w-3xl min-w-0 rounded-lg px-4 py-2 bg-user-bubble text-text-inverse shadow-sm"
            >
              <div class="chat-markdown-wrap break-words min-w-0 overflow-hidden">
                <div class="chat-markdown whitespace-pre-wrap" v-html="renderMarkdown(stripDiscussionGoalForDisplay(msg.content || ''))"></div>
              </div>
            </div>
            <!-- 主持人消息（灰色标签，先于 DHA 发言出现） -->
            <div
              v-else-if="msg.role === 'host'"
              class="max-w-3xl min-w-0 w-full flex flex-col items-center gap-2"
            >
              <div class="text-xs text-muted italic px-3 py-1.5 bg-list-hover rounded-full">
                {{ msg.content || '' }}
              </div>
              <div v-if="msg.next_prompt" class="w-full max-w-2xl">
                <details class="text-xs border border-border rounded-lg bg-card overflow-hidden">
                  <summary class="px-3 py-2 cursor-pointer hover:bg-list-hover text-muted">{{ (msg.next_dha_name || '下一 DHA') }} 的提示词</summary>
                  <pre class="p-3 m-0 text-primary whitespace-pre-wrap break-words font-mono bg-list-hover border-t border-border-light max-h-60 overflow-auto">{{ msg.next_prompt }}</pre>
                </details>
              </div>
            </div>
            <!-- DHA 消息：头像（首字）+ 名称 + 简介 + 输出框 -->
            <div
              v-else
              class="max-w-3xl min-w-0 w-full flex gap-2"
            >
              <div class="flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center text-sm font-semibold text-text-inverse"
                :style="{ backgroundColor: getDhaAvatarBg(msg.dha_id) }"
              >
                {{ getDhaAvatarChar(msg.dha_id) }}
              </div>
              <div class="min-w-0 flex-1">
              <div class="mb-1.5 flex items-center gap-2 flex-wrap">
                <span class="font-semibold text-primary">{{ getDhaName(msg.dha_id) }}</span>
                <span v-if="msg.timestamp" class="text-xs text-muted">{{ formatMsgTime(msg.timestamp) }}</span>
                <span v-if="leaderDhaId && msg.dha_id === leaderDhaId" class="text-xs px-1.5 py-0.5 rounded bg-accent-subtle text-accent-subtle-text">主持人</span>
                <span v-if="getDhaRole(msg.dha_id)" class="text-xs text-muted">{{ getDhaRole(msg.dha_id) }}</span>
              </div>
              <div
                :style="getDhaBoxStyle(msg.dha_id)"
                class="rounded-lg px-4 py-3 border-l-4"
              >
                <div
                  v-if="msg.role === 'assistant'"
                  class="mb-2 text-xs text-skill font-medium flex items-center justify-between gap-2 flex-wrap"
                >
                  <span>skill: {{ getDhaSkillLabel(msg.dha_id, msg) }}</span>
                  <button
                    type="button"
                    class="px-2 py-0.5 text-[11px] border border-border rounded text-muted hover:bg-list-hover"
                    @click="saveMessageAsFile(msg)"
                  >
                    保存为文件
                  </button>
                </div>
                <div v-if="msg.role === 'assistant' && extractToolCalls(msg.content || '').toolCalls.length">
                  <div
                    v-for="(tc, tcIdx) in extractToolCalls(msg.content || '').toolCalls"
                    :key="tcIdx"
                    class="mb-2 rounded-r-md border-l-4 border-l-tool-call-border bg-tool-call-bg border border-tool-call-border px-3 py-2 text-xs text-primary font-mono cursor-pointer hover:opacity-90 transition-opacity"
                    :title="(msg.tool_raw_results && msg.tool_raw_results[tcIdx] !== undefined) ? '点击查看原始输出' : ''"
                    @click="(msg.tool_raw_results && msg.tool_raw_results[tcIdx] !== undefined) && openRawModal(msg.tool_raw_results[tcIdx], getToolNameFromToolCall(tc) + ' 原始输出')"
                  >
                    <div class="flex items-center justify-between gap-2 mb-1">
                      <span class="text-tool-call-text font-sans font-medium">{{ getToolNameFromToolCall(tc) }}</span>
                      <button
                        v-if="msg.tool_raw_results && msg.tool_raw_results[tcIdx] !== undefined"
                        type="button"
                        class="shrink-0 text-accent hover:opacity-80 hover:underline"
                        @click.stop="openRawModal(msg.tool_raw_results[tcIdx], getToolNameFromToolCall(tc) + ' 原始输出')"
                      >
                        原始输出
                      </button>
                    </div>
                    <pre class="m-0 overflow-x-auto max-h-40 overflow-y-auto break-all whitespace-pre-wrap">{{ tc }}</pre>
                  </div>
                </div>
                <div class="chat-markdown-wrap break-words min-w-0 overflow-hidden">
                  <template
                    v-for="(seg, segIdx) in parseMessageContent(extractToolCalls(msg.content || '').rest)"
                    :key="segIdx"
                  >
                    <div v-if="seg.type === 'text'" class="chat-markdown" v-html="renderMarkdown(seg.text)" />
                    <a v-else :href="seg.url" target="_blank" rel="noreferrer" class="block mt-2">
                      <img :src="seg.url" :alt="seg.alt || 'image'" loading="lazy" class="max-w-full rounded-md border border-border" />
                    </a>
                  </template>
                </div>
                <div v-if="msg.next_prompt" class="mt-3 w-full">
                  <details class="text-xs border border-border rounded-lg bg-card overflow-hidden">
                    <summary class="px-3 py-2 cursor-pointer hover:bg-list-hover text-muted">{{ (msg.next_dha_name || '下一 DHA') }} 的提示词</summary>
                    <pre class="p-3 m-0 text-primary whitespace-pre-wrap break-words font-mono bg-list-hover border-t border-border-light max-h-60 overflow-auto">{{ msg.next_prompt }}</pre>
                  </details>
                </div>
              </div>
              </div>
            </div>
          </div>
        </template>

        <!-- 生成中：内容生成结束后一次性输出 -->
        <!-- 单一动态加载：显示当前环节 -->
        <div v-if="isStreaming" class="flex justify-start">
          <div class="max-w-3xl min-w-0 rounded-lg px-4 py-2.5 bg-card border border-border flex items-center gap-2">
            <span class="text-sm text-muted">{{ streamingPhase || '正在加载…' }}</span>
            <span class="flex gap-1">
              <span class="thinking-dot w-2 h-2 bg-loading-dot rounded-full" style="animation-delay: 0ms"></span>
              <span class="thinking-dot w-2 h-2 bg-loading-dot rounded-full" style="animation-delay: 160ms"></span>
              <span class="thinking-dot w-2 h-2 bg-loading-dot rounded-full" style="animation-delay: 320ms"></span>
            </span>
          </div>
        </div>
      </div>

      <!-- 中间：拖拽分隔条（调整消息区与工作区宽度） -->
      <div
        v-if="showWorkspaceViewer"
        class="w-1 cursor-col-resize bg-transparent hover:bg-border"
        @mousedown="startResizeMain"
      ></div>
      <!-- 右侧：工作区侧栏（简洁文件管理器风格） -->
      <div
        v-if="showWorkspaceViewer"
        class="bg-sidebar-list flex flex-col"
        :style="{ width: `${workspaceWidth}px`, minWidth: '320px', maxWidth: '640px' }"
      >
        <div class="h-9 px-3 flex items-center justify-between bg-section-header flex-shrink-0">
          <span class="text-[13px] font-medium text-primary">工作区</span>
          <button class="p-1 rounded text-muted hover:text-primary hover:bg-list-hover" title="关闭" @click="closeWorkspaceViewer" aria-label="关闭">×</button>
        </div>
        <div class="px-2 py-1.5 bg-card flex items-center gap-1 flex-wrap flex-shrink-0">
          <button type="button" :disabled="!workspacePath" class="p-1.5 rounded text-muted hover:bg-list-hover hover:text-primary disabled:opacity-40 disabled:pointer-events-none" title="上一级" @click="workspaceGoUp">↑</button>
          <span class="text-[11px] text-muted font-mono truncate max-w-[120px]" :title="workspacePath || '根目录'">{{ workspacePath || '/' }}</span>
          <div class="flex-1 min-w-0" />
          <button type="button" class="p-1.5 rounded text-muted hover:bg-list-hover hover:text-primary" title="刷新" @click="loadWorkspaceEntries(workspacePath)">↻</button>
          <button type="button" class="p-1.5 rounded text-muted hover:bg-list-hover hover:text-primary" title="新建文件夹" @click="createWorkspaceDir">⊕</button>
          <button type="button" class="p-1.5 rounded text-muted hover:bg-list-hover hover:text-primary" title="新建文件" @click="createWorkspaceTextFile">+</button>
          <button type="button" class="p-1.5 rounded text-muted hover:bg-list-hover hover:text-primary" title="上传文件" @click="triggerWorkspaceUpload">↑</button>
          <button type="button" :disabled="!workspaceSelectedEntry || workspaceSelectedEntry.is_dir" class="p-1.5 rounded text-muted hover:bg-list-hover hover:text-primary disabled:opacity-40 disabled:pointer-events-none" title="重命名（仅文件）" @click="renameWorkspaceEntry">R</button>
          <button type="button" :disabled="!workspaceSelectedEntry" class="p-1.5 rounded text-muted hover:bg-danger-subtle hover:text-danger disabled:opacity-40 disabled:pointer-events-none" title="删除（空目录也可删）" @click="deleteWorkspaceFile">−</button>
          <input ref="workspaceUploadInputRef" type="file" class="hidden" @change="onWorkspaceUpload" />
        </div>
        <div v-if="workspaceLoading" class="px-3 py-2 text-[11px] text-muted">加载中...</div>
        <div v-else-if="workspaceError" class="px-3 py-2 text-[11px] text-danger truncate">{{ workspaceError }}</div>
        <div class="flex-1 min-h-0 flex min-w-0">
          <div class="w-40 min-w-[140px] max-w-[200px] bg-card overflow-y-auto flex-shrink-0">
            <div v-if="!workspaceEntries.length && !workspaceLoading" class="px-3 py-6 text-[11px] text-muted text-center">当前目录为空</div>
            <div v-else class="py-0.5">
              <button
                v-for="e in workspaceEntries"
                :key="e.path"
                type="button"
                class="w-full text-left flex items-center gap-2 px-2 py-1.5 rounded-none text-[12px] transition-colors"
                :class="workspaceSelectedEntry?.path === e.path ? 'bg-accent-subtle/80 text-accent-subtle-text' : 'text-primary hover:bg-list-hover'"
                @click="onWorkspaceEntryClick(e)"
              >
                <span class="flex-shrink-0 w-4 text-center text-muted font-mono text-xs">{{ e.is_dir ? '▾' : '·' }}</span>
                <span class="truncate">{{ e.name }}</span>
              </button>
            </div>
          </div>
          <!-- 右侧：文件内容预览 -->
          <div class="flex-1 min-w-0 flex flex-col">
            <div class="px-3 py-2 bg-section-header flex items-center justify-between gap-2 flex-shrink-0">
              <span class="text-[11px] text-muted truncate">{{ workspaceSelectedEntry ? workspaceSelectedEntry.name : '选择文件预览' }}</span>
              <div v-if="workspaceSelectedEntry && !workspaceSelectedEntry.is_dir" class="flex items-center gap-2">
                <a
                  :href="`/api/workspaces/${encodeURIComponent(groupSessionId)}/files/download?path=${encodeURIComponent(workspaceSelectedEntry.path)}`"
                  target="_blank"
                  rel="noreferrer"
                  class="px-2 py-1 text-[11px] border border-input-border rounded text-muted hover:bg-list-hover"
                >新标签打开</a>
                <template v-if="workspaceSelectedIsText">
                  <button v-if="!workspaceEditing" class="px-1.5 py-0.5 text-[10px] text-muted hover:text-accent" @click="startWorkspaceEdit">编辑</button>
                  <template v-else>
                  <button
                    class="px-2 py-1 text-[11px] border border-accent text-accent rounded hover:bg-accent-subtle"
                    @click="saveWorkspaceEdit"
                  >
                    保存
                  </button>
                  <button
                    class="px-2 py-1 text-[11px] border border-input-border text-muted rounded hover:bg-list-hover"
                    @click="cancelWorkspaceEdit"
                  >
                    取消
                  </button>
                  </template>
                </template>
              </div>
            </div>
            <div class="flex-1 min-h-0 overflow-auto p-3 bg-list-hover">
              <div v-if="workspaceFileLoading && !workspaceSelectedIsImage" class="text-[11px] text-muted">加载中...</div>
              <div v-else-if="workspaceFileError" class="text-[11px] text-danger">{{ workspaceFileError }}</div>
              <div v-else-if="workspaceEditing && workspaceSelectedIsText" class="h-full">
                <textarea v-model="workspaceEditContent" class="w-full h-full min-h-[120px] text-[12px] text-primary whitespace-pre-wrap break-words font-mono border border-border rounded p-2 resize-none focus:outline-none focus:ring-1 focus:ring-input-focus-ring" spellcheck="false" />
              </div>
              <img v-else-if="workspaceSelectedEntry && workspaceSelectedIsImage" :src="workspacePreviewDownloadUrl" :alt="workspaceSelectedEntry.name" class="max-w-full h-auto rounded" />
              <div v-else-if="workspaceSelectedIsDocx" class="min-h-0 flex flex-col">
                <div v-if="workspaceFileLoading" class="text-[11px] text-muted py-4">加载中...</div>
                <div v-else-if="workspaceDocxError" class="text-[11px] text-danger py-2">{{ workspaceDocxError }}</div>
                <div v-show="!workspaceFileLoading && !workspaceDocxError" ref="workspaceDocxContainerRef" class="docx-preview overflow-auto text-left" />
              </div>
              <pre v-else-if="workspaceFileContent" class="text-[12px] text-primary whitespace-pre-wrap break-words font-mono m-0">{{ workspaceFileContent }}</pre>
              <div v-else class="text-[11px] text-muted">选择左侧文件以预览</div>
            </div>
          </div>
        </div>
      </div>
    </div>
    <!-- 纵向拖拽条：调整消息区与输入区高度 -->
    <div
      class="h-1 cursor-row-resize bg-transparent hover:bg-border flex-shrink-0"
      @mousedown="startResizeInput"
    ></div>
    <!-- 输入区：任务流程步进器 + 多输入框 + 下一发言人单选卡片 + 确认 -->
    <div
      class="bg-card flex-shrink-0 flex flex-col overflow-hidden"
      :style="{ height: `${inputAreaHeight}px`, minHeight: '160px', maxHeight: '420px' }"
    >
      <!-- 任务规划 / DHA 运行顺序（步进器） -->
      <div v-if="!isSingleDha && (flowSteps.length || suggestedOrderFromHost.length)" class="flex-shrink-0 px-4 pt-2 pb-1 bg-sidebar-list">
        <div class="text-[11px] font-medium text-muted uppercase tracking-wide mb-1.5">任务流程</div>
        <div class="flex items-center gap-0 overflow-x-auto pb-1">
          <template v-for="(step, idx) in flowSteps" :key="step.id + '-' + idx">
            <div
              :class="[
                'flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border transition-all shrink-0',
                step.state === 'done' && 'bg-emerald-50 border-emerald-200 text-emerald-800',
                step.state === 'current' && 'bg-accent-subtle border-accent ring-1 ring-accent text-accent-subtle-text',
                step.state === 'upcoming' && 'bg-list-hover border-border text-muted',
              ]"
            >
              <span v-if="step.state === 'done'" class="text-emerald-600">✓</span>
              <span v-else class="w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-semibold" :style="step.id === 'user' ? {} : { backgroundColor: getDhaAvatarBg(step.id), color: 'white' }">{{ step.id === 'user' ? '我' : getDhaAvatarChar(step.id) }}</span>
              <span class="text-xs font-medium max-w-[80px] truncate">{{ step.label }}</span>
            </div>
            <span v-if="idx < flowSteps.length - 1" class="text-placeholder shrink-0">→</span>
          </template>
        </div>
      </div>

      <!-- 输入区：宽度 90% 最大 1400px，左右 20px 内边距；下一发言人等已在输入框内 -->
      <div class="group-chat-input-outer flex-1 flex flex-col gap-2 min-h-0 overflow-auto relative">
        <!-- 主持人建议邀请（0 成员时）：同意并邀请 / 忽略 -->
        <div v-if="suggestedAddDhaIds.length && !isStreaming" class="flex items-center gap-3 px-4 py-2 rounded-lg bg-accent-subtle/50 border border-accent/30 text-sm">
          <span class="text-muted">主持人建议邀请 {{ suggestedAddDhaName }} 加入讨论</span>
          <button type="button" class="px-3 py-1.5 rounded-lg bg-accent text-text-inverse font-medium hover:opacity-90" @click="inviteSuggestedDha">同意并邀请</button>
          <button type="button" class="px-2 py-1 rounded text-muted hover:bg-list-hover" @click="suggestedAddDhaIds = []">忽略</button>
        </div>
        <!-- 默认单输入框：圆角容器内 = 输入区 + 功能按钮行 + 下一发言人/发送 -->
        <div v-if="!showExtendedInputs" class="group-chat-input-box flex flex-col min-h-0 flex-1">
          <div class="group-chat-input-area flex-1 min-h-0 flex flex-col">
            <textarea
              :value="singleInputValue"
              @input="singleInputValue = ($event.target as HTMLTextAreaElement).value"
              placeholder="按 Cmd+空格 发送"
              rows="3"
              class="flex-1 min-h-[60px] w-full border-0 bg-transparent px-4 py-3 text-sm text-primary placeholder:text-muted focus:ring-0 focus:outline-none resize-none"
              :disabled="isStreaming"
              @keydown="onChatInputKeydown"
            />
          </div>
          <div class="group-chat-input-btn-row flex items-center flex-wrap gap-2 px-4 pb-3 pt-1">
            <button type="button" class="group-chat-func-btn" title="插入文件" @click="openFilePicker">插入文件</button>
            <button type="button" class="group-chat-func-btn" @click="showMoreMenu = !showMoreMenu">更多</button>
          </div>
          <!-- 下一发言人 + 发送：移入输入框内 -->
          <div v-if="!isSingleDha" class="group-chat-input-footer flex flex-wrap items-center gap-2 px-4 pb-3 pt-1 border-t border-border-light">
            <span class="text-[11px] text-muted">下一发言人</span>
            <div class="flex flex-wrap gap-1.5">
              <label
                v-for="opt in nextSpeakerOptions"
                :key="opt.value"
                :class="[
                  'inline-flex items-center gap-2 px-3 py-2 rounded-[16px] border-2 cursor-pointer transition-all',
                  overrideNextSpeaker === opt.value
                    ? 'border-accent bg-accent-subtle text-accent-subtle-text shadow-sm'
                    : 'border-border bg-card text-primary hover:border-input-border hover:bg-list-hover',
                ]"
              >
                <input type="radio" :value="opt.value" v-model="overrideNextSpeaker" class="sr-only" :disabled="speakMode === 'auto'" />
                <span class="w-6 h-6 rounded-full flex items-center justify-center text-xs font-semibold text-text-inverse shrink-0" :style="opt.value === 'user' ? { backgroundColor: '#64748b' } : { backgroundColor: getDhaAvatarBg(opt.value) }">{{ opt.value === 'user' ? '我' : getDhaAvatarChar(opt.value) }}</span>
                <span class="text-sm font-medium">{{ opt.label }}</span>
              </label>
            </div>
            <button
              type="button"
              class="px-4 py-2 bg-accent text-text-inverse rounded-[16px] text-sm font-medium hover:bg-accent-hover disabled:opacity-50 disabled:cursor-not-allowed shadow-sm"
              :disabled="isStreaming || (!canSend && speakMode !== 'auto')"
              @click="sendMessage"
              title="Cmd+空格"
            >
              {{ overrideNextSpeaker ? '确认并继续' : '发送' }}
            </button>
          </div>
          <div v-else class="group-chat-input-footer flex justify-end px-4 pb-3 pt-1 border-t border-border-light">
            <button
              type="button"
              class="px-4 py-2 bg-accent text-text-inverse rounded-[16px] text-sm font-medium hover:bg-accent-hover disabled:opacity-50 disabled:cursor-not-allowed"
              :disabled="isStreaming || !inputText.trim()"
              @click="sendMessage"
            >
              发送
            </button>
          </div>
        </div>
        <!-- 扩展输入框（更多 -> 显示讨论目标/最近讨论/下一 DHA 提示词），同样放入圆角容器并带下一发言人+发送 -->
        <div v-else class="group-chat-input-box flex flex-col min-h-0 flex-1">
          <div class="grid grid-cols-1 md:grid-cols-3 gap-2 min-h-0 flex-1 p-4">
            <div class="flex flex-col min-h-0">
              <label class="text-[11px] font-medium text-muted mb-0.5 flex items-center gap-1">
                输入消息
                <button type="button" class="p-0.5 rounded text-muted hover:bg-border hover:text-muted" title="插入文件" @click="openFilePickerForGoal">⊕</button>
              </label>
              <textarea
                v-model="discussionGoalText"
                placeholder="输入本场讨论要达成的目标…"
                rows="2"
                class="flex-1 min-h-[44px] w-full border border-border rounded-[16px] px-2.5 py-1.5 text-sm resize-none focus:ring-2 focus:ring-input-focus-ring focus:border-input-focus-ring placeholder:text-muted"
                :disabled="isStreaming"
              />
            </div>
            <div class="flex flex-col min-h-0">
              <label class="text-[11px] font-medium text-muted mb-0.5">最近讨论</label>
              <textarea
                v-model="recentDiscussionText"
                placeholder="由消息自动生成，可编辑补充或修正…"
                rows="2"
                class="flex-1 min-h-[44px] w-full border border-border rounded-[16px] px-2.5 py-1.5 text-sm bg-list-hover text-primary overflow-auto resize-none placeholder:text-muted focus:ring-2 focus:ring-primary focus:border-primary"
                :disabled="isStreaming"
              />
            </div>
            <div class="flex flex-col min-h-0">
              <label class="text-[11px] font-medium text-muted mb-0.5 flex items-center gap-1">
                下一 DHA 提示词
                <button type="button" class="p-0.5 rounded text-muted hover:bg-border hover:text-muted" title="插入文件" @click="openFilePicker">⊕</button>
                <button v-if="speakMode === 'manual' && overrideNextSpeaker && overrideNextSpeaker !== 'user'" type="button" class="ml-1 text-[10px] text-accent hover:underline" @click="openPromptEditor">从预览加载</button>
              </label>
              <textarea
                v-model="inputText"
                placeholder="每次 DHA 发言前自动填充本轮提示词，可编辑后点「确认并继续」"
                rows="2"
                class="flex-1 min-h-[44px] w-full border border-border rounded-[16px] px-2.5 py-1.5 text-sm resize-none focus:ring-2 focus:ring-input-focus-ring focus:border-input-focus-ring placeholder:text-muted"
                :disabled="isStreaming"
                @keydown="onChatInputKeydown"
              />
            </div>
          </div>
          <div v-if="!isSingleDha" class="group-chat-input-footer flex flex-wrap items-center gap-2 px-4 pb-3 pt-1 border-t border-border-light">
            <span class="text-[11px] text-muted">下一发言人</span>
            <div class="flex flex-wrap gap-1.5">
              <label
                v-for="opt in nextSpeakerOptions"
                :key="opt.value"
                :class="[
                  'inline-flex items-center gap-2 px-3 py-2 rounded-[16px] border-2 cursor-pointer transition-all',
                  overrideNextSpeaker === opt.value
                    ? 'border-accent bg-accent-subtle text-accent-subtle-text shadow-sm'
                    : 'border-border bg-card text-primary hover:border-input-border hover:bg-list-hover',
                ]"
              >
                <input type="radio" :value="opt.value" v-model="overrideNextSpeaker" class="sr-only" :disabled="speakMode === 'auto'" />
                <span class="w-6 h-6 rounded-full flex items-center justify-center text-xs font-semibold text-text-inverse shrink-0" :style="opt.value === 'user' ? { backgroundColor: '#64748b' } : { backgroundColor: getDhaAvatarBg(opt.value) }">{{ opt.value === 'user' ? '我' : getDhaAvatarChar(opt.value) }}</span>
                <span class="text-sm font-medium">{{ opt.label }}</span>
              </label>
            </div>
            <button
              type="button"
              class="px-4 py-2 bg-accent text-text-inverse rounded-[16px] text-sm font-medium hover:bg-accent-hover disabled:opacity-50 disabled:cursor-not-allowed shadow-sm"
              :disabled="isStreaming || (!canSend && speakMode !== 'auto')"
              @click="sendMessage"
              title="Cmd+空格"
            >
              {{ overrideNextSpeaker ? '确认并继续' : '发送' }}
            </button>
          </div>
          <div v-else class="group-chat-input-footer flex justify-end px-4 pb-3 pt-1 border-t border-border-light">
            <button
              type="button"
              class="px-4 py-2 bg-accent text-text-inverse rounded-[16px] text-sm font-medium hover:bg-accent-hover disabled:opacity-50 disabled:cursor-not-allowed"
              :disabled="isStreaming || !inputText.trim()"
              @click="sendMessage"
            >
              发送
            </button>
          </div>
        </div>

        <!-- 更多下拉：显示扩展输入框、自动确认、增删成员 -->
        <div v-if="showMoreMenu" class="absolute left-4 right-4 md:right-auto md:w-56 bg-card border border-border rounded-lg shadow-lg py-2 z-20">
          <label class="flex items-center gap-2 px-3 py-1.5 hover:bg-list-hover cursor-pointer text-sm">
            <input type="checkbox" v-model="showExtendedInputs" class="rounded border-input-border text-accent focus:ring-input-focus-ring" />
            <span>显示消息区 / 最近讨论 / 下一 DHA 提示词</span>
          </label>
          <label class="flex items-center gap-2 px-3 py-1.5 hover:bg-list-hover cursor-pointer text-sm">
            <input type="checkbox" :checked="speakMode === 'auto'" class="rounded border-input-border text-accent focus:ring-input-focus-ring" @change="onAutoSwitchChange" />
            <span>自动确认</span>
          </label>
          <button type="button" class="w-full text-left px-3 py-1.5 hover:bg-list-hover text-sm" @click="showInviteDha = true; showMoreMenu = false">
            增删成员
          </button>
        </div>
      </div>
    </div>

    <!-- 文件选择弹窗（与 Chat 同款样式） -->
    <div
      v-if="showFilePicker"
      class="fixed inset-0 bg-black/30 flex items-center justify-center p-4 z-50"
      @click.self="closeFilePicker"
    >
      <div class="bg-card w-full max-w-2xl rounded-lg shadow-lg border border-border overflow-hidden">
        <div class="px-4 py-3 border-b border-border flex items-center justify-between gap-2">
          <div class="text-sm font-semibold text-primary truncate">
            选择要插入到输入框的文件（当前目录：{{ filePickerPath || '/' }}）
          </div>
          <button class="text-sm text-muted hover:text-primary" title="关闭" @click="closeFilePicker">关闭</button>
        </div>
        <div class="px-4 py-2 border-b border-border-light flex items-center gap-2">
          <button
            class="px-2 py-1 text-sm border border-input-border rounded hover:bg-list-hover disabled:opacity-50"
            :disabled="!filePickerPath"
            title="上一级"
            @click="filePickerGoUp"
          >
            ↑ 上一级
          </button>
          <button
            class="px-2 py-1 text-sm border border-input-border rounded hover:bg-list-hover"
            title="刷新列表"
            @click="loadFilePickerEntries(filePickerPath)"
          >
            刷新
          </button>
          <div v-if="filePickerLoading" class="text-xs text-muted">加载中...</div>
          <div v-else-if="filePickerError" class="text-xs text-red-600 truncate">{{ filePickerError }}</div>
        </div>
        <div class="max-h-[60vh] overflow-auto">
          <div v-if="!filePickerEntries.length && !filePickerLoading" class="px-4 py-6 text-sm text-muted">
            当前目录为空
          </div>
          <button
            v-for="e in filePickerEntries"
            :key="e.path"
            class="w-full text-left px-4 py-2.5 hover:bg-list-hover flex items-center gap-2 border-b border-border-light"
            :title="e.is_dir ? `进入目录：${e.name}` : `插入文件：${e.name}`"
            @click="onPickFileEntry(e)"
          >
            <span class="flex-shrink-0 text-muted font-mono">{{ e.is_dir ? '▾' : '·' }}</span>
            <span class="truncate">{{ e.name }}</span>
            <span v-if="!e.is_dir" class="ml-auto text-xs text-muted">插入</span>
          </button>
        </div>
      </div>
    </div>

    <!-- 工作区浏览弹窗（旧实现）已废弃，现改为右侧内嵌面板 -->

    <!-- 原始输出弹窗 -->
    <div
      v-if="rawModalVisible"
      class="fixed inset-0 bg-black/30 flex items-center justify-center p-4 z-50"
      @click.self="closeRawModal"
    >
      <div class="bg-card w-full max-w-2xl max-h-[80vh] rounded-lg shadow-lg border border-border flex flex-col overflow-hidden">
        <div class="px-4 py-3 border-b border-border flex items-center justify-between shrink-0">
          <span class="text-sm font-semibold text-primary">{{ rawModalTitle }}</span>
          <button class="text-muted hover:text-primary p-1" title="关闭" @click="closeRawModal" aria-label="关闭">×</button>
        </div>
        <pre class="flex-1 overflow-auto p-4 text-xs text-slate-700 whitespace-pre-wrap break-words font-mono bg-list-hover m-0">{{ rawModalContent }}</pre>
      </div>
    </div>

    <!-- 成员与邀请弹窗：当前成员 + 可邀请的 DHA（看到成员不够就可添加） -->
    <div
      v-if="showInviteDha"
      class="fixed inset-0 bg-black/30 flex items-center justify-center p-4 z-50"
      @click.self="showInviteDha = false"
    >
      <div class="bg-card w-full max-w-lg rounded-xl shadow-lg border border-border overflow-hidden flex flex-col max-h-[85vh]">
        <div class="px-4 py-3 border-b border-border flex items-center justify-between flex-shrink-0">
          <span class="text-sm font-semibold text-primary">成员与邀请</span>
          <button class="text-muted hover:text-primary p-1 rounded" title="关闭" @click="showInviteDha = false">×</button>
        </div>
        <div class="p-4 overflow-y-auto flex-1 min-h-0 space-y-4">
          <!-- 当前成员：谁是谁、干啥的 -->
          <section>
            <h3 class="text-xs font-medium text-muted uppercase tracking-wide mb-2">当前成员 ({{ sessionMembers.length }})</h3>
            <div v-if="!sessionMembers.length" class="text-sm text-muted py-2">暂无成员，可在下方邀请 DHA 加入。</div>
            <div v-else class="space-y-1.5">
              <div
                v-for="m in sessionMembers"
                :key="m.dha_id"
                class="flex items-center gap-3 py-2 px-3 rounded-lg bg-list-hover border border-border-light"
              >
                <div
                  class="w-8 h-8 rounded-full flex items-center justify-center text-sm font-semibold text-text-inverse flex-shrink-0"
                  :style="{ backgroundColor: getDhaAvatarBg(m.dha_id) }"
                >
                  {{ getDhaAvatarChar(m.dha_id) }}
                </div>
                <div class="min-w-0 flex-1">
                  <div class="font-medium text-primary truncate">{{ m.name }}</div>
                  <div v-if="m.role" class="text-xs text-muted truncate">{{ m.role }}</div>
                </div>
                <span v-if="m.isLeader" class="text-[10px] px-1.5 py-0.5 rounded bg-amber-100 text-amber-800 flex-shrink-0">主持</span>
              </div>
            </div>
          </section>
          <!-- 可邀请的 DHA：成员不够就点选添加 -->
          <section>
            <h3 class="text-xs font-medium text-muted uppercase tracking-wide mb-2">可邀请的 DHA</h3>
            <div v-if="!invitableDhas.length" class="text-sm text-muted py-2">暂无可邀请的 DHA，请在资源中心先创建 DHA。</div>
            <div v-else class="space-y-1.5">
              <label
                v-for="d in invitableDhas"
                :key="d.dha_id"
                class="flex items-center gap-3 cursor-pointer py-2 px-3 rounded-lg border transition-colors hover:bg-list-hover"
                :class="inviteSelectedIds.includes(d.dha_id) ? 'bg-accent-subtle/80 border-blue-200' : 'border-border-light hover:border-border'"
              >
                <input type="checkbox" :value="d.dha_id" v-model="inviteSelectedIds" class="rounded border-input-border text-accent focus:ring-input-focus-ring" />
                <div
                  class="w-8 h-8 rounded-full flex items-center justify-center text-sm font-semibold text-text-inverse flex-shrink-0"
                  :style="{ backgroundColor: getDhaAvatarBg(d.dha_id) }"
                >
                  {{ (d.name || d.dha_id).trim().charAt(0) || '?' }}
                </div>
                <div class="min-w-0 flex-1">
                  <div class="font-medium text-primary truncate">{{ d.name || d.dha_id }}</div>
                  <div v-if="d.role" class="text-xs text-muted truncate">{{ d.role }}</div>
                  <div v-else class="text-xs text-muted">未设置角色</div>
                </div>
              </label>
            </div>
          </section>
        </div>
        <div class="px-4 py-3 border-t border-border-light flex justify-end gap-2 flex-shrink-0">
          <button type="button" class="px-3 py-1.5 text-sm border border-input-border rounded-lg text-muted hover:bg-list-hover" @click="showInviteDha = false">
            关闭
          </button>
          <button
            type="button"
            class="px-3 py-1.5 text-sm bg-accent text-text-inverse rounded-lg hover:bg-accent-hover disabled:opacity-50"
            :disabled="!inviteSelectedIds.length"
            @click="confirmInviteDha"
          >
            邀请选中 ({{ inviteSelectedIds.length }})
          </button>
        </div>
      </div>
    </div>

    <!-- 下一发言人提示词编辑弹窗（manual 模式下使用） -->
    <div
      v-if="showPromptEditor"
      class="fixed inset-0 bg-black/30 flex items-center justify-center p-4 z-50"
      @click.self="closePromptEditor"
    >
      <div class="bg-card w-full max-w-2xl rounded-lg shadow-lg border border-border overflow-hidden">
        <div class="px-4 py-3 border-b border-border flex items-center justify-between gap-2">
          <div class="text-sm font-semibold text-primary truncate">
            下一发言人提示词（仅本轮有效）
          </div>
          <button class="text-sm text-muted hover:text-primary" @click="closePromptEditor">关闭</button>
        </div>
        <div class="p-4">
          <textarea
            v-model="promptEditorText"
            rows="10"
            class="w-full border border-input-border rounded-lg px-3 py-2 text-sm resize-y focus:ring-2 focus:ring-input-focus-ring focus:border-accent"
          />
          <p class="mt-2 text-xs text-muted">
            说明：这是发送给下一位 DHA 的完整文本提示词，你可以在 manual 模式下按需微调，仅对本轮生效。
          </p>
        </div>
        <div class="px-4 py-3 border-t border-border-light flex justify-end gap-2">
          <button
            type="button"
            class="px-3 py-1.5 text-sm border border-input-border rounded text-muted hover:bg-list-hover"
            @click="closePromptEditor"
          >
            取消
          </button>
          <button
            type="button"
            class="px-3 py-1.5 text-sm bg-accent text-text-inverse rounded hover:bg-accent-hover"
            @click="confirmPromptEditor"
          >
            使用此提示词
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick, onMounted } from 'vue'
// markdown-it / docx-preview 均按需动态导入，避免组件模块加载时即报错导致整块空白

const props = withDefaults(
  defineProps<{
    groupSessionId: string
    sessionTitle: string
    messages: { message_id?: string; role: string; dha_id?: string; content: string; timestamp?: string; tool_raw_results?: string[]; next_prompt?: string; next_dha_name?: string; suggested_order?: string[] }[]
    dhaMap?: Record<string, { name?: string; role?: string }>
    dhaIds: string[]
    allDhaInstances?: { dha_id: string; name: string; role?: string }[]
    leaderDhaId?: string
    speakMode?: string
    isSingleDha?: boolean
  }>(),
  { dhaMap: () => ({}), allDhaInstances: () => [], leaderDhaId: '', speakMode: 'auto', isSingleDha: false }
)

const emit = defineEmits<{
  (e: 'message-sent'): void
  (e: 'speak-mode-changed'): void
  (e: 'dha-added'): void
}>()

const inputText = ref('')
const discussionGoalText = ref('') // 与首条用户消息同步，可编辑
const recentDiscussionText = ref('') // 最近讨论，由消息自动生成并可编辑
const isStreaming = ref(false)
const streamingPhase = ref('')
const overrideNextSpeaker = ref('')
const customPrompt = ref('')
/** 自动模式下，主持人返回后待确认的下一发言人（在 stream 结束后触发一次发送） */
const pendingAutoConfirmSpeaker = ref<string | null>(null)
const messagesContainerRef = ref<HTMLElement | null>(null)
/** 用于逐条展示的消息列表：从 props 同步，请求完成后一次性更新 */
const displayedMessages = ref<{ message_id?: string; role: string; dha_id?: string; content: string; timestamp?: string; tool_raw_results?: string[]; next_prompt?: string; next_dha_name?: string; suggested_order?: string[] }[]>([])
const showFilePicker = ref(false)
// 工作区内的当前路径（相对 workspace 根目录，例如 ""、"notes"、"notes/sub"）
const filePickerPath = ref('')
const filePickerLoading = ref(false)
const filePickerError = ref('')
const filePickerEntries = ref<{ name: string; path: string; is_dir?: boolean }[]>([])
// 工作区浏览弹窗
const showWorkspaceViewer = ref(false)
const workspacePath = ref('')
const workspaceLoading = ref(false)
const workspaceError = ref('')
const workspaceEntries = ref<{ name: string; path: string; is_dir: boolean }[]>([])
const workspaceSelectedEntry = ref<{ name: string; path: string; is_dir: boolean } | null>(null)
const workspaceFileLoading = ref(false)
const workspaceFileError = ref('')
const workspaceFileContent = ref('')
const workspaceEditing = ref(false)
const workspaceEditContent = ref('')
const workspaceUploadInputRef = ref<HTMLInputElement | null>(null)
const workspaceWidth = ref(420) // 右侧工作区面板默认宽度（px），可拖拽调整
const inputAreaHeight = ref(140) // 底部输入区域高度（px）
const showPromptEditor = ref(false)
const promptEditorText = ref('')
const rawModalVisible = ref(false)
const rawModalTitle = ref('')
const rawModalContent = ref('')
function openRawModal(content: string, title: string) {
  rawModalTitle.value = title
  rawModalContent.value = content
  rawModalVisible.value = true
}
function closeRawModal() {
  rawModalVisible.value = false
}

const DHA_AVATAR_COLORS = [
  '#2563eb', '#059669', '#b45309', '#7c3aed', '#be123c', '#0891b2', '#0d9488', '#4f46e5',
]

function getDhaAvatarChar(dhaId: string) {
  const name = getDhaName(dhaId)
  if (!name) return '?'
  const first = name.trim().charAt(0)
  return first || dhaId?.charAt(0) || '?'
}

function getDhaAvatarBg(dhaId: string) {
  let hash = 0
  const s = dhaId || ''
  for (let i = 0; i < s.length; i++) {
    hash = ((hash << 5) - hash) + s.charCodeAt(i)
    hash |= 0
  }
  return DHA_AVATAR_COLORS[Math.abs(hash) % DHA_AVATAR_COLORS.length]
}

function openFilePicker() {
  filePickerTarget = 'prompt'
  showFilePicker.value = true
  filePickerError.value = ''
  loadFilePickerEntries('')
}

function closeFilePicker() {
  showFilePicker.value = false
}

async function loadFilePickerEntries(path: string) {
  filePickerLoading.value = true
  filePickerError.value = ''
  try {
    // 使用当前群聊对应的 workspace 文件接口
    const base = `/api/workspaces/${encodeURIComponent(props.groupSessionId)}/files`
    const url = path ? `${base}?path=${encodeURIComponent(path)}` : base
    const r = await fetch(url)
    const j = await r.json()
    if (j.status === 'ok' && j.data?.entries) {
      filePickerEntries.value = j.data.entries as { name: string; path: string; is_dir?: boolean }[]
      filePickerPath.value = path
    } else {
      filePickerEntries.value = []
      filePickerError.value = (j as { detail?: string }).detail || '加载失败'
    }
  } catch {
    filePickerEntries.value = []
    filePickerError.value = '加载失败'
  } finally {
    filePickerLoading.value = false
  }
}

function filePickerGoUp() {
  const p = filePickerPath.value.replace(/\/?[^/]+\/?$/, '').replace(/\/$/, '')
  loadFilePickerEntries(p)
}

let filePickerTarget: 'goal' | 'prompt' = 'prompt'
function openFilePickerForGoal() {
  filePickerTarget = 'goal'
  openFilePicker()
}
async function onPickFileEntry(e: { path: string; name: string; is_dir?: boolean }) {
  if (e.is_dir) {
    loadFilePickerEntries(e.path)
    return
  }
  const sid = props.groupSessionId
  if (!sid) return
  try {
    const r = await fetch(`/api/workspaces/${encodeURIComponent(sid)}/files/content?path=${encodeURIComponent(e.path)}`)
    const j = await r.json().catch(() => ({}))
    if (j?.status !== 'ok' || typeof j?.data?.content !== 'string') {
      alert((j as { detail?: string })?.detail || '读取文件内容失败')
      return
    }
    const text = (j.data.content as string).trim()
    const block = text ? `\n${text}\n` : ''
    if (filePickerTarget === 'goal') {
      discussionGoalText.value = (discussionGoalText.value || '') + (discussionGoalText.value?.trim() ? '\n\n' : '') + block
    } else {
      const sep = (inputText.value || '').trim() ? '\n\n' : ''
      inputText.value = (inputText.value || '').trim() + sep + block
      singleInputValue.value = (singleInputValue.value || '').trim() + sep + block
    }
    filePickerTarget = 'prompt'
    closeFilePicker()
  } catch {
    alert('读取文件失败，请检查网络')
  }
}

function openWorkspaceViewer() {
  showWorkspaceViewer.value = true
  workspaceError.value = ''
  workspacePath.value = ''
  loadWorkspaceEntries('')
}

function closeWorkspaceViewer() {
  showWorkspaceViewer.value = false
}

function toggleWorkspaceViewer() {
  if (showWorkspaceViewer.value) closeWorkspaceViewer()
  else openWorkspaceViewer()
}

async function loadWorkspaceEntries(path: string) {
  workspaceLoading.value = true
  workspaceError.value = ''
  try {
    const base = `/api/workspaces/${encodeURIComponent(props.groupSessionId)}/files`
    const url = path ? `${base}?path=${encodeURIComponent(path)}` : base
    const r = await fetch(url)
    const j = await r.json()
    if (j.status === 'ok' && j.data?.entries) {
      workspaceEntries.value = j.data.entries as { name: string; path: string; is_dir: boolean }[]
      workspacePath.value = path
      // 切换目录时重置选中与预览
      workspaceSelectedEntry.value = null
      workspaceFileContent.value = ''
      workspaceFileError.value = ''
    } else {
      workspaceEntries.value = []
      workspaceError.value = (j as { detail?: string }).detail || '加载失败'
    }
  } catch {
    workspaceEntries.value = []
    workspaceError.value = '加载失败'
  } finally {
    workspaceLoading.value = false
  }
}

function workspaceGoUp() {
  const p = workspacePath.value.replace(/\/?[^/]+\/?$/, '').replace(/\/$/, '')
  loadWorkspaceEntries(p)
}

function onWorkspaceEntryClick(e: { name: string; path: string; is_dir: boolean }) {
  if (e.is_dir) {
    loadWorkspaceEntries(e.path)
    return
  }
  workspaceEditing.value = false
  workspaceSelectedEntry.value = e
  loadWorkspaceFile(e)
}

function triggerWorkspaceUpload() {
  workspaceUploadInputRef.value?.click()
}

async function onWorkspaceUpload(ev: Event) {
  const input = ev.target as HTMLInputElement
  if (!input.files || !input.files.length) return
  const file = input.files[0]
  try {
    const form = new FormData()
    form.append('file', file)
    if (workspacePath.value) {
      form.append('path', workspacePath.value)
    }
    const url = `/api/workspaces/${encodeURIComponent(props.groupSessionId)}/files/upload${workspacePath.value ? `?path=${encodeURIComponent(workspacePath.value)}` : ''}`
    const r = await fetch(url, {
      method: 'POST',
      body: form,
    })
    const j = await r.json()
    if (j.status === 'ok') {
      await loadWorkspaceEntries(workspacePath.value)
    } else {
      alert((j as { detail?: string }).detail || '导入失败')
    }
  } catch {
    alert('导入失败，请检查网络或后端服务')
  } finally {
    if (input) {
      input.value = ''
    }
  }
}

async function createWorkspaceDir() {
  const name = window.prompt('新建文件夹名称', '新文件夹')
  if (!name || !name.trim()) return
  try {
    const body = { dirname: name.trim() }
    const base = `/api/workspaces/${encodeURIComponent(props.groupSessionId)}/files/mkdir`
    const url = workspacePath.value ? `${base}?path=${encodeURIComponent(workspacePath.value)}` : base
    const r = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    const j = await r.json()
    if (j.status === 'ok') {
      await loadWorkspaceEntries(workspacePath.value)
    } else {
      alert((j as { detail?: string }).detail || '新建文件夹失败')
    }
  } catch {
    alert('新建文件夹失败，请检查网络或后端服务')
  }
}

async function createWorkspaceTextFile() {
  const name = window.prompt('新建文件名（如 note.md）', 'note.md')
  if (!name || !name.trim()) return
  try {
    const body = { filename: name.trim(), content: '' }
    const base = `/api/workspaces/${encodeURIComponent(props.groupSessionId)}/files`
    const url = workspacePath.value ? `${base}?path=${encodeURIComponent(workspacePath.value)}` : base
    const r = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    const j = await r.json()
    if (j.status === 'ok') {
      await loadWorkspaceEntries(workspacePath.value)
    } else {
      alert((j as { detail?: string }).detail || '新建失败')
    }
  } catch {
    alert('新建失败，请检查网络或后端服务')
  }
}

async function renameWorkspaceEntry() {
  const entry = workspaceSelectedEntry.value
  if (!entry || entry.is_dir) return
  const name = window.prompt('重命名为', entry.name)
  if (name == null || name.trim() === '' || name.trim() === entry.name) return
  try {
    const r = await fetch(`/api/workspaces/${encodeURIComponent(props.groupSessionId)}/files/rename?path=${encodeURIComponent(entry.path)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ new_name: name.trim() }),
    })
    const j = await r.json()
    if (j.status === 'ok' && j.data?.path) {
      workspaceSelectedEntry.value = { name: name.trim(), path: j.data.path, is_dir: false }
      await loadWorkspaceEntries(workspacePath.value)
    } else {
      alert((j as { detail?: string }).detail || '重命名失败')
    }
  } catch {
    alert('重命名失败，请检查网络或后端服务')
  }
}

async function deleteWorkspaceFile() {
  const entry = workspaceSelectedEntry.value
  if (!entry) return
  const label = entry.is_dir ? `目录「${entry.name}」` : `文件「${entry.name}」`
  if (entry.is_dir) {
    if (!window.confirm(`确定要删除空目录 ${entry.name} 吗？非空目录请先清空内容。`)) return
  } else {
    if (!window.confirm(`确定要删除 ${label} 吗？此操作不可恢复。`)) return
  }
  try {
    const url = `/api/workspaces/${encodeURIComponent(props.groupSessionId)}/files/content?path=${encodeURIComponent(entry.path)}`
    const r = await fetch(url, { method: 'DELETE' })
    const j = await r.json()
    if (j.status === 'ok') {
      workspaceSelectedEntry.value = null
      workspaceFileContent.value = ''
      await loadWorkspaceEntries(workspacePath.value)
    } else {
      alert((j as { detail?: string }).detail || '删除失败')
    }
  } catch {
    alert('删除失败，请检查网络或后端服务')
  }
}

async function loadWorkspaceFile(e: { name: string; path: string; is_dir: boolean }) {
  workspaceFileLoading.value = true
  workspaceFileError.value = ''
  workspaceFileContent.value = ''
  workspaceDocxError.value = ''
  const url = `/api/workspaces/${encodeURIComponent(props.groupSessionId)}/files/download?path=${encodeURIComponent(e.path)}`
  const lower = e.name.toLowerCase()

  // 图片：仅需展示，无需请求内容
  if (imageExtensions.test(e.name)) {
    workspaceFileLoading.value = false
    return
  }

  // DOC/DOCX：拉取 blob 后用 docx-preview 渲染（按需动态导入）
  if (docxExtensions.test(e.name)) {
    try {
      const r = await fetch(url, { cache: 'no-store' })
      if (!r.ok) {
        workspaceFileError.value = '预览失败'
        return
      }
      const blob = await r.blob()
      await nextTick()
      const container = workspaceDocxContainerRef.value
      if (!container) {
        workspaceFileLoading.value = false
        return
      }
      container.innerHTML = ''
      const { renderAsync } = await import('docx-preview')
      await renderAsync(blob, container)
    } catch {
      workspaceDocxError.value = '预览失败，请下载查看'
    } finally {
      workspaceFileLoading.value = false
    }
    return
  }

  // 文本类：按文本拉取
  const textExts = ['.md', '.txt', '.json', '.yaml', '.yml', '.log', '.csv']
  const isText = textExts.some((ext) => lower.endsWith(ext))
  if (!isText) {
    workspaceFileContent.value = '该文件类型暂不支持在线预览，请点击「在新标签打开」查看。'
    workspaceFileLoading.value = false
    return
  }
  try {
    const r = await fetch(url, { cache: 'no-store' })
    if (!r.ok) {
      workspaceFileError.value = '预览失败'
      return
    }
    const t = await r.text()
    workspaceFileContent.value = t
  } catch {
    workspaceFileError.value = '预览失败'
  } finally {
    workspaceFileLoading.value = false
  }
}

const workspaceSelectedIsText = computed(() => {
  const e = workspaceSelectedEntry.value
  if (!e || e.is_dir) return false
  const lower = e.name.toLowerCase()
  const textExts = ['.md', '.txt', '.json', '.yaml', '.yml', '.log', '.csv']
  return textExts.some((ext) => lower.endsWith(ext))
})

const workspacePreviewDownloadUrl = computed(() => {
  const e = workspaceSelectedEntry.value
  if (!e || e.is_dir) return ''
  return `/api/workspaces/${encodeURIComponent(props.groupSessionId)}/files/download?path=${encodeURIComponent(e.path)}`
})
const imageExtensions = /\.(jpe?g|png|gif|webp|bmp|svg)$/i
const workspaceSelectedIsImage = computed(() => {
  const e = workspaceSelectedEntry.value
  return !!e && !e.is_dir && imageExtensions.test(e.name)
})
const docxExtensions = /\.docx?$/i
const workspaceSelectedIsDocx = computed(() => {
  const e = workspaceSelectedEntry.value
  return !!e && !e.is_dir && docxExtensions.test(e.name)
})

const workspaceDocxContainerRef = ref<HTMLElement | null>(null)
const workspaceDocxError = ref('')

function startWorkspaceEdit() {
  if (!workspaceSelectedIsText.value || !workspaceSelectedEntry.value) return
  workspaceEditContent.value = workspaceFileContent.value || ''
  workspaceEditing.value = true
}

async function saveWorkspaceEdit() {
  const entry = workspaceSelectedEntry.value
  if (!entry || !workspaceSelectedIsText.value) return
  try {
    const url = `/api/workspaces/${encodeURIComponent(props.groupSessionId)}/files/content?path=${encodeURIComponent(entry.path)}`
    const r = await fetch(url, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content: workspaceEditContent.value }),
    })
    const j = await r.json()
    if (j.status === 'ok') {
      workspaceFileContent.value = workspaceEditContent.value
      workspaceEditing.value = false
    } else {
      alert((j as { detail?: string }).detail || '保存失败')
    }
  } catch {
    alert('保存失败，请检查网络或后端服务')
  }
}

function cancelWorkspaceEdit() {
  workspaceEditing.value = false
  workspaceEditContent.value = workspaceFileContent.value || ''
}

// 横向拖拽：调整消息区与工作区宽度
function startResizeMain(ev: MouseEvent) {
  const startX = ev.clientX
  const startWidth = workspaceWidth.value
  const onMove = (e: MouseEvent) => {
    const delta = startX - e.clientX
    let next = startWidth + delta
    if (next < 260) next = 260
    if (next > 640) next = 640
    workspaceWidth.value = next
  }
  const onUp = () => {
    window.removeEventListener('mousemove', onMove)
    window.removeEventListener('mouseup', onUp)
  }
  window.addEventListener('mousemove', onMove)
  window.addEventListener('mouseup', onUp)
}

// 纵向拖拽：调整消息区与输入区高度
function startResizeInput(ev: MouseEvent) {
  const startY = ev.clientY
  const startHeight = inputAreaHeight.value
  const onMove = (e: MouseEvent) => {
    const delta = e.clientY - startY
    let next = startHeight - delta
    if (next < 96) next = 96
    if (next > 260) next = 260
    inputAreaHeight.value = next
  }
  const onUp = () => {
    window.removeEventListener('mousemove', onMove)
    window.removeEventListener('mouseup', onUp)
  }
  window.addEventListener('mousemove', onMove)
  window.addEventListener('mouseup', onUp)
}

async function saveMessageAsFile(msg: { content: string; dha_id?: string }) {
  const raw = (msg.content || '').trim()
  if (!raw) return
  const dhaLabel = msg.dha_id || 'dha'
  const ts = new Date()
  const tsStr = `${ts.getFullYear()}${String(ts.getMonth() + 1).padStart(2, '0')}${String(ts.getDate()).padStart(2, '0')}-${String(ts.getHours()).padStart(2, '0')}${String(ts.getMinutes()).padStart(2, '0')}`
  const suggested = `${dhaLabel}-${tsStr}.md`
  const filename = window.prompt('保存为工作区文件名（如 note.md）', suggested)
  if (!filename || !filename.trim()) return
  try {
    const r = await fetch(`/api/workspaces/${encodeURIComponent(props.groupSessionId)}/files`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ filename: filename.trim(), content: raw }),
    })
    const j = await r.json()
    if (j.status === 'ok' && j.data?.path) {
      console.log('已保存为工作区文件:', j.data.path)
    } else {
      alert((j as { detail?: string }).detail || '保存失败')
    }
  } catch (e) {
    console.error('保存消息为文件失败', e)
    alert('保存失败，请检查网络或后端服务')
  }
}

async function openPromptEditor() {
  if (!overrideNextSpeaker.value || overrideNextSpeaker.value === 'user') {
    return
  }
  try {
    const r = await fetch(`/api/sessions/${encodeURIComponent(props.groupSessionId)}/prompt-preview`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ dha_id: overrideNextSpeaker.value }),
    })
    const j = await r.json()
    if (j.status === 'ok' && j.data?.prompt) {
      promptEditorText.value = j.data.prompt as string
      showPromptEditor.value = true
    } else {
      alert((j as { detail?: string }).detail || '加载提示词失败')
    }
  } catch {
    alert('加载提示词失败，请检查网络或后端服务')
  }
}

function closePromptEditor() {
  showPromptEditor.value = false
}

function confirmPromptEditor() {
  const v = promptEditorText.value || ''
  customPrompt.value = v
  inputText.value = v  // 同步到输入框，用户可直接发送
  singleInputValue.value = v
  showPromptEditor.value = false
}

watch(
  () => props.messages,
  (next) => {
    if (!isStreaming.value && next?.length !== undefined) {
      displayedMessages.value = [...next]
      const lastWithPrompt = next?.slice().reverse().find((m: { next_prompt?: string }) => m?.next_prompt)
      if (lastWithPrompt?.next_prompt) {
        inputText.value = lastWithPrompt.next_prompt
        if (!showExtendedInputs.value) singleInputValue.value = lastWithPrompt.next_prompt
      }
      const firstUser = next?.find((m: { role: string }) => m.role === 'user')
      if (firstUser?.content && !discussionGoalText.value) {
        discussionGoalText.value = stripDiscussionGoalForDisplay(firstUser.content)
        if (!showExtendedInputs.value && !singleInputValue.value) singleInputValue.value = stripDiscussionGoalForDisplay(firstUser.content)
      }
      recentDiscussionText.value = recentDiscussionPreview.value
      // 0 成员时：从最后一条带 suggested_add_dha_ids 的主持人消息恢复邀请条
      if (!props.dhaIds?.length) {
        const lastHost = next?.slice().reverse().find((m: { role?: string; suggested_add_dha_ids?: string[]; suggested_add_dha_id?: string }) => m.role === 'host' && (m.suggested_add_dha_ids?.length || m.suggested_add_dha_id))
        if (lastHost) {
          if ((lastHost as { suggested_add_dha_ids?: string[] }).suggested_add_dha_ids?.length)
            suggestedAddDhaIds.value = (lastHost as { suggested_add_dha_ids: string[] }).suggested_add_dha_ids
          else if ((lastHost as { suggested_add_dha_id?: string }).suggested_add_dha_id)
            suggestedAddDhaIds.value = [(lastHost as { suggested_add_dha_id: string }).suggested_add_dha_id]
        }
      }
    }
  },
  { immediate: true }
)
watch(
  () => props.dhaIds?.length ?? 0,
  (len) => {
    if (len > 0) suggestedAddDhaIds.value = []
  }
)
const dhaList = computed(() => {
  return props.dhaIds.map((id) => ({
    dha_id: id,
    name: props.dhaMap[id]?.name || id,
    role: props.dhaMap[id]?.role,
  }))
})

/** 最近讨论摘要（由消息生成），用于同步到可编辑框 */
const recentDiscussionPreview = computed(() => {
  const msgs = displayedMessages.value
  if (!msgs.length) return '暂无讨论内容'
  const recent = msgs.slice(-16)
  const lines: string[] = []
  for (const m of recent) {
    const role = m.role || ''
    const content = (m.content || '').trim().slice(0, 180)
    if (role === 'user') lines.push(`【用户】${content}${(m.content || '').length > 180 ? '…' : ''}`)
    else if (role === 'host') lines.push(`【主持人】${content}${(m.content || '').length > 180 ? '…' : ''}`)
    else lines.push(`【${getDhaName(m.dha_id) || '助手'}】${content}${(m.content || '').length > 180 ? '…' : ''}`)
  }
  return lines.join('\n\n')
})

/** 主持人首轮返回的 suggested_order（任务规划顺序） */
const suggestedOrderFromHost = computed(() => {
  for (let i = displayedMessages.value.length - 1; i >= 0; i--) {
    const order = displayedMessages.value[i]?.suggested_order
    if (order && Array.isArray(order) && order.length) return order
  }
  return []
})

/** 流程步进器数据：优先用主持人 suggested_order，并标记已完成/当前/待执行 */
const flowSteps = computed(() => {
  const order = suggestedOrderFromHost.value
  const msgs = displayedMessages.value
  const actual: { id: string; label: string }[] = []
  for (const m of msgs) {
    if (m.role === 'user') actual.push({ id: 'user', label: '用户' })
    else if (m.role === 'assistant' && m.dha_id) actual.push({ id: m.dha_id, label: getDhaName(m.dha_id) || m.dha_id })
  }
  if (order.length) {
    const steps = order.map((id): { id: string; label: string; state: 'done' | 'current' | 'upcoming' } => {
      const sid = (id === 'user' ? 'user' : id) as string
      return { id: sid, label: sid === 'user' ? '用户' : (getDhaName(sid) || sid), state: 'upcoming' as const }
    })
    for (const a of actual) {
      const idx = steps.findIndex(s => s.id === a.id && s.state === 'upcoming')
      if (idx >= 0) steps[idx].state = 'done'
    }
    const firstUpcoming = steps.findIndex(s => s.state === 'upcoming')
    if (firstUpcoming >= 0) steps[firstUpcoming].state = 'current'
    return steps
  }
  if (actual.length) {
    return actual.map((a, i) => ({
      id: a.id,
      label: a.label,
      state: (i < actual.length - 1 ? 'done' : 'current') as 'done' | 'current' | 'upcoming',
    }))
  }
  return []
})

/** 下一发言人单选列表：主持人定 + 用户 + 各 DHA */
const nextSpeakerOptions = computed(() => {
  const opts: { value: string; label: string }[] = [
    { value: '', label: '主持人定' },
    { value: 'user', label: '用户' },
  ]
  for (const d of dhaList.value) {
    opts.push({ value: d.dha_id, label: d.name || d.dha_id })
  }
  return opts
})

const canSend = computed(() => {
  if (overrideNextSpeaker.value) return true
  if (!showExtendedInputs.value) return !!singleInputValue.value.trim()
  return !!(discussionGoalText.value.trim() || inputText.value.trim())
})

/** 当前会话成员（用于头部展示：谁是谁、干啥的），含 name/role 及是否主持人 */
const sessionMembers = computed(() => {
  const all = props.allDhaInstances || []
  return props.dhaIds.map((id) => {
    const fromMap = props.dhaMap?.[id]
    const fromAll = all.find((d) => d.dha_id === id)
    return {
      dha_id: id,
      name: fromMap?.name || fromAll?.name || id,
      role: fromMap?.role ?? fromAll?.role ?? '',
      isLeader: props.leaderDhaId === id,
    }
  })
})

const invitableDhas = computed(() => {
  const inGroup = new Set(props.dhaIds)
  return (props.allDhaInstances || []).filter((d) => !inGroup.has(d.dha_id))
})

/** 主持人推荐的 DHA 的展示名（多位用顿号连接） */
const suggestedAddDhaName = computed(() => {
  const ids = suggestedAddDhaIds.value
  if (!ids.length) return ''
  const names = ids.map((id) => (props.allDhaInstances || []).find((x) => x.dha_id === id)?.name || id)
  return names.join('、')
})

const showInviteDha = ref(false)
const inviteSelectedIds = ref<string[]>([])
/** 主持人推荐的待邀请 DHA（0 成员时从 message/end 的 suggested_add_dha_ids 解析） */
const suggestedAddDhaIds = ref<string[]>([])
const showExtendedInputs = ref(false)
const showMoreMenu = ref(false)
/** 默认单输入框时的内容：无用户消息时作为讨论目标，有用户消息时作为下一 DHA 提示词 */
const singleInputValue = ref('')

async function confirmInviteDha() {
  if (!inviteSelectedIds.value.length) return
  try {
    const r = await fetch(`/api/sessions/${encodeURIComponent(props.groupSessionId)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ add_dha_ids: inviteSelectedIds.value }),
    })
    const j = await r.json()
    if (j.status === 'ok') {
      showInviteDha.value = false
      inviteSelectedIds.value = []
      emit('dha-added')
    } else {
      alert((j as { detail?: string }).detail || '邀请失败')
    }
  } catch {
    alert('邀请失败，请检查网络')
  }
}

/** 同意主持人推荐并邀请（0 成员时展示的「同意并邀请」按钮） */
async function inviteSuggestedDha() {
  const ids = suggestedAddDhaIds.value
  if (!ids.length) return
  try {
    const r = await fetch(`/api/sessions/${encodeURIComponent(props.groupSessionId)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ add_dha_ids: ids }),
    })
    const j = await r.json()
    if ((j as { status?: string }).status === 'ok') {
      suggestedAddDhaIds.value = []
      emit('dha-added')
    } else {
      alert((j as { detail?: string }).detail || '邀请失败')
    }
  } catch {
    alert('邀请失败，请检查网络')
  }
}

function getDhaName(dhaId: string) {
  const map = props.dhaMap || {}
  return map[dhaId]?.name || dhaId || '助手'
}

function getDhaRole(dhaId: string) {
  const map = props.dhaMap || {}
  const role = map[dhaId]?.role
  return (role && String(role).trim()) || ''
}

const DHA_BOX_COUNT = 8

function getDhaBoxStyle(dhaId: string): { borderLeftColor: string; backgroundColor: string } {
  let idx = 0
  if (dhaId) {
    let hash = 0
    for (let i = 0; i < dhaId.length; i++) {
      hash = ((hash << 5) - hash) + dhaId.charCodeAt(i)
      hash |= 0
    }
    idx = Math.abs(hash) % DHA_BOX_COUNT
  }
  return {
    borderLeftColor: `var(--color-dha-box-${idx})`,
    backgroundColor: `var(--color-dha-box-${idx}-bg)`,
  }
}

function getDhaSkillLabel(dhaId: string, msg?: { skill_id?: string; meta?: { skills?: string[] } }): string {
  if (msg?.skill_id) return msg.skill_id
  if (msg?.meta?.skills?.length) return msg.meta.skills[0]
  return '无'
}

/** 展示时去掉「【讨论目标】」前缀，不在前端显示 */
function stripDiscussionGoalForDisplay(content: string): string {
  const raw = (content ?? '').trim()
  if (!raw) return ''
  const prefix = '【讨论目标】'
  if (raw.startsWith(prefix)) return raw.slice(prefix.length).replace(/^\s*\n?/, '').trim() || ''
  return raw
}

function formatMsgTime(iso?: string): string {
  if (!iso) return ''
  try {
    const d = new Date(iso)
    return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })
  } catch {
    return iso
  }
}

/** 从 content 中提取 tool_call JSON 块，返回 { toolCalls, rest } */
function extractToolCalls(content: string): { toolCalls: string[]; rest: string } {
  const text = content ?? ''
  const jsonBlockRe = /```(?:json)?\s*([\s\S]*?)```/g
  let match: RegExpExecArray | null
  const toolCalls: string[] = []
  const restParts: string[] = []
  let lastIndex = 0
  while ((match = jsonBlockRe.exec(text)) !== null) {
    const before = text.slice(lastIndex, match.index)
    if (before) restParts.push(before)
    lastIndex = match.index + match[0].length
    const raw = match[1].trim()
    try {
      const obj = JSON.parse(raw)
      if (obj && obj.action === 'tool_call') {
        toolCalls.push(JSON.stringify({ action: obj.action, tool: obj.tool, arguments: obj.arguments }, null, 2))
        continue
      }
    } catch {
      /* ignore */
    }
    restParts.push(match[0])
  }
  if (lastIndex < text.length) restParts.push(text.slice(lastIndex))
  return { toolCalls, rest: restParts.join('').trim() || text }
}

function getToolNameFromToolCall(toolCallStr: string | null): string {
  if (!toolCallStr) return '执行工具'
  try {
    const obj = JSON.parse(toolCallStr)
    return (obj && typeof obj.tool === 'string' && obj.tool) ? obj.tool : '执行工具'
  } catch {
    return '执行工具'
  }
}

type ParsedSegment = { type: 'text'; text: string } | { type: 'image'; alt: string; url: string }

function parseMessageContent(content: string): ParsedSegment[] {
  const text = (content ?? '').replace(/```(?:[\w]+)?\s*\n?([\s\S]*?)```/g, (_, inner) => inner || '')
  const re = /!\[([^\]]*)\]\(([^)]+)\)/g
  const segments: ParsedSegment[] = []
  let lastIndex = 0
  let match: RegExpExecArray | null
  while ((match = re.exec(text)) !== null) {
    if (match.index > lastIndex) {
      segments.push({ type: 'text', text: text.slice(lastIndex, match.index) })
    }
    segments.push({ type: 'image', alt: (match[1] ?? '').trim(), url: (match[2] ?? '').trim() })
    lastIndex = match.index + match[0].length
  }
  if (lastIndex < text.length) segments.push({ type: 'text', text: text.slice(lastIndex) })
  return segments.length ? segments : [{ type: 'text', text }]
}

/** markdown-it 实例：挂载后按需加载，避免顶层 import 导致模块加载失败、右侧空白 */
const mdRef = ref<{ render: (s: string) => string } | null>(null)
onMounted(() => {
  import('markdown-it').then((M) => {
    const Md = M.default as new (opts?: { breaks?: boolean }) => { render: (s: string) => string }
    mdRef.value = new Md({ breaks: true })
  }).catch(() => {})
})

function escapeHtml(s: string) {
  if (!s) return ''
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

/** 去掉末尾空行，并把连续换行压成单个，减少段落间空行 */
function normalizeContent(s: string) {
  if (!s) return ''
  return s.trimEnd().replace(/\n{2,}/g, '\n')
}

function renderMarkdown(text: string) {
  if (!text) return ''
  if (!mdRef.value) return escapeHtml(text)
  try {
    return mdRef.value.render(normalizeContent(text))
  } catch {
    return escapeHtml(text)
  }
}

function onChatInputKeydown(e: KeyboardEvent) {
  if (e.key === ' ' && e.metaKey) {
    e.preventDefault()
    sendMessage()
  }
}

async function sendMessage() {
  const hasOverride = !!overrideNextSpeaker.value
  const useSingle = !showExtendedInputs.value
  const goalText = useSingle ? singleInputValue.value.trim() : discussionGoalText.value.trim()
  const promptText = useSingle ? singleInputValue.value.trim() : inputText.value.trim()
  if (isStreaming.value) return
  if (!hasOverride && !goalText && !promptText) return

  // 选择下一发言人时：发送「确认并继续」，message 为空，custom_prompt 为输入框提示词；否则发送用户消息（讨论目标）
  const msg = hasOverride ? '' : (goalText || promptText)
  if (!hasOverride) {
    inputText.value = ''
    if (useSingle) singleInputValue.value = ''
    else discussionGoalText.value = ''
  } else {
    inputText.value = ''
    if (useSingle) singleInputValue.value = ''
  }
  isStreaming.value = true

  if (msg) {
    const userMsg = {
      message_id: `msg-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      role: 'user' as const,
      content: msg,
    }
    displayedMessages.value = [...displayedMessages.value, userMsg]
    scrollToBottom()
  }

  const body: Record<string, string> = { message: msg }
  if (hasOverride) {
    body.override_next_speaker = overrideNextSpeaker.value
    if (promptText) body.custom_prompt = promptText
  }
  if (!hasOverride && customPrompt.value.trim()) {
    body.custom_prompt = customPrompt.value.trim()
  }

  try {
    streamingPhase.value = '正在准备…'
    const r = await fetch(`/api/sessions/${encodeURIComponent(props.groupSessionId)}/chat/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (!r.ok) throw new Error(r.statusText)
    emit('message-sent')

    const reader = r.body?.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    if (reader) {
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const parts = buffer.split('\n\n')
        buffer = parts.pop() || ''
        for (const block of parts) {
          if (!block.startsWith('event: ')) continue
          const eventType = block.slice(0, block.indexOf('\n')).replace('event: ', '').trim()
          const dataStr = block.includes('\ndata: ') ? block.split('\ndata: ').slice(1).join('\ndata: ').trim() : ''
          if (eventType === 'start') {
            streamingPhase.value = '正在准备…'
          } else if (eventType === 'message' && dataStr) {
            streamingPhase.value = '正在生成回复…'
            try {
              const data = JSON.parse(dataStr)
              if (data && (data.role === 'assistant' || data.role === 'user' || data.role === 'host')) {
                displayedMessages.value = [...displayedMessages.value, data]
                if (data.next_prompt) {
                  inputText.value = data.next_prompt
                  singleInputValue.value = data.next_prompt
                }
                if (data.suggested_add_dha_ids?.length) suggestedAddDhaIds.value = data.suggested_add_dha_ids
                else if (data.suggested_add_dha_id) suggestedAddDhaIds.value = [data.suggested_add_dha_id]
                recentDiscussionText.value = recentDiscussionPreview.value
                scrollToBottom()
              }
            } catch (_) {}
            } else if (eventType === 'end' && dataStr) {
              streamingPhase.value = ''
              try {
                const endData = JSON.parse(dataStr)
                // pause and fill next speaker and prompt if provided
                if (endData.waiting_for_user && endData.suggested_next_speaker != null) {
                  overrideNextSpeaker.value = endData.suggested_next_speaker
                }
                if (endData.next_prompt) {
                  inputText.value = endData.next_prompt
                  singleInputValue.value = endData.next_prompt
                }
                if (endData.suggested_add_dha_ids?.length) suggestedAddDhaIds.value = endData.suggested_add_dha_ids
                else if (endData.suggested_add_dha_id) suggestedAddDhaIds.value = [endData.suggested_add_dha_id]
                // clear any pending auto-confirm to avoid auto-send
                if (endData.suggested_next_speaker != null) {
                  pendingAutoConfirmSpeaker.value = null
                }
              } catch (_) {}
            }
        }
      }
    }
    emit('message-sent')
  } catch (e) {
    console.error('Group 发送失败', e)
  } finally {
    isStreaming.value = false
    streamingPhase.value = ''
    // 自动模式下暂停，等待用户确认 next_prompt 后手动发送
    if (pendingAutoConfirmSpeaker.value != null && props.speakMode === 'auto') {
      const next = pendingAutoConfirmSpeaker.value
      pendingAutoConfirmSpeaker.value = null
      overrideNextSpeaker.value = next
    }
  }
}

async function onAutoSwitchChange(e: Event) {
  const target = e.target as HTMLInputElement
  const next = target.checked ? 'auto' : 'manual'
  const wasAuto = props.speakMode === 'auto'
  try {
    const r = await fetch(`/api/sessions/${encodeURIComponent(props.groupSessionId)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ speak_mode: next }),
    })
    const j = await r.json()
    if (j.status === 'ok') {
      emit('speak-mode-changed')
      // 从自动切换到手动时，向后端发送消息让主持人返回并暂停
      if (wasAuto && next === 'manual') {
        isStreaming.value = true
        streamingPhase.value = '正在切换模式…'
        try {
          const res = await fetch(`/api/sessions/${encodeURIComponent(props.groupSessionId)}/chat/stream`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: '' }),
          })
          if (res.ok) {
            const reader = res.body?.getReader()
            const decoder = new TextDecoder()
            let buffer = ''
            if (reader) {
              while (true) {
                const { done, value } = await reader.read()
                if (done) break
                buffer += decoder.decode(value, { stream: true })
                const parts = buffer.split('\n\n')
                buffer = parts.pop() || ''
                for (const block of parts) {
                  if (!block.startsWith('event: ')) continue
                  const eventType = block.slice(0, block.indexOf('\n')).replace('event: ', '').trim()
                  const dataStr = block.includes('\ndata: ') ? block.split('\ndata: ').slice(1).join('\ndata: ').trim() : ''
                  if (eventType === 'message' && dataStr) {
                    try {
                      const data = JSON.parse(dataStr)
                      if (data && data.content) {
                        displayedMessages.value = [...displayedMessages.value, data]
                        if (data.next_prompt) {
                          inputText.value = data.next_prompt
                          singleInputValue.value = data.next_prompt
                        }
                        if (data.suggested_add_dha_ids?.length) suggestedAddDhaIds.value = data.suggested_add_dha_ids
                        else if (data.suggested_add_dha_id) suggestedAddDhaIds.value = [data.suggested_add_dha_id]
                        scrollToBottom()
                      }
                    } catch {}
                  } else if (eventType === 'end' && dataStr) {
                    streamingPhase.value = ''
                    try {
                      const endData = JSON.parse(dataStr)
                      if (endData.suggested_add_dha_ids?.length) suggestedAddDhaIds.value = endData.suggested_add_dha_ids
                      else if (endData.suggested_add_dha_id) suggestedAddDhaIds.value = [endData.suggested_add_dha_id]
                    } catch {}
                  }
                }
              }
            }
          }
        } finally {
          isStreaming.value = false
        }
      }
    } else {
      target.checked = !target.checked
    }
  } catch {
    target.checked = !target.checked
  }
}

watch(
  () => overrideNextSpeaker.value,
  () => {
    // 选择不同的下一发言人时，清空上一次编辑的提示词，避免误用
    customPrompt.value = ''
  }
)

function scrollToBottom() {
  nextTick(() => {
    messagesContainerRef.value?.scrollTo({ top: messagesContainerRef.value.scrollHeight, behavior: 'smooth' })
  })
}

watch(
  () => displayedMessages.value.length,
  () => { scrollToBottom() }
)
</script>

<style scoped>
.thinking-dot {
  animation: thinking-bounce 0.6s ease-in-out infinite;
}
@keyframes thinking-bounce {
  0%, 60%, 100% {
    transform: translateY(0);
    opacity: 0.5;
  }
  30% {
    transform: translateY(-4px);
    opacity: 1;
  }
}
.chat-markdown :deep(p) {
  margin: 0 0 0.35em 0;
}
.chat-markdown :deep(p:last-child) {
  margin-bottom: 0;
}
.docx-preview :deep(*) {
  max-width: 100%;
}

/* 群聊输入区：圆角 24px，功能按钮 16px，宽度 90% 最大 1400px，响应式 100%+20px */
.group-chat-input-outer {
  padding: 20px;
}
.group-chat-input-box {
  width: 90%;
  max-width: 1400px;
  margin: 0 auto;
  background: var(--color-page);
  border: 1px solid var(--color-input-border);
  border-radius: 24px;
  overflow: hidden;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.08);
}
@media (max-width: 768px) {
  .group-chat-input-box {
    width: 100%;
  }
}
.group-chat-input-area {
  border-radius: 0;
}
.group-chat-input-btn-row {
  border-top: 1px solid var(--color-border-light);
}
.group-chat-input-footer {
  flex-shrink: 0;
}
.group-chat-func-btn {
  background: var(--color-sidebar-list);
  border: none;
  border-radius: 16px;
  color: var(--color-text-muted);
  padding: 8px 16px;
  font-size: 0.875rem;
  cursor: pointer;
  transition: background 0.15s, color 0.15s;
}
.group-chat-func-btn:hover {
  background: var(--color-list-hover);
  color: var(--color-text);
}
</style>
