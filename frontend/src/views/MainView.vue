<template>
  <div class="flex flex-1 min-h-0 min-w-0 bg-page">
    <!-- 最左侧：导航（图标 + 名称） -->
    <nav class="w-28 flex-shrink-0 flex flex-col bg-sidebar py-3">
      <div class="px-2 space-y-0.5">
        <div class="px-1 pb-2">
          <div class="flex items-center justify-center py-1">
            <img
              :src="logoUrl"
              alt="书童四九 logo"
              class="h-16 w-16 rounded-full object-cover"
              width="64"
              height="64"
              decoding="async"
            />
          </div>
        </div>
        <button
          type="button"
          @click="onNavClick('workspace')"
          :class="[
            'w-full flex items-center justify-between px-2 py-2.5 rounded-lg text-sm font-medium transition-colors',
            currentModule === 'workspace'
              ? 'bg-nav-selected-bg text-nav-selected-text'
              : 'text-nav-text hover:bg-nav-hover-bg'
          ]"
        >
          <span class="truncate">工作空间</span>
        </button>
        <button
          type="button"
          @click="onNavClick('resource')"
          :class="[
            'w-full flex items-center justify-between px-2 py-2.5 rounded-lg text-sm font-medium transition-colors',
            currentModule === 'resource'
              ? 'bg-nav-selected-bg text-nav-selected-text'
              : 'text-nav-text hover:bg-nav-hover-bg'
          ]"
        >
          <span class="truncate">资源中心</span>
          <span class="inline-flex items-center justify-center w-4 h-4 rounded-md bg-list-hover">
            <svg
              class="w-3 h-3 transition-transform duration-200"
              :class="resourceMenuExpanded ? 'rotate-180' : ''"
              viewBox="0 0 20 20"
              fill="none"
              xmlns="http://www.w3.org/2000/svg"
              aria-hidden="true"
            >
              <path d="M5 7.5L10 12.5L15 7.5" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" />
            </svg>
          </span>
        </button>
        <div
          v-if="resourceMenuExpanded"
          class="pl-4 pr-1 py-1 space-y-0.5"
        >
          <button
            v-for="child in resourceChildren"
            :key="child.id"
            type="button"
            @click="onResourceChildClick(child.id)"
            :class="[
              'w-full text-left px-2 py-1.5 rounded-md text-xs transition-colors',
              currentModule === 'resource' && resourceSubModule === child.id
                ? 'bg-nav-selected-bg text-nav-selected-text'
                : 'text-nav-text hover:bg-nav-hover-bg'
            ]"
          >
            {{ child.label }}
          </button>
        </div>
        <button
          type="button"
          @click="onNavClick('settings')"
          :class="[
            'w-full flex items-center justify-between px-2 py-2.5 rounded-lg text-sm font-medium transition-colors',
            currentModule === 'settings'
              ? 'bg-nav-selected-bg text-nav-selected-text'
              : 'text-nav-text hover:bg-nav-hover-bg'
          ]"
        >
          <span class="truncate">设置</span>
        </button>
      </div>
      <div class="flex-1 min-h-2" />
      <div class="px-2 pb-3 pt-2 flex flex-col gap-1 border-t border-sidebar-border/60">
        <button
          type="button"
          @click="logout"
          :class="[
            'w-full flex items-center justify-center px-2 py-2.5 rounded-lg text-sm font-medium transition-colors',
            'text-nav-text hover:bg-nav-hover-bg'
          ]"
        >
          登出
        </button>
      </div>
    </nav>

    <!-- 中间列：当前模块的列表/摘要 -->
    <aside
      class="flex-shrink-0 flex flex-col bg-sidebar overflow-hidden"
      :style="{ width: middleColumnOpen ? middleColumnWidth + 'px' : '0px' }"
    >
      <!-- 顶部区 -->
      <div v-if="currentModule === 'workspace'" class="px-3 pt-3 pb-3 flex-shrink-0">
        <button
          @click="createNewSession"
          :class="[
            'w-full px-3 py-3 rounded-xl text-sm font-semibold flex items-center justify-center gap-1 transition-colors shadow-sm',
            creatingSession
              ? 'opacity-70 pointer-events-none bg-nav-selected-bg text-nav-selected-text'
              : 'bg-nav-selected-bg text-nav-selected-text hover:bg-nav-hover-bg'
          ]"
        >
          <span class="text-base leading-none">＋</span>
          <span>新建会话</span>
        </button>
      </div>
      <div
        class="flex-1 overflow-y-auto middle-column-scrollbar"
        :class="currentModule === 'resource' ? 'pt-3' : ''"
      >
        <!-- 工作空间：统一会话列表 -->
        <template v-if="currentModule === 'workspace'">
          <div v-if="groupSessionsLoading" class="px-3 py-4 text-sm text-muted">加载中...</div>
          <div v-else-if="!groupSessions.length" class="px-3 py-4 text-sm text-muted">暂无会话</div>
          <div
            v-else
            v-for="s in groupSessions"
            :key="s.id"
            @click="selectGroupSession(s.id)"
            :class="[
              'w-full flex items-center gap-1 px-3 py-2.5 rounded-lg text-sm transition-colors cursor-pointer group',
              selectedGroupSessionId === s.id ? 'bg-accent-subtle text-accent-subtle-text' : 'hover:bg-list-hover text-list-hover-text'
            ]"
          >
            <div class="flex-1 min-w-0 text-left">
              <div class="truncate font-medium">{{ displaySessionTitle(s) }}</div>
              <div class="mt-0.5 flex items-center gap-1">
                <template v-if="(s.agent_ids?.length || 0) > 0">
                  <div class="flex -space-x-1">
                    <span
                      v-for="id in (s.agent_ids || []).slice(0, 3)"
                      :key="id"
                      class="inline-flex items-center justify-center w-5 h-5 rounded-full text-[10px] font-semibold text-text-inverse shrink-0 ring-1 ring-sidebar"
                      :style="{ backgroundColor: dhaAvatarColorForId(id) }"
                    >
                      {{ dhaAvatarCharForId(id) }}
                    </span>
                  </div>
                  <span class="truncate text-xs text-muted">
                    {{ (s.agent_ids?.length || 0) }} 位专家 · {{ formatDate(s.updated_at) }}
                  </span>
                </template>
                <template v-else>
                  <span class="truncate text-xs text-muted">
                    0 位专家 · {{ formatDate(s.updated_at) }}
                  </span>
                </template>
              </div>
            </div>
            <div class="flex-shrink-0 flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
              <button
                type="button"
                class="p-1.5 rounded text-muted hover:text-danger hover:bg-danger-subtle"
                title="删除"
                @click.stop="deleteGroupSession(s.id)"
              >
                ×
              </button>
            </div>
          </div>
        </template>
        <!-- 资源中心：子 Tab 专家 / Skill / MCP -->
        <template v-else-if="currentModule === 'resource'">
          <!-- 场景 -->
          <template v-if="resourceSubModule === 'scenario'">
            <div class="px-3 mb-2 space-y-2">
              <div class="flex items-center gap-2">
                <button
                  type="button"
                  class="flex-1 h-10 px-3 rounded-xl text-sm font-semibold flex items-center justify-center gap-1 transition-colors shadow-sm bg-nav-selected-bg text-nav-selected-text hover:bg-nav-hover-bg"
                  @click="createScenarioPreset"
                >
                  <span class="text-base leading-none">＋</span>
                  <span>创建场景</span>
                </button>
                <button
                  type="button"
                  class="w-10 h-10 rounded-xl bg-list-hover text-primary hover:bg-nav-hover-bg transition-colors flex items-center justify-center"
                  title="搜索场景"
                  @click="toggleSearch('scenario')"
                >
                  <svg
                    class="main-sidebar-svg-icon"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="1.5"
                    stroke-linecap="round"
                    stroke-linejoin="round"
                    aria-hidden="true"
                  >
                    <circle cx="11" cy="11" r="7" />
                    <path d="M20 20l-3.5-3.5" />
                  </svg>
                </button>
              </div>
              <input
                v-if="showScenarioSearch"
                v-model="scenarioSearch"
                type="text"
                placeholder="搜索场景（名称/描述）"
                class="w-full px-3 py-2 text-sm bg-input-bg border border-input-border rounded-lg text-primary placeholder-muted focus:outline-none focus:ring-2 focus:ring-input-focus-ring"
              />
            </div>
            <div v-if="scenarioLoading" class="px-3 py-4 text-sm text-muted">加载中...</div>
            <div v-else-if="!filteredScenarioPresets.length" class="px-3 py-4 text-sm text-muted">暂无场景</div>
            <div
              v-else
              v-for="s in filteredScenarioPresets"
              :key="s.id"
              :class="[
                'w-full flex items-center gap-1 px-3 py-2.5 rounded-lg text-sm transition-colors cursor-pointer group',
                selectedId === s.id ? 'bg-accent-subtle text-accent-subtle-text' : 'hover:bg-list-hover text-list-hover-text'
              ]"
              @click="selectedId = s.id"
            >
              <div class="flex-1 min-w-0 text-left">
                <div class="truncate font-medium">{{ s.name }}</div>
                <div class="truncate text-xs text-muted mt-0.5">{{ s.agent_ids.length }} 位专家</div>
              </div>
              <button
                type="button"
                class="p-1.5 rounded text-muted hover:text-danger hover:bg-danger-subtle opacity-0 group-hover:opacity-100"
                title="删除"
                @click.stop="deleteScenarioPreset(s.id)"
              >
                ×
              </button>
            </div>
          </template>
          <!-- 专家 -->
          <template v-else-if="resourceSubModule === 'dha'">
            <div class="mb-2 px-3 space-y-2">
              <div class="flex items-center gap-2">
                <button
                  @click="selectedId = '__new__'"
                  :class="[
                    'flex-1 h-10 px-3 rounded-xl text-sm font-semibold flex items-center justify-center gap-1 transition-colors shadow-sm',
                    selectedId === '__new__'
                      ? 'bg-nav-selected-bg text-nav-selected-text'
                      : 'bg-nav-selected-bg text-nav-selected-text hover:bg-nav-hover-bg'
                  ]"
                >
                  <span class="text-base leading-none">＋</span>
                  <span>创建专家</span>
                </button>
                <button
                  type="button"
                  class="w-10 h-10 rounded-xl bg-list-hover text-primary hover:bg-nav-hover-bg transition-colors flex items-center justify-center"
                  title="搜索专家"
                  @click="toggleSearch('dha')"
                >
                  <svg
                    class="main-sidebar-svg-icon"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="1.5"
                    stroke-linecap="round"
                    stroke-linejoin="round"
                    aria-hidden="true"
                  >
                    <circle cx="11" cy="11" r="7" />
                    <path d="M20 20l-3.5-3.5" />
                  </svg>
                </button>
              </div>
            </div>
            <div v-if="showDhaSearch" class="px-3 mb-2">
              <input
                v-model="dhaSearch"
                type="text"
                placeholder="搜索专家（名称/描述）"
                class="w-full px-3 py-2 text-sm bg-input-bg border border-input-border rounded-lg text-primary placeholder-muted focus:outline-none focus:ring-2 focus:ring-input-focus-ring"
              />
            </div>
            <div v-if="dhaInstancesLoading" class="px-3 py-4 text-sm text-muted">加载中...</div>
            <div v-else-if="!filteredDhaInstances.length" class="px-3 py-4 text-sm text-muted">暂无专家</div>
            <div
              v-else
              v-for="d in filteredDhaInstances"
              :key="d.agent_id"
              :class="[
                'w-full flex items-center gap-1 px-3 py-2.5 rounded-lg text-sm transition-colors cursor-pointer group',
                selectedId === d.agent_id ? 'bg-accent-subtle text-accent-subtle-text' : 'hover:bg-list-hover text-list-hover-text'
              ]"
              @click="selectedId = d.agent_id"
            >
              <div class="flex-1 min-w-0 text-left">
              <div class="truncate font-medium">{{ d.name || d.agent_id }}</div>
                <div class="truncate text-xs text-muted mt-0.5">{{ d.role || '（无角色）' }}</div>
              </div>
              <button
                type="button"
                class="p-1.5 rounded text-muted hover:text-danger hover:bg-danger-subtle opacity-0 group-hover:opacity-100"
                title="删除专家"
                @click.stop="deleteDhaInstance(d.agent_id)"
              >
                ×
              </button>
            </div>
          </template>
          <!-- Skill -->
          <template v-else-if="resourceSubModule === 'skill'">
            <div class="mb-2 px-3 space-y-2">
              <div class="flex items-center gap-2">
                <button
                  @click="createEmptySkill"
                  :class="[
                    'flex-1 h-10 px-3 rounded-xl text-sm font-semibold flex items-center justify-center gap-1 transition-colors shadow-sm',
                    'bg-nav-selected-bg text-nav-selected-text hover:bg-nav-hover-bg'
                  ]"
                >
                  <span class="text-base leading-none">＋</span>
                  <span>创建技能</span>
                </button>
                <button
                  type="button"
                  class="w-10 h-10 rounded-xl bg-list-hover text-primary hover:bg-nav-hover-bg transition-colors flex items-center justify-center"
                  @click="triggerSkillZipImport"
                  title="导入技能"
                >
                  <svg
                    class="main-sidebar-svg-icon"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="1.8"
                    stroke-linecap="round"
                    stroke-linejoin="round"
                    aria-hidden="true"
                  >
                    <path d="M14 3h6v18h-6" />
                    <path d="M4 12h11" />
                    <path d="m11 8 4 4-4 4" />
                  </svg>
                </button>
                <input
                  ref="skillZipInputRef"
                  type="file"
                  accept=".zip,application/zip"
                  class="hidden"
                  @change="onSkillZipSelected"
                />
                <button
                  type="button"
                  class="w-10 h-10 rounded-xl bg-list-hover text-primary hover:bg-nav-hover-bg transition-colors flex items-center justify-center"
                  title="搜索技能"
                  @click="toggleSearch('skill')"
                >
                  <svg
                    class="main-sidebar-svg-icon"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="1.5"
                    stroke-linecap="round"
                    stroke-linejoin="round"
                    aria-hidden="true"
                  >
                    <circle cx="11" cy="11" r="7" />
                    <path d="M20 20l-3.5-3.5" />
                  </svg>
                </button>
              </div>
            </div>
            <div v-if="showSkillSearch" class="px-3 mb-2">
              <input
                v-model="skillSearch"
                type="text"
                placeholder="搜索技能（名称/描述）"
                class="w-full px-3 py-2 text-sm bg-input-bg border border-input-border rounded-lg text-primary placeholder-muted focus:outline-none focus:ring-2 focus:ring-input-focus-ring"
              />
            </div>
            <div v-if="skillsLoading" class="px-3 py-4 text-sm text-muted">加载中...</div>
            <button
              v-else
              v-for="s in filteredSkills"
              :key="s.id"
              @click="selectedId = s.id"
              :class="[
                'w-full text-left px-3 py-3.5 rounded-lg text-sm transition-colors',
                selectedId === s.id ? 'bg-accent-subtle text-accent-subtle-text' : 'hover:bg-list-hover text-list-hover-text'
              ]"
            >
              <div class="truncate font-medium">{{ s.name || s.id }}</div>
            </button>
          </template>
          <!-- MCP -->
          <template v-else-if="resourceSubModule === 'mcp'">
            <div class="mb-2 px-3 space-y-2">
              <div class="flex items-center gap-2">
                <button
                  @click="selectedId = '__new__'"
                  :class="[
                    'flex-1 h-10 px-3 rounded-xl text-sm font-semibold flex items-center justify-center gap-1 transition-colors shadow-sm',
                    selectedId === '__new__'
                      ? 'bg-nav-selected-bg text-nav-selected-text'
                      : 'bg-nav-selected-bg text-nav-selected-text hover:bg-nav-hover-bg'
                  ]"
                >
                  <span class="text-base leading-none">＋</span>
                  <span>创建工具</span>
                </button>
                <button
                  type="button"
                  class="w-10 h-10 rounded-xl bg-list-hover text-primary hover:bg-nav-hover-bg transition-colors flex items-center justify-center"
                  title="搜索工具"
                  @click="toggleSearch('mcp')"
                >
                  <svg
                    class="main-sidebar-svg-icon"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="1.5"
                    stroke-linecap="round"
                    stroke-linejoin="round"
                    aria-hidden="true"
                  >
                    <circle cx="11" cy="11" r="7" />
                    <path d="M20 20l-3.5-3.5" />
                  </svg>
                </button>
              </div>
            </div>
            <div v-if="showMcpSearch" class="px-3 mb-2">
              <input
                v-model="mcpSearch"
                type="text"
                placeholder="搜索工具（名称/描述）"
                class="w-full px-3 py-2 text-sm bg-input-bg border border-input-border rounded-lg text-primary placeholder-muted focus:outline-none focus:ring-2 focus:ring-input-focus-ring"
              />
            </div>
            <div v-if="mcpLoading" class="px-3 py-4 text-sm text-muted">加载中...</div>
            <button
              v-else
              v-for="s in filteredMcpServers"
              :key="s.id"
              @click="selectedId = s.id"
              :class="[
                'w-full text-left px-3 py-2.5 rounded-lg text-sm transition-colors',
                selectedId === s.id ? 'bg-accent-subtle text-accent-subtle-text' : 'hover:bg-list-hover text-list-hover-text'
              ]"
            >
              <div class="truncate font-medium">{{ s.name || s.id }}</div>
              <div class="truncate text-xs text-muted mt-0.5">{{ s.status === 'connected' ? '已连接' : '未连接' }} · {{ s.tool_count || 0 }} 工具</div>
            </button>
          </template>
          <!-- LLM -->
          <template v-else-if="resourceSubModule === 'llm'">
            <div class="mb-2 px-3 flex items-center gap-2">
              <button
                @click="selectedId = '__new__'"
                :class="[
                  'flex-1 h-10 px-3 rounded-xl text-sm font-semibold flex items-center justify-center gap-1 transition-colors shadow-sm',
                  selectedId === '__new__'
                    ? 'bg-nav-selected-bg text-nav-selected-text'
                    : 'bg-nav-selected-bg text-nav-selected-text hover:bg-nav-hover-bg'
                ]"
              >
                <span class="text-base leading-none">＋</span>
                <span>创建模型</span>
              </button>
            </div>
            <div v-if="llmLoading" class="px-3 py-4 text-sm text-muted">加载中...</div>
            <div v-else-if="!llmProviderIds.length" class="px-3 py-4 text-sm text-muted">暂无模型</div>
            <button
              v-else
              v-for="id in llmProviderIds"
              :key="id"
              @click="selectedId = id"
              :class="[
                'w-full text-left px-3 py-2.5 rounded-lg text-sm transition-colors',
                selectedId === id ? 'bg-accent-subtle text-accent-subtle-text' : 'hover:bg-list-hover text-list-hover-text'
              ]"
            >
              <div class="truncate font-medium flex items-center gap-2">
                <span class="truncate">{{ id }}</span>
                <span
                  v-if="id === llmDefault"
                  class="px-2 py-0.5 text-xs rounded-full bg-accent-subtle text-accent-subtle-text"
                >
                  默认
                </span>
              </div>
              <div class="truncate text-xs text-muted mt-0.5">{{ llmProviders[id]?.model || '—' }}</div>
            </button>
          </template>
          <!-- 文件 -->
          <template v-else-if="resourceSubModule === 'files'">
            <div class="px-3 mb-2 space-y-2">
              <input
                v-model="fileSessionSearch"
                type="text"
                placeholder="搜索会话（标题）"
                class="w-full px-3 py-2 text-sm bg-input-bg border border-input-border rounded-lg text-primary placeholder-muted focus:outline-none focus:ring-2 focus:ring-input-focus-ring"
              />
              <select
                v-model="fileSessionSort"
                class="w-full px-3 py-2 text-sm bg-input-bg border border-input-border rounded-lg text-primary focus:outline-none focus:ring-2 focus:ring-input-focus-ring"
              >
                <option value="updated_desc">按更新时间（新→旧）</option>
                <option value="updated_asc">按更新时间（旧→新）</option>
              </select>
            </div>
            <div v-if="fileSessionsLoading" class="px-3 py-4 text-sm text-muted">加载中...</div>
            <div v-else-if="!visibleFileSessions.length" class="px-3 py-4 text-sm text-muted">无匹配会话</div>
            <button
              v-else
              v-for="s in visibleFileSessions"
              :key="s.id"
              @click="selectedId = s.id"
              :class="[
                'w-full text-left px-3 py-2.5 rounded-lg text-sm transition-colors',
                selectedId === s.id ? 'bg-accent-subtle text-accent-subtle-text' : 'hover:bg-list-hover text-list-hover-text'
              ]"
            >
              <div class="truncate font-medium">{{ displaySessionTitle(s) }}</div>
              <div class="truncate text-xs text-muted mt-0.5">{{ s.file_count }} 个文件 · {{ formatDate(s.updated_at) }}</div>
            </button>
          </template>
        </template>
        <!-- 设置 -->
        <template v-else-if="currentModule === 'settings'">
          <button
            v-for="c in settingsCategories"
            :key="c.id"
            @click="selectedId = c.id"
            :class="[
              'w-full text-left px-3 py-2.5 rounded-lg text-sm transition-colors',
              selectedId === c.id ? 'bg-accent-subtle text-accent-subtle-text' : 'hover:bg-list-hover text-list-hover-text'
            ]"
          >
            {{ c.label }}
          </button>
        </template>
      </div>
    </aside>

    <!-- 拖动分隔条：调整中间列与右侧工作区宽度 -->
    <div v-if="middleColumnOpen" class="workspace-resizer" @mousedown="onMiddleResizeMouseDown" />

    <!-- 右侧列：主内容。工作空间用 v-show 保持挂载，切到资源中心再回来不会打断对话（后台保留） -->
    <main class="main-right flex-1 flex flex-col min-h-0 overflow-hidden bg-page text-primary">
      <div
        v-show="currentModule === 'workspace'"
        class="flex-1 flex flex-col min-h-0 overflow-hidden"
      >
        <WorkspaceContent
          ref="workspaceContentRef"
          :selected-group-session-id="selectedGroupSessionId"
          :dha-instances="dhaInstances"
          :middle-column-open="middleColumnOpen"
          @middle-column-open-request="middleColumnOpen = true"
          @middle-column-toggle="toggleMiddleColumn"
          @message-sent="onChatMessageSent"
          @speak-mode-changed="onGroupChatRefresh"
          @dha-added="onDhaAdded"
        />
      </div>
      <!-- 资源中心：智能体 / 技能 / 工具 -->
      <template v-if="currentModule === 'resource'">
        <template v-if="resourceSubModule === 'scenario'">
          <div class="h-full overflow-y-auto themed-scrollbar p-4">
            <div v-if="selectedScenarioPreset" class="max-w-5xl w-full mx-auto">
              <div class="mb-4">
                <h2 class="text-2xl font-semibold text-primary mb-1">
                  {{ isCreatingScenario ? '创建场景' : '配置场景' }}
                </h2>
              </div>
              <form class="space-y-6 bg-card backdrop-blur rounded-xl border border-border-light shadow-sm px-5 py-6">
                <div>
                  <label class="block text-sm font-medium text-primary mb-1">名称</label>
                  <input
                    v-model="scenarioDraft.name"
                    type="text"
                    class="w-full px-3 py-2 text-sm bg-input-bg border border-input-border rounded-lg text-primary placeholder-muted focus:outline-none focus:ring-2 focus:ring-input-focus-ring"
                    placeholder="请输入场景名称"
                  />
                </div>
                <div>
                  <label class="block text-sm font-medium text-primary mb-1">描述</label>
                  <textarea
                    v-model="scenarioDraft.description"
                    rows="3"
                    class="w-full px-3 py-2 text-sm bg-input-bg border border-input-border rounded-lg text-primary placeholder-muted focus:outline-none focus:ring-2 focus:ring-input-focus-ring resize-y"
                    placeholder="请输入场景描述"
                  />
                </div>
                <div>
                  <label class="block text-sm font-medium text-primary mb-2">专家</label>
                  <div class="flex flex-wrap gap-2">
                    <span
                      v-for="id in scenarioDraft.agent_ids"
                      :key="id"
                      class="inline-flex items-center gap-1 px-2 py-1 rounded-md text-xs bg-accent-subtle text-accent-subtle-text"
                    >
                      {{ dhaDisplayName(id) }}
                      <button
                        type="button"
                        class="ml-1 text-accent-subtle-text/80 hover:text-danger"
                        @click="removeScenarioExpert(id)"
                      >×</button>
                    </span>
                    <span v-if="!scenarioDraft.agent_ids.length" class="text-xs text-muted">暂无专家</span>
                  </div>
                  <div class="mt-3">
                    <input
                      v-model="scenarioExpertSearch"
                      type="text"
                      placeholder="搜索专家（名称/描述）"
                      class="w-full px-3 py-2 mb-2 text-sm bg-input-bg border border-input-border rounded-lg text-primary placeholder-muted focus:outline-none focus:ring-2 focus:ring-input-focus-ring"
                    />
                    <div class="flex flex-wrap gap-2">
                      <button
                        v-for="d in filteredScenarioAddableExperts"
                        :key="d.agent_id"
                        type="button"
                        class="px-2 py-1 rounded-md text-xs border border-input-border bg-card text-primary hover:bg-list-hover"
                        @click="addScenarioExpert(d.agent_id)"
                      >
                        + {{ d.name || d.agent_id }}
                      </button>
                      <span v-if="!scenarioAddableExperts.length" class="text-xs text-muted">可添加专家已为空</span>
                      <span v-else-if="!filteredScenarioAddableExperts.length" class="text-xs text-muted">无匹配专家</span>
                    </div>
                  </div>
                </div>
                <div class="flex items-center justify-end gap-2 px-4 py-3 flex-shrink-0">
                  <button
                    type="button"
                    class="inline-flex items-center justify-center px-4 py-2 text-sm font-medium rounded-lg bg-accent text-text-inverse hover:bg-accent-hover disabled:opacity-50"
                    :disabled="scenarioSaving"
                    @click="saveScenarioPreset"
                  >
                    {{ scenarioSaving ? '保存中...' : '保存' }}
                  </button>
                  <button
                    type="button"
                    class="inline-flex items-center justify-center px-4 py-2 text-sm font-medium rounded-lg bg-danger-subtle text-danger hover:opacity-90"
                    :disabled="scenarioSaving"
                    @click="deleteScenarioPreset(selectedScenarioPreset.id)"
                  >
                    删除
                  </button>
                </div>
              </form>
            </div>
            <div v-else class="flex h-full items-center justify-center text-muted text-sm">
              请从左侧选择场景
            </div>
          </div>
        </template>
        <template v-if="resourceSubModule === 'dha'">
          <DHAView
            :selected-dha-id="selectedId"
            :dha-instances="dhaInstances"
            @created="onDHACreated"
            @updated="fetchDHA"
            @cancel="selectedId = null"
          />
        </template>
        <template v-else-if="resourceSubModule === 'skill' && selectedId">
          <SkillDetailView :skill-id="selectedId" @updated="fetchSkills" @deleted="selectedId = null; fetchSkills()" />
        </template>
        <template v-else-if="resourceSubModule === 'skill'">
          <div class="flex flex-col h-full items-center justify-center text-muted text-sm p-4">
            <p>请从左侧选择技能或添加新技能</p>
          </div>
        </template>
        <template v-else-if="resourceSubModule === 'mcp' && selectedId === '__new__'">
          <MCPAddView @created="onMCPCreated" />
        </template>
        <template v-else-if="resourceSubModule === 'mcp' && selectedId">
          <MCPDetailView :server-id="selectedId" @updated="fetchMCP" @deleted="selectedId = null; fetchMCP()" />
        </template>
        <template v-else-if="resourceSubModule === 'mcp'">
          <div class="flex flex-col h-full items-center justify-center text-muted text-sm p-4">
            <p>请从左侧选择 MCP 或添加新 MCP</p>
          </div>
        </template>
        <template v-else-if="resourceSubModule === 'llm'">
          <LLMSettingsView
            :provider-id="selectedId"
            @updated="(id: string | undefined) => { fetchLLM(); if (id) selectedId = id }"
          />
        </template>
        <template v-else-if="resourceSubModule === 'files'">
          <WorkspaceFilesView
            :session-id="selectedId"
            :session-title="fileSessions.find((x) => x.id === selectedId)?.title || ''"
          />
        </template>
      </template>
      <!-- 设置 -->
      <template v-if="currentModule === 'settings'">
        <AppSettingsView v-if="selectedId === 'app'" />
        <ThemeSettingsView v-else-if="selectedId === 'theme'" />
        <UserPreferenceSettingsView v-else-if="selectedId === 'user'" />
        <AccountSecuritySettingsView v-else-if="selectedId === 'account-security'" />
        <div v-else class="flex flex-col h-full items-center justify-center text-muted text-sm p-4">
          <p>请从左侧选择设置项</p>
        </div>
      </template>
      <template v-if="currentModule !== 'workspace' && currentModule !== 'resource' && currentModule !== 'settings'">
        <div class="flex flex-col h-full items-center justify-center text-muted text-sm p-4">
          <p>请从左侧选择功能</p>
        </div>
      </template>
    </main>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, inject, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'

import SkillDetailView from './SkillDetailView.vue'
import MCPDetailView from './MCPDetailView.vue'
import MCPAddView from './MCPAddView.vue'
import AppSettingsView from './AppSettingsView.vue'
import ThemeSettingsView from './ThemeSettingsView.vue'
import UserPreferenceSettingsView from './UserPreferenceSettingsView.vue'
import AccountSecuritySettingsView from './AccountSecuritySettingsView.vue'
import LLMSettingsView from './LLMSettingsView.vue'
import DHAView from './DHAView.vue'
import WorkspaceContent from './WorkspaceContent.vue'
import WorkspaceFilesView from './WorkspaceFilesView.vue'
import { useTheme } from '@/composables/useTheme'
import logoUrl from '@/assets/49logo.png'
import './MainView.css'

const router = useRouter()
// 主题 composable 在该视图内会触发全局样式变量初始化；无需直接读取其返回值
inject<ReturnType<typeof useTheme>>('theme') ?? useTheme()
const LOGIN_STORAGE_KEY = 'dha_logged_in'
const USER_STORAGE_KEY = 'dha_user'
const TOKEN_STORAGE_KEY = 'dha_token'

function logout() {
  if (!window.confirm('确定要登出吗？')) return
  localStorage.removeItem(LOGIN_STORAGE_KEY)
  localStorage.removeItem(USER_STORAGE_KEY)
  localStorage.removeItem(TOKEN_STORAGE_KEY)
  router.push('/login')
}

type ModuleId = 'workspace' | 'resource' | 'settings'
type ResourceSubModule = 'scenario' | 'dha' | 'skill' | 'mcp' | 'llm' | 'files'

const resourceChildren: { id: ResourceSubModule; label: string }[] = [
  { id: 'scenario', label: '场景' },
  { id: 'dha', label: '专家' },
  { id: 'skill', label: '技能' },
  { id: 'mcp', label: '工具' },
  { id: 'llm', label: '模型' },
  { id: 'files', label: '文件' },
]

const currentModule = ref<ModuleId>('workspace')
const resourceSubModule = ref<ResourceSubModule>('scenario')
const selectedId = ref<string | null>(null)
const resourceMenuExpanded = ref(false)

interface ScenarioPreset {
  id: string
  name: string
  agent_ids: string[]
  description?: string
}
type ScenarioDraft = {
  id: string
  name: string
  agent_ids: string[]
  description: string
}
const scenarioPresets = ref<ScenarioPreset[]>([])
const scenarioLoading = ref(false)
const scenarioSaving = ref(false)
const creatingScenarioId = ref<string | null>(null)
const scenarioSearch = ref('')
const scenarioExpertSearch = ref('')
const scenarioDraft = ref<ScenarioDraft>({
  id: '',
  name: '',
  agent_ids: [],
  description: '',
})
const isCreatingScenario = computed(() => !!selectedId.value && selectedId.value === creatingScenarioId.value)
const filteredScenarioPresets = computed(() => {
  const q = (scenarioSearch.value || '').trim().toLowerCase()
  const list = scenarioPresets.value || []
  if (!q) return list
  return list.filter((s) => `${s.name || ''} ${s.description || ''}`.toLowerCase().includes(q))
})
const selectedScenarioPreset = computed(() => {
  if (!selectedId.value) return null
  return scenarioPresets.value.find((x) => x.id === selectedId.value) || null
})
const scenarioAddableExperts = computed(() => {
  const selected = new Set(scenarioDraft.value.agent_ids || [])
  return (dhaInstances.value || []).filter((d) => !selected.has(d.agent_id))
})
const filteredScenarioAddableExperts = computed(() => {
  const q = (scenarioExpertSearch.value || '').trim().toLowerCase()
  const list = scenarioAddableExperts.value || []
  if (!q) return list
  return list.filter((d) => {
    const hay = `${d.name || ''} ${d.role || ''}`.toLowerCase()
    return hay.includes(q)
  })
})

const skills = ref<{ id: string; name: string; description?: string; enabled: boolean }[]>([])
const skillsLoading = ref(false)
const mcpServers = ref<{ id: string; name: string; description?: string; metadata?: Record<string, any>; status: string; tool_count: number }[]>([])
const mcpLoading = ref(false)
const llmDefault = ref<string>('qwen')
const llmProviders = ref<Record<string, { base_url?: string; model?: string; api_key_env?: string }>>({})
const llmLoading = ref(false)
const llmProviderIds = computed(() => Object.keys(llmProviders.value || {}))
const fileSessions = ref<{ id: string; title: string; updated_at: string; file_count: number }[]>([])
const fileSessionsLoading = ref(false)
const fileSessionSearch = ref('')
const fileSessionSort = ref<'updated_desc' | 'updated_asc'>('updated_desc')
const visibleFileSessions = computed(() => {
  const q = (fileSessionSearch.value || '').trim().toLowerCase()
  const list = (fileSessions.value || []).filter((s) => {
    if (!q) return true
    const title = (s.title || '').toLowerCase()
    return title.includes(q)
  })
  const arr = [...list]
  if (fileSessionSort.value === 'updated_desc') {
    arr.sort((a, b) => (b.updated_at || '').localeCompare(a.updated_at || ''))
  } else if (fileSessionSort.value === 'updated_asc') {
    arr.sort((a, b) => (a.updated_at || '').localeCompare(b.updated_at || ''))
  }
  return arr
})

// 资源中心列表搜索（专家 / Skill / MCP）
const showScenarioSearch = ref(false)
const showDhaSearch = ref(false)
const showSkillSearch = ref(false)
const showMcpSearch = ref(false)
const dhaSearch = ref('')
const skillSearch = ref('')
const mcpSearch = ref('')

function toggleSearch(kind: 'scenario' | 'dha' | 'skill' | 'mcp') {
  if (kind === 'scenario') {
    showScenarioSearch.value = !showScenarioSearch.value
    if (!showScenarioSearch.value) scenarioSearch.value = ''
  }
  if (kind === 'dha') {
    showDhaSearch.value = !showDhaSearch.value
    if (!showDhaSearch.value) dhaSearch.value = ''
  }
  if (kind === 'skill') {
    showSkillSearch.value = !showSkillSearch.value
    if (!showSkillSearch.value) skillSearch.value = ''
  }
  if (kind === 'mcp') {
    showMcpSearch.value = !showMcpSearch.value
    if (!showMcpSearch.value) mcpSearch.value = ''
  }
}

function _q(s: string) {
  return (s || '').trim().toLowerCase()
}

const filteredDhaInstances = computed(() => {
  const q = _q(dhaSearch.value)
  const list = dhaInstances.value || []
  if (!q) return list
  return list.filter((d) => {
    const hay = `${d.name || ''} ${d.role || ''}`.toLowerCase()
    return hay.includes(q)
  })
})

const filteredSkills = computed(() => {
  const q = _q(skillSearch.value)
  const list = skills.value || []
  if (!q) return list
  return list.filter((s) => {
    const hay = `${s.name || ''} ${s.description || ''}`.toLowerCase()
    return hay.includes(q)
  })
})

function mcpServerDescription(server: { description?: string; metadata?: Record<string, any> }) {
  const fromMetadata = server?.metadata && typeof server.metadata.description === 'string'
    ? server.metadata.description
    : ''
  return server.description || fromMetadata || ''
}

const filteredMcpServers = computed(() => {
  const q = _q(mcpSearch.value)
  const list = mcpServers.value || []
  if (!q) return list
  return list.filter((s) => {
    const hay = `${s.name || ''} ${mcpServerDescription(s)}`.toLowerCase()
    return hay.includes(q)
  })
})
const settingsCategories = [
  { id: 'app', label: '主持人设置' },
  { id: 'theme', label: '配色' },
  { id: 'account-security', label: '账号' },
]
// Group
const selectedGroupSessionId = ref<string | null>(null)
const groupSessions = ref<{ id: string; title: string; updated_at: string; agent_ids?: string[]; speak_mode?: string }[]>([])
const groupSessionsLoading = ref(false)
const creatingSession = ref(false)
const dhaInstances = ref<{ agent_id: string; name: string; role?: string; system_prompt?: string; skill_ids?: string[]; mcp_server_ids?: string[]; is_leader?: boolean }[]>([])
const dhaInstancesLoading = ref(false)
const skillZipInputRef = ref<HTMLInputElement | null>(null)
const skillZipImporting = ref(false)

// 中间列宽度（可拖动调整）
const middleColumnWidth = ref(240)
const middleColumnOpen = ref(true)
const middleColumnPrevWidth = ref(240)
let resizeStartX = 0
let resizeStartWidth = 240
const isResizingMiddle = ref(false)

function toggleMiddleColumn() {
  if (middleColumnOpen.value) {
    middleColumnPrevWidth.value = middleColumnWidth.value
    middleColumnOpen.value = false
  } else {
    middleColumnOpen.value = true
    middleColumnWidth.value = middleColumnPrevWidth.value || 240
  }
}

/** 群聊里收起中间列后，切到资源中心/设置需自动展开，否则侧栏无容器 */
function ensureMiddleColumnOpen() {
  if (!middleColumnOpen.value) {
    middleColumnOpen.value = true
    middleColumnWidth.value = middleColumnPrevWidth.value || 240
  }
}

function onMiddleResizeMouseDown(e: MouseEvent) {
  e.preventDefault()
  if (!middleColumnOpen.value) return
  isResizingMiddle.value = true
  resizeStartX = e.clientX
  resizeStartWidth = middleColumnWidth.value
  window.addEventListener('mousemove', onMiddleResizeMouseMove)
  window.addEventListener('mouseup', onMiddleResizeMouseUp)
}

function onMiddleResizeMouseMove(e: MouseEvent) {
  if (!isResizingMiddle.value) return
  const delta = e.clientX - resizeStartX
  const next = Math.min(420, Math.max(220, resizeStartWidth + delta))
  middleColumnWidth.value = next
}

function onMiddleResizeMouseUp() {
  if (!isResizingMiddle.value) return
  isResizingMiddle.value = false
  window.removeEventListener('mousemove', onMiddleResizeMouseMove)
  window.removeEventListener('mouseup', onMiddleResizeMouseUp)
}

onUnmounted(() => {
  window.removeEventListener('mousemove', onMiddleResizeMouseMove)
  window.removeEventListener('mouseup', onMiddleResizeMouseUp)
})

/** 会话列表展示用标题：为空或默认值时用更友好的「AI 命名」 */
function displaySessionTitle(s: { id: string; title: string; agent_ids?: string[]; updated_at: string }): string {
  const raw = (s.title || '').trim()
  if (!raw || raw === '新对话') {
    const dhaCount = s.agent_ids?.length || 0
    if (dhaCount === 0) return '空白会话'
    if (dhaCount === 1) return '单专家协作会话'
    if (dhaCount <= 3) return `${dhaCount} 专家协作会话`
    return `多专家协作会话`
  }
  return raw
}

const DHA_AVATAR_COLORS = [
  'var(--color-dha-box-0)',
  'var(--color-dha-box-1)',
  'var(--color-dha-box-2)',
  'var(--color-dha-box-3)',
  'var(--color-dha-box-4)',
  'var(--color-dha-box-5)',
  'var(--color-dha-box-6)',
  'var(--color-dha-box-7)',
]

function dhaAvatarColorForId(dhaId: string): string {
  const list = dhaInstances.value || []
  const idx = Math.max(
    0,
    list.findIndex((d) => d.agent_id === dhaId),
  )
  return DHA_AVATAR_COLORS[idx % DHA_AVATAR_COLORS.length]
}

function dhaAvatarCharForId(dhaId: string): string {
  const list = dhaInstances.value || []
  const found = list.find((d) => d.agent_id === dhaId)
  const name = (found?.name || dhaId || '?').trim()
  return name ? name.slice(0, 1).toUpperCase() : '?'
}


function formatDate(iso: string) {
  if (!iso) return ''
  try {
    const d = new Date(iso)
    return d.toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })
  } catch {
    return iso
  }
}

function onNavClick(moduleId: ModuleId) {
  if (moduleId === 'resource' && currentModule.value === 'resource') {
    resourceMenuExpanded.value = !resourceMenuExpanded.value
    return
  }
  currentModule.value = moduleId
  if (moduleId === 'resource') {
    resourceMenuExpanded.value = true
  } else {
    resourceMenuExpanded.value = false
  }
  selectedId.value = null
  if (moduleId === 'resource' || moduleId === 'settings') {
    ensureMiddleColumnOpen()
  }
  if (moduleId === 'workspace') {
    fetchGroupSessions()
    fetchDHA()
  }
  if (moduleId === 'resource') {
    fetchScenarioPresets()
    fetchDHA()
    fetchSkills()
    fetchMCP()
    fetchLLM()
    fetchFileSessions()
  }
}

function onResourceChildClick(id: ResourceSubModule) {
  currentModule.value = 'resource'
  resourceMenuExpanded.value = true
  resourceSubModule.value = id
}

function dhaDisplayName(dhaId: string): string {
  const hit = (dhaInstances.value || []).find((d) => d.agent_id === dhaId)
  return hit?.name || dhaId
}

function syncScenarioDraftFromSelected() {
  const s = selectedScenarioPreset.value
  if (!s) {
    scenarioDraft.value = { id: '', name: '', agent_ids: [], description: '' }
    return
  }
  scenarioDraft.value = {
    id: s.id,
    name: s.name || '',
    agent_ids: [...(s.agent_ids || [])],
    description: s.description || '',
  }
}

function createScenarioPreset() {
  const ts = Date.now().toString(36)
  const id = `scenario-${ts}`
  const next: ScenarioPreset = {
    id,
    name: '',
    agent_ids: [],
    description: '',
  }
  scenarioPresets.value = [next, ...(scenarioPresets.value || [])]
  selectedId.value = id
  creatingScenarioId.value = id
  syncScenarioDraftFromSelected()
}

function removeScenarioExpert(dhaId: string) {
  scenarioDraft.value.agent_ids = (scenarioDraft.value.agent_ids || []).filter((x) => x !== dhaId)
}

function addScenarioExpert(dhaId: string) {
  if (!dhaId) return
  if ((scenarioDraft.value.agent_ids || []).includes(dhaId)) return
  scenarioDraft.value.agent_ids = [...(scenarioDraft.value.agent_ids || []), dhaId]
}

async function persistScenarioPresets(nextPresets: ScenarioPreset[]) {
  const payload = {
    presets: nextPresets.map((p) => ({
      id: p.id,
      name: (p.name || '').trim(),
      agent_ids: [...(p.agent_ids || [])],
      description: p.description || '',
    })),
  }
  const r = await fetch('/api/settings/session-presets', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  const j = await r.json().catch(() => ({}))
  if (j?.status !== 'ok') {
    throw new Error((j as { detail?: string }).detail || '保存场景失败')
  }
  // 工作区侧栏仍挂载（v-show），需通知其重新拉取场景预设，否则快捷场景列表与专家名陈旧
  window.dispatchEvent(new CustomEvent('dha-session-presets-updated'))
}

async function saveScenarioPreset() {
  const cur = selectedScenarioPreset.value
  if (!cur) return
  const name = (scenarioDraft.value.name || '').trim()
  const dhaIds = [...(scenarioDraft.value.agent_ids || [])]
  if (!name) {
    window.alert('场景名称不能为空')
    return
  }
  if (!dhaIds.length) {
    window.alert('请至少选择 1 位专家')
    return
  }
  scenarioSaving.value = true
  try {
    const next = (scenarioPresets.value || []).map((p) =>
      p.id === cur.id
        ? {
            ...p,
            name,
            description: scenarioDraft.value.description || '',
            agent_ids: dhaIds,
          }
        : p,
    )
    await persistScenarioPresets(next)
    scenarioPresets.value = next
    if (creatingScenarioId.value === cur.id) creatingScenarioId.value = null
    syncScenarioDraftFromSelected()
  } catch (e) {
    window.alert((e as Error).message || '保存场景失败')
  } finally {
    scenarioSaving.value = false
  }
}

async function deleteScenarioPreset(id: string) {
  if (!id) return
  const target = (scenarioPresets.value || []).find((x) => x.id === id)
  const label = target?.name || id
  if (!window.confirm(`确定删除场景「${label}」吗？`)) return
  scenarioSaving.value = true
  try {
    const next = (scenarioPresets.value || []).filter((p) => p.id !== id)
    await persistScenarioPresets(next)
    scenarioPresets.value = next
    if (creatingScenarioId.value === id) creatingScenarioId.value = null
    if (selectedId.value === id) {
      selectedId.value = next[0]?.id || null
    }
    syncScenarioDraftFromSelected()
  } catch (e) {
    window.alert((e as Error).message || '删除场景失败')
  } finally {
    scenarioSaving.value = false
  }
}

async function fetchScenarioPresets() {
  scenarioLoading.value = true
  try {
    const r = await fetch('/api/settings/session-presets')
    const j = await r.json()
    if (j?.status === 'ok' && j?.data?.presets) {
      scenarioPresets.value = j.data.presets
    } else {
      scenarioPresets.value = []
    }
    if (resourceSubModule.value === 'scenario') {
      const ids = scenarioPresets.value.map((s) => s.id)
      if (selectedId.value && !ids.includes(selectedId.value)) {
        selectedId.value = ids[0] || null
      } else if (!selectedId.value) {
        selectedId.value = ids[0] || null
      }
      if (!selectedId.value || selectedId.value !== creatingScenarioId.value) {
        creatingScenarioId.value = null
      }
      syncScenarioDraftFromSelected()
    }
  } catch {
    scenarioPresets.value = []
    syncScenarioDraftFromSelected()
  } finally {
    scenarioLoading.value = false
  }
}

async function fetchSkills() {
  skillsLoading.value = true
  try {
    const r = await fetch('/api/settings/skills')
    const j = await r.json()
    if (j.status === 'ok' && j.data?.skills) {
      skills.value = j.data.skills
      // 资源中心 Skill：默认打开第一个，避免右侧空白。
      // 同时：当当前选中项不在列表里（被删除/过滤）时，回退到第一个。
      if (currentModule.value === 'resource' && resourceSubModule.value === 'skill') {
        const list = skills.value || []
        if (selectedId.value === '__new__') return
        const ids = list.map((s) => s.id)
        if (selectedId.value && !ids.includes(selectedId.value)) {
          selectedId.value = list.length > 0 ? list[0].id : null
        } else if (!selectedId.value && list.length > 0) {
          selectedId.value = list[0].id
        }
      }
    }
  } finally {
    skillsLoading.value = false
  }
}

async function fetchGroupSessions() {
  groupSessionsLoading.value = true
  try {
    const r = await fetch('/api/sessions')
    const j = await r.json()
    if (j.status === 'ok' && j.data?.sessions) {
      groupSessions.value = j.data.sessions
      const current = selectedGroupSessionId.value
      const ids = groupSessions.value.map((s) => s.id)
      if (current && !ids.includes(current)) {
        selectedGroupSessionId.value = groupSessions.value.length > 0 ? groupSessions.value[0].id : null
      } else if (!current && groupSessions.value.length > 0) {
        selectedGroupSessionId.value = groupSessions.value[0].id
      }
    }
  } finally {
    groupSessionsLoading.value = false
  }
}

const workspaceContentRef = ref<{ refresh: () => void } | null>(null)
async function onChatMessageSent() {
  workspaceContentRef.value?.refresh()
  await fetchGroupSessions()
}
function onGroupChatRefresh() {
  workspaceContentRef.value?.refresh()
}

/** 新加成员后：刷新当前会话详情并刷新左侧会话列表，使成员数立即更新 */
async function onDhaAdded() {
  workspaceContentRef.value?.refresh()
  await fetchGroupSessions()
}

async function createNewSession() {
  if (creatingSession.value) return
  creatingSession.value = true
  try {
    const r = await fetch('/api/sessions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: '新对话', agent_ids: [] }),
    })
    const j = await r.json()
    if (j.status === 'ok' && j.data?.id) {
      selectedGroupSessionId.value = j.data.id
      await fetchGroupSessions()
    } else {
      alert(j.detail || '新建会话失败')
    }
  } finally {
    creatingSession.value = false
  }
}

function selectGroupSession(id: string) {
  selectedGroupSessionId.value = id
}

async function deleteGroupSession(id: string) {
  if (!confirm('确定删除该会话？')) return
  const r = await fetch(`/api/sessions/${encodeURIComponent(id)}`, { method: 'DELETE' })
  const j = await r.json()
  if (j.status === 'ok') {
    if (selectedGroupSessionId.value === id) {
      selectedGroupSessionId.value = null
    }
    fetchGroupSessions()
  } else {
    alert(j.detail || '删除失败')
  }
}


async function renameGroupSession(id: string, currentTitle: string) {
  const next = prompt('重命名会话', currentTitle)
  if (next == null || next.trim() === '') return
  const r = await fetch(`/api/sessions/${encodeURIComponent(id)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title: next.trim() }),
  })
  const j = await r.json()
  if (j.status === 'ok') {
    fetchGroupSessions()
    if (selectedGroupSessionId.value === id) workspaceContentRef.value?.refresh()
  } else {
    alert(j.detail || '重命名失败')
  }
}

async function fetchDHA() {
  dhaInstancesLoading.value = true
  try {
    const r = await fetch('/api/agents')
    const j = await r.json()
    if (j.status === 'ok' && j.data?.instances) {
      dhaInstances.value = j.data.instances
      // 资源中心 专家：默认选中第一个，且当当前选中项失效时自动回退
      if (currentModule.value === 'resource' && resourceSubModule.value === 'dha') {
        const list = dhaInstances.value || []
        if (selectedId.value === '__new__') return
        const ids = list.map((d) => d.agent_id)
        if (selectedId.value && !ids.includes(selectedId.value)) {
          selectedId.value = list.length > 0 ? list[0].agent_id : null
        } else if (!selectedId.value && list.length > 0) {
          selectedId.value = list[0].agent_id
        }
      }
    }
  } catch {
    dhaInstances.value = []
  } finally {
    dhaInstancesLoading.value = false
  }
}

function onDHACreated(dhaId: string) {
  selectedId.value = dhaId
  fetchDHA()
}

async function deleteDhaInstance(dhaId: string) {
  if (!confirm('确定删除该专家？')) return
  const r = await fetch(`/api/agents/${encodeURIComponent(dhaId)}`, { method: 'DELETE' })
  const j = await r.json()
  if (j.status === 'ok') {
    if (selectedId.value === dhaId) selectedId.value = null
    fetchDHA()
  } else {
    alert(j.detail || '删除失败')
  }
}

async function fetchMCP() {
  mcpLoading.value = true
  try {
    const r = await fetch('/api/settings/mcp')
    const j = await r.json()
    if (j.status === 'ok' && j.data?.servers) {
      mcpServers.value = j.data.servers
      // 资源中心 工具：默认选中第一个，且当当前选中项失效时自动回退
      if (currentModule.value === 'resource' && resourceSubModule.value === 'mcp') {
        const list = mcpServers.value || []
        if (selectedId.value === '__new__') return
        const ids = list.map((s) => s.id)
        if (selectedId.value && !ids.includes(selectedId.value)) {
          selectedId.value = list.length > 0 ? list[0].id : null
        } else if (!selectedId.value && list.length > 0) {
          selectedId.value = list[0].id
        }
      }
    }
  } finally {
    mcpLoading.value = false
  }
}

async function fetchLLM() {
  llmLoading.value = true
  try {
    const r = await fetch('/api/settings/app')
    const j = await r.json()
    if (j?.status === 'ok' && j?.data) {
      llmDefault.value = j.data.default_llm || 'qwen'
      llmProviders.value = { ...(j.data.llm_providers || {}) }
      if (resourceSubModule.value === 'llm' && !selectedId.value) {
        selectedId.value = llmDefault.value
      }
    } else {
      llmDefault.value = 'qwen'
      llmProviders.value = {}
    }
  } catch {
    llmDefault.value = 'qwen'
    llmProviders.value = {}
  } finally {
    llmLoading.value = false
  }
}

async function fetchFileSessions() {
  fileSessionsLoading.value = true
  try {
    const r = await fetch('/api/workspaces/sessions-with-files')
    if (r.ok) {
      const j = await r.json()
      if (j?.status === 'ok' && j?.data?.sessions) {
        fileSessions.value = j.data.sessions
      } else {
        fileSessions.value = []
      }
    } else {
      // 兼容后端尚未重启到新路由的场景：前端本地回退计算“有文件会话”
      const sRes = await fetch('/api/sessions')
      const sJson = await sRes.json()
      const sessions = (sJson?.status === 'ok' ? (sJson?.data?.sessions || []) : []) as Array<{ id: string; title?: string; updated_at?: string }>
      const withFiles: { id: string; title: string; updated_at: string; file_count: number }[] = []
      for (const s of sessions) {
        const fr = await fetch(`/api/workspaces/${encodeURIComponent(s.id)}/files`)
        if (!fr.ok) continue
        const fj = await fr.json()
        const entries = (fj?.status === 'ok' ? (fj?.data?.entries || []) : []) as Array<{ is_dir?: boolean }>
        const fileCount = entries.filter((e) => !e.is_dir).length
        if (fileCount > 0) {
          withFiles.push({
            id: s.id,
            title: s.title || '新对话',
            updated_at: s.updated_at || '',
            file_count: fileCount,
          })
        }
      }
      fileSessions.value = withFiles
    }
    if (resourceSubModule.value === 'files') {
      const ids = visibleFileSessions.value.map((s) => s.id)
      if (selectedId.value && !ids.includes(selectedId.value)) {
        selectedId.value = ids[0] || null
      } else if (!selectedId.value) {
        selectedId.value = ids[0] || null
      }
    }
  } catch {
    fileSessions.value = []
  } finally {
    fileSessionsLoading.value = false
  }
}

function triggerSkillZipImport() {
  const ok = window.confirm('仅支持导入 ZIP 文件，且 ZIP 根目录必须包含 SKILL.md。确认后请选择 ZIP 文件。')
  if (!ok) return
  if (skillZipImporting.value) return
  skillZipInputRef.value?.click()
}

async function onSkillZipSelected(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  const isZip = file.name.toLowerCase().endsWith('.zip') || file.type === 'application/zip' || file.type === 'application/x-zip-compressed'
  if (!isZip) {
    window.alert('仅支持导入 ZIP 文件')
    return
  }
  if (skillZipImporting.value) return
  skillZipImporting.value = true
  try {
    const fd = new FormData()
    fd.append('file', file)
    fd.append('enabled', 'true')
    const r = await fetch('/api/settings/skills/import-zip', {
      method: 'POST',
      body: fd,
    })
    const j = await r.json().catch(() => ({}))
    if (j?.status === 'ok' && j?.data?.id) {
      await fetchSkills()
      selectedId.value = j.data.id
    } else {
      window.alert(j?.detail || '导入技能失败')
    }
  } catch (err) {
    console.error(err)
    window.alert('导入技能失败，请检查网络或 ZIP 格式')
  } finally {
    skillZipImporting.value = false
  }
}

async function createEmptySkill() {
  try {
    const r = await fetch('/api/settings/skills', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: '新 Skill',
        description: '',
        source: 'local',
        enabled: true,
      }),
    })
    const j = await r.json()
    if (j.status === 'ok' && j.data?.id) {
      selectedId.value = j.data.id
      await fetchSkills()
    } else {
      alert(j.detail || '新建 Skill 失败')
    }
  } catch (e) {
    console.error(e)
    alert('新建 Skill 失败')
  }
}

function onMCPCreated(id: string) {
  selectedId.value = id
  fetchMCP()
}

watch(currentModule, (mod) => {
  if (mod !== 'resource') selectedId.value = null
  if (mod === 'resource') {
    if (resourceSubModule.value === 'scenario') fetchScenarioPresets()
    if (resourceSubModule.value === 'skill') fetchSkills()
    if (resourceSubModule.value === 'mcp') fetchMCP()
    if (resourceSubModule.value === 'dha') fetchDHA()
    if (resourceSubModule.value === 'llm') fetchLLM()
    if (resourceSubModule.value === 'files') fetchFileSessions()
  }
  if (mod === 'settings') selectedId.value = 'app'
  if (mod === 'workspace') {
    fetchGroupSessions()
    fetchDHA()
  }
}, { immediate: true })

watch(resourceSubModule, (sub) => {
  selectedId.value = null
  // 切换子栏目时收起搜索，避免“跨栏目残留过滤”造成误解
  showDhaSearch.value = false
  showSkillSearch.value = false
  showMcpSearch.value = false
  dhaSearch.value = ''
  skillSearch.value = ''
  mcpSearch.value = ''
  scenarioSearch.value = ''
  if (sub === 'scenario') fetchScenarioPresets()
  if (sub === 'dha') fetchDHA()
  if (sub === 'skill') fetchSkills()
  if (sub === 'mcp') fetchMCP()
  if (sub === 'llm') fetchLLM()
  if (sub === 'files') fetchFileSessions()
})

watch(selectedScenarioPreset, () => {
  if (resourceSubModule.value !== 'scenario') return
  syncScenarioDraftFromSelected()
})

// 初始加载：切到对应模块时再请求数据
</script>
