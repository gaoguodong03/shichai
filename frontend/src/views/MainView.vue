<template>
  <div
    v-if="scenarioShareRouteImportLoading"
    class="fixed top-0 left-0 right-0 z-[300] px-4 py-2 text-center text-sm bg-accent text-text-inverse shadow"
  >
    正在加载分享场景…
  </div>
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
            :data-session-id="s.id"
            @click="selectGroupSession(s.id)"
            :class="[
              'w-full flex items-center gap-1 px-3 py-2.5 rounded-lg text-sm transition-colors cursor-pointer group',
              selectedGroupSessionId === s.id ? 'bg-accent-subtle text-accent-subtle-text' : 'hover:bg-list-hover text-list-hover-text'
            ]"
          >
            <div class="flex-1 min-w-0 text-left">
              <div class="flex items-center gap-1.5 min-w-0">
                <div class="truncate font-medium">{{ displaySessionTitle(s) }}</div>
                <span
                  v-if="sessionNotice(s.id).running"
                  class="session-running-spinner"
                  role="status"
                  aria-label="会话正在运行"
                  title="会话正在运行"
                />
                <span
                  v-else-if="sessionNotice(s.id).hasUpdate"
                  class="session-unread-dot"
                  aria-label="会话有新回复"
                  title="会话有新回复"
                />
              </div>
              <div class="mt-0.5 flex items-center gap-1">
                <template v-if="(s.agent_ids?.length || 0) > 0">
                  <div class="flex -space-x-1">
                    <span
                      v-for="id in (s.agent_ids || []).slice(0, 3)"
                      :key="id"
                      class="inline-flex items-center justify-center w-5 h-5 rounded-full text-[10px] font-semibold shrink-0 ring-1 ring-sidebar overflow-hidden"
                      :class="dhaAvatarImgUrlForSession(id) ? '' : 'text-text-inverse'"
                      :style="dhaAvatarImgUrlForSession(id) ? {} : { backgroundColor: dhaAvatarColorForId(id) }"
                    >
                      <img
                        v-if="dhaAvatarImgUrlForSession(id)"
                        :src="dhaAvatarImgUrlForSession(id)!"
                        alt=""
                        class="w-full h-full object-cover"
                      />
                      <template v-else>{{ dhaAvatarCharForId(id) }}</template>
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
            <div class="mb-2 px-3 space-y-2">
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
                  title="导入场景包（ZIP）"
                  @click="pickScenarioImportFile"
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
                    stroke-width="1.8"
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
              <input
                ref="scenarioImportFileInputRef"
                type="file"
                accept=".zip,application/zip"
                class="hidden"
                @change="onScenarioImportFile"
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
                <div class="truncate text-xs text-muted mt-0.5">{{ (s.agent_ids || []).length }} 位专家</div>
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
          <template v-else-if="resourceSubModule === 'agent'">
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
                  title="导入专家包（ZIP）"
                  @click="pickDhaImportFile"
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
                <button
                  type="button"
                  class="w-10 h-10 rounded-xl bg-list-hover text-primary hover:bg-nav-hover-bg transition-colors flex items-center justify-center"
                  title="搜索专家"
                  @click="toggleSearch('agent')"
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
                    <circle cx="11" cy="11" r="7" />
                    <path d="M20 20l-3.5-3.5" />
                  </svg>
                </button>
              </div>
            </div>
            <input
              ref="dhaImportFileInputRef"
              type="file"
              accept=".zip,application/zip"
              class="hidden"
              @change="onDhaImportFile"
            />
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
              <div
                class="shrink-0 w-9 h-9 rounded-xl border border-border-light overflow-hidden bg-page flex items-center justify-center text-muted text-sm font-semibold"
              >
                <img
                  v-if="d.avatar_url"
                  :src="d.avatar_url"
                  alt=""
                  class="w-full h-full object-cover"
                />
                <span v-else>{{ (d.name || d.agent_id || '?').trim().charAt(0) || '?' }}</span>
              </div>
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
                    stroke-width="1.8"
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
                  title="导入工具"
                  :disabled="mcpZipImporting"
                  @click="triggerMcpZipImport"
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
                  ref="mcpZipInputRef"
                  type="file"
                  accept=".zip,application/zip"
                  class="hidden"
                  @change="onMcpZipSelected"
                />
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
                    stroke-width="1.8"
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
            @click="router.push(settingsRoutePath(c.id))"
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
          :skills="skills"
          :middle-column-open="middleColumnOpen"
          @middle-column-open-request="middleColumnOpen = true"
          @middle-column-toggle="toggleMiddleColumn"
          @message-sent="onChatMessageSent"
          @session-run-state="onSessionRunState"
          @scenario-new-session="onScenarioNewSession"
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
              <form class="space-y-6 bg-card backdrop-blur rounded-xl border border-border-light shadow-sm px-5 py-6 text-left">
                <div>
                  <label class="block text-sm font-medium text-primary mb-1">名称</label>
                  <input
                    v-model="scenarioDraft.name"
                    type="text"
                    class="w-full bg-input-bg text-primary border border-input-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-input-focus-ring focus:border-input-focus-ring"
                    placeholder="请输入场景名称"
                  />
                </div>
                <div>
                  <label class="block text-sm font-medium text-primary mb-1">描述</label>
                  <textarea
                    v-model="scenarioDraft.description"
                    rows="3"
                    class="w-full bg-input-bg text-primary border border-input-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-input-focus-ring focus:border-input-focus-ring resize-y"
                    placeholder="请输入场景描述"
                  />
                </div>
                <div class="border border-border-light rounded-lg px-5 py-6 space-y-6">
                  <label class="block text-sm font-medium text-primary mb-2">场景主持人</label>
                  <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div>
                      <label class="block text-sm font-medium text-primary mb-1">名称</label>
                      <input
                        v-model="scenarioLeaderDisplayName"
                        type="text"
                        class="w-full bg-input-bg text-primary border border-input-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-input-focus-ring focus:border-input-focus-ring"
                        placeholder="例如：四九"
                      />
                    </div>
                    <div>
                      <label class="block text-sm font-medium text-primary mb-1">大模型（可选）</label>
                      <select
                        v-model="scenarioLeaderLlmId"
                        class="w-full border border-input-border rounded-lg px-3 py-2 text-sm bg-input-bg text-primary focus:outline-none focus:ring-2 focus:ring-input-focus-ring focus:border-input-focus-ring"
                      >
                        <option value="">使用应用默认</option>
                        <option v-for="pid in llmProviderIds" :key="pid" :value="pid">
                          {{ scenarioLlmOptionLabel(pid) }}
                        </option>
                      </select>
                    </div>
                  </div>
                  <div>
                    <label class="block text-sm font-medium text-primary mb-1">系统提示词（可选）</label>
                    <textarea
                      v-model="scenarioLeaderSystemPrompt"
                      rows="6"
                      class="w-full bg-input-bg text-primary border border-input-border rounded-lg px-3 py-2 text-sm leading-relaxed resize-y themed-scrollbar focus:outline-none focus:ring-2 focus:ring-input-focus-ring focus:border-input-focus-ring"
                      placeholder="例如：你是群聊主持人，只负责决定下一位发言人与 next_prompt，不代写专家正文。"
                    />
                  </div>
                  <div>
                    <label class="block text-sm font-medium text-primary mb-2">技能与基础能力</label>
                    <div class="text-xs font-medium text-muted mb-1.5">技能</div>
                    <input
                      v-if="skills.length"
                      v-model.trim="scenarioLeaderSkillSearch"
                      type="text"
                      class="w-full mb-2 bg-input-bg text-primary border border-input-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-input-focus-ring focus:border-input-focus-ring"
                      placeholder="搜索技能（名称/描述）"
                    />
                    <div
                      v-if="skills.length"
                      class="flex flex-wrap items-start justify-start content-start gap-2 rounded-lg bg-page border border-border-light px-3 py-3"
                    >
                      <button
                        v-for="sk in filteredScenarioLeaderSkills"
                        :key="sk.id"
                        type="button"
                        class="px-3 py-1.5 rounded-full text-xs font-medium transition-colors border"
                        :class="scenarioLeaderSkillIds.includes(sk.id)
                          ? 'bg-accent-subtle text-accent-subtle-text border-accent/40 shadow-sm'
                          : 'bg-card text-muted border-border-light hover:bg-list-hover'"
                        @click="toggleScenarioLeaderSkill(sk.id)"
                      >
                        {{ sk.name || sk.id }}
                      </button>
                    </div>
                    <p v-if="skills.length && !filteredScenarioLeaderSkills.length" class="text-xs text-muted">没有匹配的 Skill</p>
                    <p v-else-if="!skills.length" class="text-xs text-muted">当前技能库为空，请先到左侧“技能”中新建或导入 Skill。</p>
                    <div v-if="missingScenarioLeaderSkillRefs.length" class="mt-3">
                      <div class="text-xs font-medium text-red-600 mb-1.5">缺失技能</div>
                      <div class="flex flex-wrap gap-2">
                        <span
                          v-for="item in missingScenarioLeaderSkillRefs"
                          :key="item.id"
                          class="inline-flex items-center px-3 py-1.5 rounded-full text-xs font-medium border border-red-300 bg-red-50 text-red-700"
                          :title="`缺失技能 ID：${item.id}`"
                        >
                          {{ item.name }}
                        </span>
                      </div>
                    </div>
                  </div>
                </div>
                <div>
                  <label class="block text-sm font-medium text-primary mb-2">协作专家</label>
                  <div class="flex flex-wrap gap-2">
                    <span
                      v-for="id in scenarioDraft.agent_ids || []"
                      :key="id"
                      class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium border"
                      :class="scenarioExpertMissing(id)
                        ? 'border-red-300 bg-red-50 text-red-700'
                        : 'border-accent/40 bg-accent-subtle text-accent-subtle-text'"
                      :title="scenarioExpertMissing(id) ? `缺失专家 ID：${id}` : '已选择专家'"
                    >
                      {{ dhaDisplayName(id, scenarioDraft.agent_refs) }}
                      <button
                        type="button"
                        class="ml-0.5 hover:text-danger"
                        :class="scenarioExpertMissing(id) ? 'text-red-700/80' : 'text-accent-subtle-text/80'"
                        @click="removeScenarioExpert(id)"
                      >×</button>
                    </span>
                    <span v-if="!(scenarioDraft.agent_ids || []).length" class="text-xs text-muted">暂无专家</span>
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
                        class="px-3 py-1.5 rounded-full text-xs font-medium transition-colors border border-border-light bg-card text-muted hover:bg-list-hover"
                        @click="addScenarioExpert(d.agent_id)"
                      >
                        + {{ d.name || d.agent_id }}
                      </button>
                      <span v-if="!scenarioAddableExperts.length" class="text-xs text-muted">可添加专家已为空</span>
                      <span v-else-if="!filteredScenarioAddableExperts.length" class="text-xs text-muted">无匹配专家</span>
                    </div>
                    <div v-if="missingScenarioExpertRefs.length" class="mt-3">
                      <div class="text-xs font-medium text-red-600 mb-1.5">缺失专家</div>
                      <div class="flex flex-wrap gap-2">
                        <span
                          v-for="item in missingScenarioExpertRefs"
                          :key="item.id"
                          class="inline-flex items-center px-3 py-1.5 rounded-full text-xs font-medium border border-red-300 bg-red-50 text-red-700"
                          :title="`缺失专家 ID：${item.id}`"
                        >
                          {{ item.name }}
                        </span>
                      </div>
                    </div>
                  </div>
                </div>
                <div v-if="!isCreatingScenario" class="space-y-2 pt-1 border-t border-border-light">
                  <div class="text-sm font-medium text-primary">访问方式</div>
                  <div v-if="scenarioShareAutoPublishing" class="text-sm text-muted py-1">
                    正在生成推广链接…
                  </div>
                  <template v-else-if="scenarioShareFullUrl">
                    <div
                      class="rounded-lg bg-accent-subtle/80 dark:bg-input-bg/40 border border-border-light px-3 py-2.5"
                    >
                      <a
                        :href="scenarioShareFullUrl"
                        target="_blank"
                        rel="noopener noreferrer"
                        class="text-blue-600 dark:text-blue-400 hover:underline break-all text-sm leading-relaxed"
                      >{{ scenarioShareFullUrl }}</a>
                    </div>
                  </template>
                  <p v-else class="text-xs text-muted">
                    请先填写名称、至少选择一位协作专家并保存，系统将自动生成固定推广链接。
                  </p>
                </div>
                <div class="flex items-center justify-start gap-2 pt-3 flex-shrink-0 flex-wrap">
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
                    class="inline-flex items-center justify-center px-4 py-2 text-sm font-medium rounded-lg bg-list-hover text-primary border border-border-light hover:bg-nav-hover-bg disabled:opacity-50"
                    :disabled="scenarioSaving || isCreatingScenario"
                    title="导出 ZIP 场景包（含专家、技能、MCP 与场景）"
                    @click="exportScenarioBundle"
                  >
                    导出
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
        <template v-else-if="resourceSubModule === 'agent'">
          <DHAView
            :selected-dha-id="selectedId"
            :dha-instances="dhaInstances"
            @created="onDHACreated"
            @updated="fetchDHA"
            @cancel="selectedId = null"
          />
        </template>
        <template v-else-if="resourceSubModule === 'skill' && selectedId">
          <SkillDetailView
            :skill-id="selectedId"
            @updated="
              (newId?: string) => {
                fetchSkills({ silent: true })
                if (newId) selectedId = newId
              }
            "
            @deleted="selectedId = null; fetchSkills()"
          />
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
          <MCPDetailView :server-id="selectedId" @updated="fetchMCP({ silent: true })" @deleted="selectedId = null; fetchMCP()" />
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
        <ApiSecretsSettingsView v-else-if="selectedId === 'secrets'" />
        <UserPreferenceSettingsView v-else-if="selectedId === 'user'" />
        <AccountSecuritySettingsView v-else-if="selectedId === 'account-security'" />
        <SandboxSettingsView v-else-if="selectedId === 'sandbox'" />
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

    <!-- 通用分享预览与导入 -->
    <div
      v-if="sharePreviewModalOpen"
      class="fixed inset-0 z-[320] flex items-center justify-center p-4 bg-black/50"
      role="dialog"
      aria-modal="true"
      aria-labelledby="share-preview-title"
      @click.self="onSharePreviewBackdropClick"
    >
      <div
        class="max-w-2xl w-full max-h-[88vh] overflow-y-auto rounded-xl border border-border-light bg-card shadow-xl p-5 text-primary themed-scrollbar relative"
        @click.stop
      >
        <div
          v-if="sharePreviewCommitting"
          class="absolute inset-0 z-[25] flex flex-col items-center justify-center gap-3 rounded-xl bg-card/90 backdrop-blur-sm"
          aria-live="polite"
          aria-busy="true"
        >
          <span class="inline-block h-9 w-9 rounded-full border-2 border-accent border-t-transparent animate-spin" aria-hidden="true" />
          <p class="text-sm font-medium text-primary">正在导入分享内容…</p>
        </div>
        <template v-if="sharePreviewResult">
          <h3 id="share-preview-title" class="text-lg font-semibold mb-3">
            {{ sharePreviewResult.ok ? '导入成功' : '导入失败' }}
          </h3>
          <p
            class="text-sm mb-4 whitespace-pre-wrap"
            :class="sharePreviewResult.ok ? 'text-primary' : 'text-danger'"
          >
            {{ sharePreviewResult.message }}
          </p>
          <div class="flex justify-start">
            <button
              type="button"
              class="px-4 py-2 text-sm rounded-lg bg-accent text-text-inverse hover:bg-accent-hover"
              @click="closeSharePreviewModal"
            >
              关闭
            </button>
          </div>
        </template>
        <template v-else>
          <h3 id="share-preview-title" class="text-lg font-semibold mb-3">分享预览</h3>
          <div class="mb-4 space-y-3 text-sm border border-border-light rounded-lg p-3 bg-page">
            <div class="flex items-center gap-2">
              <span class="text-xs px-2 py-0.5 rounded-full bg-accent-subtle text-accent-subtle-text">
                {{ sharePreviewData?.meta?.object_type || 'unknown' }}
              </span>
              <span class="font-medium text-primary truncate">{{ sharePreviewData?.meta?.title || '未命名分享' }}</span>
            </div>
            <div class="text-xs text-muted">分享 ID：<span class="font-mono text-primary">{{ sharePreviewData?.share_id || '-' }}</span></div>
            <div v-if="isShareScenePreview(sharePreviewData)" class="space-y-2">
              <div class="font-medium text-primary">{{ shareScenePreview(sharePreviewData)?.preset_name || sharePreviewData?.meta?.title || '未命名场景' }}</div>
              <div class="text-xs text-muted">场景名称：{{ shareScenePreview(sharePreviewData)?.preset_name || sharePreviewData?.meta?.title || '未命名场景' }}</div>
              <div v-if="(shareScenePreview(sharePreviewData)?.experts || []).length" class="pt-2">
                <div class="text-xs font-medium text-muted mb-1">包内专家</div>
                <ul class="list-disc pl-4 text-muted space-y-0.5">
                  <li v-for="ex in shareScenePreview(sharePreviewData)?.experts || []" :key="ex.agent_id">
                    <span class="text-primary">{{ ex.name || ex.agent_id }}</span>
                  </li>
                </ul>
              </div>
              <div v-if="(shareScenePreview(sharePreviewData)?.skills || []).length" class="pt-2">
                <div class="text-xs font-medium text-muted mb-1">包内技能</div>
                <p class="text-xs text-primary">{{ displaySkillNames(shareScenePreview(sharePreviewData)?.skills || []).join('，') }}</p>
              </div>
              <div v-if="(shareScenePreview(sharePreviewData)?.mcps || []).length" class="pt-2">
                <div class="text-xs font-medium text-muted mb-1">包内 MCP</div>
                <ul class="list-disc pl-4 text-muted space-y-0.5">
                  <li v-for="m in shareScenePreview(sharePreviewData)?.mcps || []" :key="m.id">
                    <span class="font-mono text-primary">{{ m.id }}</span> {{ m.name }}
                  </li>
                </ul>
              </div>
              <p v-if="shareSceneOverwriteSummary" class="text-xs text-amber-700 dark:text-amber-400 pt-2 whitespace-pre-line">
                将覆盖已有内容：{{ shareSceneOverwriteSummary }}
              </p>
            </div>
            <div v-else class="rounded-md border border-border-light p-3 bg-card">
              <div class="text-xs font-medium text-muted mb-2">分享内容</div>
              <ul v-if="sharePreviewSummaryItems.length" class="space-y-1 text-xs text-primary">
                <li v-for="item in sharePreviewSummaryItems" :key="item.label">
                  <span class="text-muted">{{ item.label }}：</span>{{ item.value }}
                </li>
              </ul>
              <p v-else class="text-xs text-muted">该分享可导入到当前账号。</p>
            </div>
            <div
              v-if="hasImportMissingReferences(sharePreviewMissingReferences)"
              class="rounded-lg border border-red-300 bg-red-50 px-3 py-2 text-red-700 dark:bg-red-950/20 dark:border-red-500/50 dark:text-red-300"
            >
              <div class="text-xs font-medium mb-1">缺失内容</div>
              <div class="space-y-2">
                <div v-for="group in missingReferenceGroups(sharePreviewMissingReferences)" :key="group.key">
                  <div class="text-xs font-medium">{{ group.label }}</div>
                  <ul class="mt-1 list-disc pl-4 text-xs space-y-0.5">
                    <li v-for="item in group.items" :key="`${group.key}-${item.source}-${item.id}`">
                      <span>{{ missingReferenceTitle(group, item) }}</span>
                      <span class="font-mono text-red-600 dark:text-red-300">（{{ item.id }}）</span>
                      <span v-if="missingRequiredByText(item)" class="text-red-600 dark:text-red-300">
                        ，被 {{ missingRequiredByText(item) }} 依赖
                      </span>
                    </li>
                  </ul>
                </div>
              </div>
              <p class="mt-2 text-xs">这些内容不会阻止导入，但导入后相关场景、专家或技能可能需要手动补齐。</p>
            </div>
          </div>
          <div class="flex justify-start gap-2">
            <button
              type="button"
              class="px-4 py-2 text-sm rounded-lg bg-accent text-text-inverse hover:bg-accent-hover disabled:opacity-50"
              :disabled="sharePreviewLoading || sharePreviewCommitting"
              @click="commitSharePreviewImport"
            >
              {{ sharePreviewCommitting ? '导入中…' : '确认导入' }}
            </button>
            <button
              type="button"
              class="px-4 py-2 text-sm rounded-lg border border-border-light bg-card hover:bg-list-hover disabled:opacity-50"
              :disabled="sharePreviewCommitting"
              @click="closeSharePreviewModal"
            >
              取消
            </button>
          </div>
        </template>
      </div>
    </div>

    <!-- 场景导入：依赖校验与确认 -->
    <div
      v-if="scenarioImportModalOpen"
      class="fixed inset-0 z-[300] flex items-center justify-center p-4 bg-black/50"
      role="dialog"
      aria-modal="true"
      aria-labelledby="scenario-import-title"
      @click.self="onScenarioImportBackdropClick"
    >
      <div
        class="max-w-lg w-full max-h-[85vh] overflow-y-auto rounded-xl border border-border-light bg-card shadow-xl p-5 text-primary themed-scrollbar relative"
        @click.stop
      >
        <div
          v-if="scenarioImportCommitting"
          class="absolute inset-0 z-[25] flex flex-col items-center justify-center gap-3 rounded-xl bg-card/90 backdrop-blur-sm"
          aria-live="polite"
          aria-busy="true"
        >
          <span
            class="inline-block h-9 w-9 rounded-full border-2 border-accent border-t-transparent animate-spin"
            aria-hidden="true"
          />
          <p class="text-sm font-medium text-primary">正在导入…</p>
          <p class="text-xs text-muted px-4 text-center">请勿关闭页面，导入完成后将在此显示结果</p>
        </div>
        <template v-if="scenarioImportResult">
          <h3 id="scenario-import-title" class="text-lg font-semibold mb-3">
            {{ scenarioImportResult.ok ? '导入成功' : '导入失败' }}
          </h3>
          <p
            class="text-sm mb-4 whitespace-pre-wrap"
            :class="scenarioImportResult.ok ? 'text-primary' : 'text-danger'"
          >
            {{ scenarioImportResult.message }}
          </p>
          <div class="flex justify-start">
            <button
              type="button"
              class="px-4 py-2 text-sm rounded-lg bg-accent text-text-inverse hover:bg-accent-hover"
              @click="closeScenarioImportModal"
            >
              关闭
            </button>
          </div>
        </template>
        <template v-else>
        <h3 id="scenario-import-title" class="text-lg font-semibold mb-3">导入场景</h3>
        <template v-if="scenarioBundlePreview?.bundle_preview">
          <div class="mb-4 space-y-2 text-sm border border-border-light rounded-lg p-3 bg-page">
            <div class="font-medium text-primary">{{ scenarioBundlePreview.bundle_preview.preset_name }}</div>
            <div class="text-xs text-muted">场景名称：{{ scenarioBundlePreview.bundle_preview.preset_name }}</div>
            <div v-if="(scenarioBundlePreview.bundle_preview.experts || []).length" class="pt-2">
              <div class="text-xs font-medium text-muted mb-1">包内专家</div>
              <ul class="list-disc pl-4 text-muted space-y-0.5">
                <li v-for="ex in scenarioBundlePreview.bundle_preview.experts" :key="ex.agent_id">
                  <span class="text-primary">{{ ex.name || ex.agent_id }}</span>
                </li>
              </ul>
            </div>
            <div v-if="(scenarioBundlePreview.bundle_preview.skills || []).length" class="pt-2">
              <div class="text-xs font-medium text-muted mb-1">包内技能</div>
              <p class="text-xs text-primary">{{ displaySkillNames(scenarioBundlePreview.bundle_preview.skills || []).join('，') }}</p>
            </div>
            <div v-if="(scenarioBundlePreview.bundle_preview.mcps || []).length" class="pt-2">
              <div class="text-xs font-medium text-muted mb-1">包内 MCP</div>
              <ul class="list-disc pl-4 text-muted space-y-0.5">
                <li v-for="m in scenarioBundlePreview.bundle_preview.mcps" :key="m.id">
                  <span class="font-mono text-primary">{{ m.id }}</span> {{ m.name }}
                </li>
              </ul>
            </div>
            <div
              v-if="hasImportMissingReferences(scenarioBundlePreview.bundle_preview.missing_references)"
              class="rounded-lg border border-red-300 bg-red-50 px-3 py-2 text-red-700 dark:bg-red-950/20 dark:border-red-500/50 dark:text-red-300"
            >
              <div class="text-xs font-medium mb-1">缺失内容</div>
              <div class="space-y-2">
                <div v-for="group in missingReferenceGroups(scenarioBundlePreview.bundle_preview.missing_references)" :key="group.key">
                  <div class="text-xs font-medium">{{ group.label }}</div>
                  <ul class="mt-1 list-disc pl-4 text-xs space-y-0.5">
                    <li v-for="item in group.items" :key="`${group.key}-${item.source}-${item.id}`">
                      <span>{{ missingReferenceTitle(group, item) }}</span>
                      <span class="font-mono text-red-600 dark:text-red-300">（{{ item.id }}）</span>
                      <span v-if="missingRequiredByText(item)" class="text-red-600 dark:text-red-300">
                        ，被 {{ missingRequiredByText(item) }} 依赖
                      </span>
                    </li>
                  </ul>
                </div>
              </div>
              <p class="mt-2 text-xs">这些内容不会阻止导入，但导入后相关场景、专家或技能可能需要手动补齐。</p>
            </div>
            <p v-if="scenarioOverwriteSummary" class="text-xs text-amber-700 dark:text-amber-400 pt-2 whitespace-pre-line">
              将覆盖已有内容：{{ scenarioOverwriteSummary }}
            </p>
          </div>
        </template>
        <div class="flex justify-start gap-2">
          <button
            type="button"
            class="px-4 py-2 text-sm rounded-lg bg-accent text-text-inverse hover:bg-accent-hover disabled:opacity-50"
            :disabled="scenarioImportCommitting || !canConfirmScenarioImport"
            @click="commitScenarioImport"
          >
            {{ scenarioImportCommitting ? '导入中…' : hasScenarioNameConflict ? '确认覆盖导入' : '确认导入' }}
          </button>
          <button
            type="button"
            class="px-4 py-2 text-sm rounded-lg border border-border-light bg-card hover:bg-list-hover disabled:opacity-50"
            :disabled="scenarioImportCommitting"
            @click="closeScenarioImportModal"
          >
            取消
          </button>
        </div>
        </template>
      </div>
    </div>

    <!-- 专家导入 -->
    <div
      v-if="dhaImportModalOpen"
      class="fixed inset-0 z-[300] flex items-center justify-center p-4 bg-black/50"
      role="dialog"
      aria-modal="true"
      @click.self="onDhaImportBackdropClick"
    >
      <div
        class="max-w-lg w-full max-h-[85vh] overflow-y-auto rounded-xl border border-border-light bg-card shadow-xl p-5 text-primary themed-scrollbar relative"
        @click.stop
      >
        <div
          v-if="dhaImportCommitting"
          class="absolute inset-0 z-[25] flex flex-col items-center justify-center gap-3 rounded-xl bg-card/90 backdrop-blur-sm"
          aria-live="polite"
          aria-busy="true"
        >
          <span
            class="inline-block h-9 w-9 rounded-full border-2 border-accent border-t-transparent animate-spin"
            aria-hidden="true"
          />
          <p class="text-sm font-medium text-primary">正在导入…</p>
          <p class="text-xs text-muted px-4 text-center">请勿关闭页面，导入完成后将在此显示结果</p>
        </div>
        <template v-if="dhaImportResult">
          <h3 class="text-lg font-semibold mb-3">{{ dhaImportResult.ok ? '导入成功' : '导入失败' }}</h3>
          <p
            class="text-sm mb-4 whitespace-pre-wrap"
            :class="dhaImportResult.ok ? 'text-primary' : 'text-danger'"
          >
            {{ dhaImportResult.message }}
          </p>
          <div class="flex justify-start">
            <button
              type="button"
              class="px-4 py-2 text-sm rounded-lg bg-accent text-text-inverse hover:bg-accent-hover"
              @click="closeDhaImportModal"
            >
              关闭
            </button>
          </div>
        </template>
        <template v-else>
        <h3 class="text-lg font-semibold mb-3">导入专家</h3>
        <template v-if="dhaBundlePreview?.bundle_preview">
          <div class="mb-4 space-y-2 text-sm border border-border-light rounded-lg p-3 bg-page">
            <div class="font-medium text-primary">{{ dhaBundlePreview.bundle_preview.name }}</div>
            <div class="text-xs text-muted">专家名称：{{ dhaBundlePreview.bundle_preview.name || '未命名专家' }}</div>
            <div v-if="(dhaBundlePreview.bundle_preview.skills || []).length" class="pt-2">
              <div class="text-xs font-medium text-muted mb-1">包内技能</div>
              <p class="text-xs text-primary">{{ displaySkillNames(dhaBundlePreview.bundle_preview.skills || []).join('，') }}</p>
            </div>
            <div v-if="(dhaBundlePreview.bundle_preview.mcps || []).length" class="pt-2">
              <div class="text-xs font-medium text-muted mb-1">包内 MCP</div>
              <ul class="list-disc pl-4 text-muted space-y-0.5">
                <li v-for="m in dhaBundlePreview.bundle_preview.mcps" :key="m.id">
                  <span class="font-mono text-primary">{{ m.id }}</span> {{ m.name }}
                </li>
              </ul>
            </div>
            <div
              v-if="hasImportMissingReferences(dhaBundlePreview.bundle_preview.missing_references)"
              class="rounded-lg border border-red-300 bg-red-50 px-3 py-2 text-red-700 dark:bg-red-950/20 dark:border-red-500/50 dark:text-red-300"
            >
              <div class="text-xs font-medium mb-1">缺失内容</div>
              <div class="space-y-2">
                <div v-for="group in missingReferenceGroups(dhaBundlePreview.bundle_preview.missing_references)" :key="group.key">
                  <div class="text-xs font-medium">{{ group.label }}</div>
                  <ul class="mt-1 list-disc pl-4 text-xs space-y-0.5">
                    <li v-for="item in group.items" :key="`${group.key}-${item.source}-${item.id}`">
                      <span>{{ missingReferenceTitle(group, item) }}</span>
                      <span class="font-mono text-red-600 dark:text-red-300">（{{ item.id }}）</span>
                      <span v-if="missingRequiredByText(item)" class="text-red-600 dark:text-red-300">
                        ，被 {{ missingRequiredByText(item) }} 依赖
                      </span>
                    </li>
                  </ul>
                </div>
              </div>
              <p class="mt-2 text-xs">这些内容不会阻止导入，但导入后相关场景、专家或技能可能需要手动补齐。</p>
            </div>
            <p v-if="dhaOverwriteSummary" class="text-xs text-amber-700 dark:text-amber-400 pt-2 whitespace-pre-line">
              将覆盖已有内容：{{ dhaOverwriteSummary }}
            </p>
          </div>
        </template>
        <div class="flex justify-start gap-2">
          <button
            type="button"
            class="px-4 py-2 text-sm rounded-lg bg-accent text-text-inverse hover:bg-accent-hover disabled:opacity-50"
            :disabled="dhaImportCommitting || !canConfirmDhaImport"
            @click="commitDhaImport"
          >
            {{ dhaImportCommitting ? '导入中…' : hasDhaNameConflict ? '确认覆盖导入' : '确认导入' }}
          </button>
          <button
            type="button"
            class="px-4 py-2 text-sm rounded-lg border border-border-light bg-card hover:bg-list-hover disabled:opacity-50"
            :disabled="dhaImportCommitting"
            @click="closeDhaImportModal"
          >
            取消
          </button>
        </div>
        </template>
      </div>
    </div>

    <!-- 技能导入 -->
    <div
      v-if="skillImportModalOpen"
      class="fixed inset-0 z-[300] flex items-center justify-center p-4 bg-black/50"
      role="dialog"
      aria-modal="true"
      @click.self="onSkillImportBackdropClick"
    >
      <div
        class="max-w-lg w-full max-h-[85vh] overflow-y-auto rounded-xl border border-border-light bg-card shadow-xl p-5 text-primary themed-scrollbar relative"
        @click.stop
      >
        <div
          v-if="skillZipImporting"
          class="absolute inset-0 z-[25] flex flex-col items-center justify-center gap-3 rounded-xl bg-card/90 backdrop-blur-sm"
          aria-live="polite"
          aria-busy="true"
        >
          <span
            class="inline-block h-9 w-9 rounded-full border-2 border-accent border-t-transparent animate-spin"
            aria-hidden="true"
          />
          <p class="text-sm font-medium text-primary">正在导入…</p>
          <p class="text-xs text-muted px-4 text-center">请勿关闭页面，导入完成后将在此显示结果</p>
        </div>
        <template v-if="skillImportResult">
          <h3 class="text-lg font-semibold mb-3">{{ skillImportResult.ok ? '导入成功' : '导入失败' }}</h3>
          <p
            class="text-sm mb-4 whitespace-pre-wrap"
            :class="skillImportResult.ok ? 'text-primary' : 'text-danger'"
          >
            {{ skillImportResult.message }}
          </p>
          <div class="flex justify-start">
            <button
              type="button"
              class="px-4 py-2 text-sm rounded-lg bg-accent text-text-inverse hover:bg-accent-hover"
              @click="closeSkillImportModal"
            >
              关闭
            </button>
          </div>
        </template>
        <template v-else>
          <h3 class="text-lg font-semibold mb-3">导入技能</h3>
          <div class="mb-4 space-y-2 text-sm border border-border-light rounded-lg p-3 bg-page">
            <div class="font-medium text-primary">{{ pendingSkillZipFile?.name || '未选择文件' }}</div>
            <p class="text-xs text-muted">仅支持 ZIP 文件，且 ZIP 根目录必须包含 SKILL.md。</p>
            <p class="text-xs text-amber-700 dark:text-amber-400">同名技能将执行覆盖导入。</p>
          </div>
          <div class="flex justify-start gap-2">
            <button
              type="button"
              class="px-4 py-2 text-sm rounded-lg bg-accent text-text-inverse hover:bg-accent-hover disabled:opacity-50"
              :disabled="skillZipImporting || !pendingSkillZipFile"
              @click="commitSkillZipImport"
            >
              {{ skillZipImporting ? '导入中…' : '确认覆盖导入' }}
            </button>
            <button
              type="button"
              class="px-4 py-2 text-sm rounded-lg border border-border-light bg-card hover:bg-list-hover disabled:opacity-50"
              :disabled="skillZipImporting"
              @click="closeSkillImportModal"
            >
              取消
            </button>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, inject, onUnmounted, nextTick } from 'vue'
import { useRouter, useRoute } from 'vue-router'

import WorkspaceContent from '@/features/workspace/WorkspaceContent.vue'
import WorkspaceFilesView from '@/features/workspace/WorkspaceFilesView.vue'
import DHAView from '@/features/resources/DHAView.vue'
import SkillDetailView from '@/features/resources/SkillDetailView.vue'
import MCPDetailView from '@/features/resources/MCPDetailView.vue'
import MCPAddView from '@/features/resources/MCPAddView.vue'
import LLMSettingsView from '@/features/resources/LLMSettingsView.vue'
import AppSettingsView from '@/features/settings/AppSettingsView.vue'
import ThemeSettingsView from '@/features/settings/ThemeSettingsView.vue'
import UserPreferenceSettingsView from '@/features/settings/UserPreferenceSettingsView.vue'
import AccountSecuritySettingsView from '@/features/settings/AccountSecuritySettingsView.vue'
import SandboxSettingsView from '@/features/settings/SandboxSettingsView.vue'
import ApiSecretsSettingsView from '@/features/settings/ApiSecretsSettingsView.vue'
import { THEME_AUTH_CHANGED_EVENT, useTheme } from '@/composables/useTheme'
import logoUrl from '@/assets/49logo.png'
import './MainView.css'

const router = useRouter()
const route = useRoute()
/** 与后端 app.core.scene_host.VIRTUAL_SCENE_HOST_ID 一致 */
const VIRTUAL_SCENE_HOST_ID = 'agent-scene-host'
// 主题 composable 在该视图内会触发全局样式变量初始化；无需直接读取其返回值
inject<ReturnType<typeof useTheme>>('theme') ?? useTheme()
const LOGIN_STORAGE_KEY = 'dha_logged_in'
const USER_STORAGE_KEY = 'dha_user'
const USER_ID_STORAGE_KEY = 'dha_user_id'
const TOKEN_STORAGE_KEY = 'dha_token'

function logout() {
  if (!window.confirm('确定要登出吗？')) return
  localStorage.removeItem(LOGIN_STORAGE_KEY)
  localStorage.removeItem(USER_STORAGE_KEY)
  localStorage.removeItem(USER_ID_STORAGE_KEY)
  localStorage.removeItem(TOKEN_STORAGE_KEY)
  window.dispatchEvent(new Event(THEME_AUTH_CHANGED_EVENT))
  router.push('/login')
}

type ModuleId = 'workspace' | 'resource' | 'settings'
type ResourceSubModule = 'scenario' | 'agent' | 'skill' | 'mcp' | 'llm' | 'files'
type SettingsCategoryId = 'app' | 'theme' | 'secrets' | 'account-security' | 'sandbox'
type MissingReferenceSource = 'scene' | 'expert' | 'skill' | 'tool'
type ReferenceSnapshot = { id: string; name?: string }

interface MissingReference {
  id: string
  name?: string
  display_name?: string
  type_label?: string
  required_by?: string[]
  source?: MissingReferenceSource
}

interface ImportMissingReferences {
  experts?: MissingReference[]
  skills?: MissingReference[]
  tools?: MissingReference[]
}

interface MissingReferenceGroup {
  key: keyof ImportMissingReferences
  label: string
  items: MissingReference[]
}

const resourceChildren: { id: ResourceSubModule; label: string }[] = [
  { id: 'scenario', label: '场景' },
  { id: 'agent', label: '专家' },
  { id: 'skill', label: '技能' },
  { id: 'mcp', label: '工具' },
  { id: 'llm', label: '模型' },
  { id: 'files', label: '文件' },
]

const selectedId = ref<string | null>(null)
const resourceMenuExpanded = ref(false)

function resourceRoutePath(id: ResourceSubModule) {
  return `/resources/${id}`
}

function settingsRoutePath(id: SettingsCategoryId) {
  return `/settings/${id}`
}

const currentModule = computed<ModuleId>(() => {
  if (route.path.startsWith('/resources')) return 'resource'
  if (route.path.startsWith('/settings')) return 'settings'
  return 'workspace'
})

const resourceSubModule = computed<ResourceSubModule>(() => {
  const section = String(route.params.section || 'scenario')
  return section === 'agent' || section === 'skill' || section === 'mcp' || section === 'llm' || section === 'files'
    ? section
    : 'scenario'
})

const settingsSection = computed<SettingsCategoryId>(() => {
  const section = String(route.params.section || 'app')
  return section === 'theme' || section === 'secrets' || section === 'account-security' || section === 'sandbox'
    ? section
    : 'app'
})

interface ScenarioHostConfig {
  skill_ids: string[]
  skill_refs?: ReferenceSnapshot[]
  display_name?: string
  system_prompt?: string
  llm_provider_id?: string
  mcp_server_ids?: string[]
  file_capabilities?: {
    read?: boolean
    edit?: boolean
    write?: boolean
    delete?: boolean
    rename?: boolean
  }
  url_capability?: boolean
}
interface ScenarioPreset {
  id: string
  name: string
  agent_ids: string[]
  agent_refs?: ReferenceSnapshot[]
  leader_agent_id?: string
  host_config?: ScenarioHostConfig
  description?: string
  discussion_goal_example?: string
}
type ScenarioDraft = {
  id: string
  name: string
  agent_ids: string[]
  agent_refs: ReferenceSnapshot[]
  description: string
}
const scenarioPresets = ref<ScenarioPreset[]>([])
const scenarioLoading = ref(false)
const scenarioSaving = ref(false)
const creatingScenarioId = ref<string | null>(null)
const scenarioDraftIds = ref<string[]>([])
const LEGACY_DEFAULT_HOST_SKILL_ID = 'group-host'
const scenarioSearch = ref('')
const scenarioExpertSearch = ref('')
const scenarioLeaderSkillSearch = ref('')
const scenarioLeaderDisplayName = ref('')
const scenarioLeaderSkillIds = ref<string[]>([])
const scenarioLeaderSystemPrompt = ref('')
const scenarioLeaderLlmId = ref('')
const scenarioLeaderFileCaps = ref({
  read: true,
  edit: true,
  write: true,
  rename: true,
  mkdir: true,
  list_dir: true,
})
const scenarioLeaderUrlCapability = ref(true)
const scenarioDraft = ref<ScenarioDraft>({
  id: '',
  name: '',
  agent_ids: [],
  agent_refs: [],
  description: '',
})

const scenarioImportFileInputRef = ref<HTMLInputElement | null>(null)
const scenarioImportModalOpen = ref(false)
const scenarioImportCommitting = ref(false)
/** 导入完成后在弹窗内展示结果，用户点「关闭」后再收起（避免先关弹窗再等 alert） */
const scenarioImportResult = ref<{ ok: boolean; message: string } | null>(null)
const pendingBundleFile = ref<File | null>(null)
const scenarioBundlePreview = ref<{
  bundle_preview?: {
    preset_id: string
    preset_name: string
    experts: { agent_id: string; name: string }[]
    skills: string[]
    mcps: { id: string; name: string }[]
    missing_references?: ImportMissingReferences
    would_overwrite_skills?: string[]
    would_skip_skills?: string[]
    name_conflict_existing_ids?: string[]
    name_conflict_mode?: 'skip' | 'overwrite'
  }
} | null>(null)
type ShareScenePreview = {
  preset_id?: string
  preset_name?: string
  experts?: { agent_id: string; name: string }[]
  skills?: string[]
  mcps?: { id: string; name: string }[]
  missing_references?: ImportMissingReferences
  would_overwrite_skills?: string[]
  would_skip_skills?: string[]
  name_conflict_existing_ids?: string[]
  would_overwrite_experts?: Record<string, string[]>
  would_remap_skill_ids?: Record<string, string>
  would_remap_mcp_server_ids?: Record<string, string>
}
const scenarioShareAutoPublishing = ref(false)
const scenarioShareRouteImportLoading = ref(false)
const scenarioShareLinkData = ref<{ share_id: string | null }>({ share_id: null })
function publicAppOriginForShareLink(): string {
  const raw = import.meta.env.VITE_PUBLIC_APP_ORIGIN
  if (typeof raw === 'string' && raw.trim()) {
    return raw.trim().replace(/\/$/, '')
  }
  return window.location.origin
}

const scenarioShareFullUrl = computed(() => {
  const id = scenarioShareLinkData.value.share_id
  if (!id) return ''
  return `${publicAppOriginForShareLink()}/share/run?id=${encodeURIComponent(id)}`
})
const scenarioShareRouteHandled = ref('')
const scenarioShareOpenInFlight = ref(false)
const sharePreviewModalOpen = ref(false)
const sharePreviewLoading = ref(false)
const sharePreviewCommitting = ref(false)
const sharePreviewData = ref<{
  share_id: string
  meta: { object_type: string; title: string; summary?: Record<string, unknown> }
  preview?: (Record<string, unknown> & { missing_references?: ImportMissingReferences }) | ShareScenePreview
} | null>(null)
const sharePreviewResult = ref<{ ok: boolean; message: string } | null>(null)
const sharePreviewMissingReferences = computed(
  () => sharePreviewData.value?.preview?.missing_references || null,
)
const sharePreviewSummaryItems = computed(() => {
  const summary = sharePreviewData.value?.meta?.summary || {}
  return Object.entries(summary)
    .map(([key, value]) => ({
      label: shareSummaryLabel(key),
      value: shareSummaryValue(value),
    }))
    .filter((item) => item.value)
})

const dhaImportFileInputRef = ref<HTMLInputElement | null>(null)
const dhaImportModalOpen = ref(false)
const pendingDhaBundleFile = ref<File | null>(null)
const dhaImportCommitting = ref(false)
const dhaImportResult = ref<{ ok: boolean; message: string } | null>(null)
const dhaBundlePreview = ref<{
  bundle_preview?: {
    agent_id: string
    name?: string
    skills: string[]
    mcps: { id: string; name: string }[]
    missing_references?: ImportMissingReferences
    would_overwrite_skills?: string[]
    would_skip_skills?: string[]
    name_conflict_existing_ids?: string[]
    name_conflict_mode?: 'skip' | 'overwrite'
  }
} | null>(null)

const canConfirmDhaImport = computed(
  () => !!(dhaBundlePreview.value?.bundle_preview && pendingDhaBundleFile.value),
)

const canConfirmScenarioImport = computed(
  () => !!(scenarioBundlePreview.value?.bundle_preview && pendingBundleFile.value),
)
const hasScenarioNameConflict = computed(
  () => (scenarioBundlePreview.value?.bundle_preview?.name_conflict_existing_ids || []).length > 0,
)
const hasDhaNameConflict = computed(
  () => (dhaBundlePreview.value?.bundle_preview?.name_conflict_existing_ids || []).length > 0,
)

function displaySkillNames(skillIds: string[]): string[] {
  const byId = new Map((skills.value || []).map((s) => [s.id, s.name || s.id]))
  return (skillIds || []).map((sid) => byId.get(sid) || sid)
}
function isShareScenePreview(
  data: typeof sharePreviewData.value,
): data is NonNullable<typeof sharePreviewData.value> & { preview: ShareScenePreview } {
  if (!data?.preview) return false
  const type = String(data.meta?.object_type || '').trim().toLowerCase()
  return (type === 'scene' || type === 'scenario') && typeof (data.preview as ShareScenePreview).preset_name === 'string'
}
function shareScenePreview(data: typeof sharePreviewData.value): ShareScenePreview | null {
  return isShareScenePreview(data) ? data.preview : null
}
function shareSummaryLabel(key: string): string {
  const labels: Record<string, string> = {
    agent_count: '专家数量',
    scenario: '场景',
    experts: '专家',
    skills: '技能',
    mcps: 'MCP',
    tools: '工具',
    skill_count: '技能数量',
    mcp_count: 'MCP 数量',
  }
  return labels[key] || key
}
function shareSummaryValue(value: unknown): string {
  if (Array.isArray(value)) return value.map((item) => String(item || '').trim()).filter(Boolean).join('，')
  if (value === null || value === undefined) return ''
  if (typeof value === 'object') return Object.keys(value as Record<string, unknown>).join('，')
  return String(value)
}
function formatShareJson(obj: unknown): string {
  try {
    return JSON.stringify(obj ?? {}, null, 2)
  } catch {
    return String(obj ?? '')
  }
}
function hasImportMissingReferences(refs: ImportMissingReferences | null | undefined): boolean {
  if (!refs) return false
  return Boolean((refs.experts || []).length || (refs.skills || []).length || (refs.tools || []).length)
}
function missingReferenceGroups(refs: ImportMissingReferences | null | undefined): MissingReferenceGroup[] {
  if (!refs) return []
  const groups: MissingReferenceGroup[] = [
    { key: 'experts', label: '专家', items: refs.experts || [] },
    { key: 'skills', label: '技能', items: refs.skills || [] },
    { key: 'tools', label: '工具', items: refs.tools || [] },
  ]
  return groups.filter((group) => group.items.length)
}
function missingRequiredByText(item: MissingReference): string {
  return (item.required_by || []).filter(Boolean).join('，')
}
function missingReferenceTitle(group: MissingReferenceGroup, item: MissingReference): string {
  const typeLabel = item.type_label || (group.key === 'tools' ? 'MCP 工具' : group.label)
  const name = String(item.name || '').trim()
  if (name) return `${typeLabel} ${name}`
  return item.display_name || `${typeLabel} ${item.id}`
}
const scenarioOverwriteSummary = computed(() => {
  const bp = scenarioBundlePreview.value?.bundle_preview
  if (!bp) return ''
  const parts: string[] = []
  if ((bp.name_conflict_existing_ids || []).length) {
    parts.push(`场景：${bp.preset_name || bp.preset_id}`)
  }
  if ((bp.experts || []).length) {
    const expertNames = (bp.experts || []).map((x) => x.name || x.agent_id).filter(Boolean)
    if (expertNames.length) parts.push(`专家：${expertNames.join('，')}`)
  }
  const skillNames = displaySkillNames(bp.would_overwrite_skills || [])
  if (skillNames.length) parts.push(`技能：${skillNames.join('，')}`)
  if ((bp.mcps || []).length) {
    const mcpNames = (bp.mcps || []).map((x) => x.name || x.id).filter(Boolean)
    if (mcpNames.length) parts.push(`工具：${mcpNames.join('，')}`)
  }
  return parts.join('\n')
})
const shareSceneOverwriteSummary = computed(() => {
  const bp = shareScenePreview(sharePreviewData.value)
  if (!bp) return ''
  const parts: string[] = []
  if ((bp.name_conflict_existing_ids || []).length) {
    parts.push(`场景：${bp.preset_name || bp.preset_id || '未命名场景'}`)
  }
  if (bp.would_overwrite_experts && Object.keys(bp.would_overwrite_experts).length) {
    const expertNames = (bp.experts || []).map((x) => x.name || x.agent_id).filter(Boolean)
    parts.push(`专家：${expertNames.join('，') || Object.keys(bp.would_overwrite_experts).join('，')}`)
  }
  const skillNames = displaySkillNames(bp.would_overwrite_skills || [])
  if (skillNames.length) parts.push(`技能：${skillNames.join('，')}`)
  const remapMcpIds = Object.values(bp.would_remap_mcp_server_ids || {})
  if (remapMcpIds.length) {
    const mcpNames = (bp.mcps || [])
      .filter((x) => remapMcpIds.includes(x.id))
      .map((x) => x.name || x.id)
      .filter(Boolean)
    parts.push(`工具：${mcpNames.join('，') || remapMcpIds.join('，')}`)
  }
  return parts.join('\n')
})
const dhaOverwriteSummary = computed(() => {
  const bp = dhaBundlePreview.value?.bundle_preview
  if (!bp) return ''
  const parts: string[] = []
  if ((bp.name_conflict_existing_ids || []).length) {
    parts.push(`专家：${bp.name || bp.agent_id || '未命名专家'}`)
  }
  const skillNames = displaySkillNames(bp.would_overwrite_skills || [])
  if (skillNames.length) parts.push(`技能：${skillNames.join('，')}`)
  if ((bp.mcps || []).length) {
    const mcpNames = (bp.mcps || []).map((x) => x.name || x.id).filter(Boolean)
    if (mcpNames.length) parts.push(`工具：${mcpNames.join('，')}`)
  }
  return parts.join('\n')
})

const isCreatingScenario = computed(() => !!selectedId.value && selectedId.value === creatingScenarioId.value)
function isUnsavedScenarioDraftPreset(s: ScenarioPreset): boolean {
  return (
    s.id.startsWith('scenario-') &&
    !(s.name || '').trim() &&
    !(s.description || '').trim() &&
    !(s.agent_ids || []).length
  )
}
const filteredScenarioPresets = computed(() => {
  const q = (scenarioSearch.value || '').trim().toLowerCase()
  const draftIds = new Set(scenarioDraftIds.value)
  const list = (scenarioPresets.value || []).filter((s) => !draftIds.has(s.id) && !isUnsavedScenarioDraftPreset(s))
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
const filteredScenarioLeaderSkills = computed(() => {
  const q = (scenarioLeaderSkillSearch.value || '').trim().toLowerCase()
  const list = skills.value || []
  if (!q) return list
  return list.filter((s) => {
    const hay = `${s.name || ''} ${s.description || ''} ${s.id || ''}`.toLowerCase()
    return hay.includes(q)
  })
})
const missingScenarioExpertRefs = computed(() =>
  (scenarioDraft.value.agent_ids || [])
    .filter((id) => scenarioExpertMissing(id))
    .map((id) => ({
      id,
      name: referenceNameForId(id, scenarioDraft.value.agent_refs, dhaNameLookup()) || id,
    })),
)
const missingScenarioLeaderSkillRefs = computed(() =>
  (scenarioLeaderSkillIds.value || [])
    .filter((id) => scenarioLeaderSkillMissing(id))
    .map((id) => ({
      id,
      name: scenarioLeaderSkillLabel(id),
    })),
)

const skills = ref<{ id: string; name: string; description?: string }[]>([])
const skillsLoading = ref(false)
const mcpServers = ref<{ id: string; name: string; description?: string; metadata?: Record<string, any>; status: string; tool_count: number }[]>([])
const mcpLoading = ref(false)
const llmDefault = ref<string>('qwen')
const llmProviders = ref<
  Record<string, { base_url?: string; model?: string; api_key_env?: string; label?: string }>
>({})
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

function toggleSearch(kind: 'scenario' | 'agent' | 'skill' | 'mcp') {
  if (kind === 'scenario') {
    showScenarioSearch.value = !showScenarioSearch.value
    if (!showScenarioSearch.value) scenarioSearch.value = ''
  }
  if (kind === 'agent') {
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
const settingsCategories: { id: SettingsCategoryId; label: string }[] = [
  { id: 'app', label: '主持人设置' },
  { id: 'theme', label: '配色' },
  { id: 'secrets', label: '密钥' },
  { id: 'account-security', label: '账号' },
  { id: 'sandbox', label: '沙箱' },
]
// Group
type GroupSessionRow = {
  id: string
  title: string
  updated_at: string
  agent_ids?: string[]
  runtime_state?: { running?: boolean }
}
type SessionNotice = { running?: boolean; hasUpdate?: boolean }
const selectedGroupSessionId = ref<string | null>(null)
const groupSessions = ref<GroupSessionRow[]>([])
const groupSessionsLoading = ref(false)
const creatingSession = ref(false)
const sessionNotices = ref<Record<string, SessionNotice>>({})
let groupSessionsFetchSeq = 0
const protectedGroupSessionIds = new Set<string>()
const dhaInstances = ref<
  {
    agent_id: string
    name: string
    role?: string
    system_prompt?: string
    skill_ids?: string[]
    skill_refs?: ReferenceSnapshot[]
    mcp_server_ids?: string[]
    is_leader?: boolean
    llm_provider_id?: string
    avatar_url?: string
    file_capabilities?: Record<string, boolean>
    file_capability_labels?: string[]
    url_capability?: boolean
  }[]
>([])
const dhaInstancesLoading = ref(false)
const skillZipInputRef = ref<HTMLInputElement | null>(null)
const skillZipImporting = ref(false)
const skillImportModalOpen = ref(false)
const pendingSkillZipFile = ref<File | null>(null)
const skillImportResult = ref<{ ok: boolean; message: string } | null>(null)
const mcpZipInputRef = ref<HTMLInputElement | null>(null)
const mcpZipImporting = ref(false)

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

function dhaAvatarImgUrlForSession(dhaId: string): string | null {
  const u = (dhaInstances.value || []).find((d) => d.agent_id === dhaId)?.avatar_url
  return u && String(u).trim() ? String(u).trim() : null
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
  if (moduleId === 'resource') {
    resourceMenuExpanded.value = true
  } else {
    resourceMenuExpanded.value = false
  }
  if (moduleId !== 'resource') selectedId.value = null
  if (moduleId === 'resource' || moduleId === 'settings') {
    ensureMiddleColumnOpen()
  }
  if (moduleId === 'workspace') void router.push('/workspace')
  if (moduleId === 'resource') void router.push('/resources/scenario')
  if (moduleId === 'settings') void router.push('/settings/app')
}

function onResourceChildClick(id: ResourceSubModule) {
  resourceMenuExpanded.value = true
  void router.push(resourceRoutePath(id))
}

function normalizeReferenceRows(raw: unknown): ReferenceSnapshot[] {
  if (!Array.isArray(raw)) return []
  const out: ReferenceSnapshot[] = []
  const seen = new Set<string>()
  for (const item of raw) {
    const row = item && typeof item === 'object' ? item as Record<string, unknown> : null
    const id = String(row?.id || row?.agent_id || row?.skill_id || '').trim()
    const name = String(row?.name || row?.display_name || row?.label || '').trim()
    if (!id || seen.has(id)) continue
    out.push(name ? { id, name } : { id })
    seen.add(id)
  }
  return out
}

function mergeReferenceRowsForIds(ids: string[], refs?: ReferenceSnapshot[], lookup?: Record<string, string>): ReferenceSnapshot[] {
  const old = new Map(normalizeReferenceRows(refs || []).map((row) => [row.id, row.name || '']))
  const seen = new Set<string>()
  const out: ReferenceSnapshot[] = []
  for (const raw of ids || []) {
    const id = String(raw || '').trim()
    if (!id || seen.has(id)) continue
    const name = String((lookup || {})[id] || old.get(id) || '').trim()
    out.push(name ? { id, name } : { id })
    seen.add(id)
  }
  return out
}

function skillNameLookup(): Record<string, string> {
  return Object.fromEntries((skills.value || []).map((s) => [s.id, s.name || s.id]))
}

function dhaNameLookup(): Record<string, string> {
  return Object.fromEntries((dhaInstances.value || []).map((d) => [d.agent_id, d.name || d.agent_id]))
}

function referenceNameForId(id: string, refs?: ReferenceSnapshot[], lookup?: Record<string, string>): string {
  const key = String(id || '').trim()
  if (!key) return ''
  const current = String((lookup || {})[key] || '').trim()
  if (current) return current
  const hit = normalizeReferenceRows(refs || []).find((row) => row.id === key)
  return hit?.name || ''
}

function dhaDisplayName(dhaId: string, refs?: ReferenceSnapshot[]): string {
  const hit = (dhaInstances.value || []).find((d) => d.agent_id === dhaId)
  return hit?.name || referenceNameForId(dhaId, refs) || dhaId
}

function scenarioExpertMissing(dhaId: string): boolean {
  return Boolean(dhaId && !(dhaInstances.value || []).some((d) => d.agent_id === dhaId))
}

function scenarioLeaderSkillLabel(skillId: string): string {
  return referenceNameForId(skillId, selectedScenarioPreset.value?.host_config?.skill_refs, skillNameLookup()) || skillId
}

function scenarioLeaderSkillMissing(skillId: string): boolean {
  return Boolean(skillId && !(skills.value || []).some((s) => s.id === skillId))
}

function normalizeScenarioLeaderSkillIds(raw: unknown, refs?: ReferenceSnapshot[]): string[] {
  const out: string[] = []
  const seen = new Set<string>()
  const skillLookup = skillNameLookup()
  for (const item of Array.isArray(raw) ? raw : []) {
    const id = String(item || '').trim()
    if (!id || seen.has(id)) continue
    const exists = Boolean(skillLookup[id])
    const refName = referenceNameForId(id, refs, exists ? skillLookup : undefined)
    if (id === LEGACY_DEFAULT_HOST_SKILL_ID && !exists && (!refName || refName === id)) {
      continue
    }
    out.push(id)
    seen.add(id)
  }
  return out
}

function scenarioLlmOptionLabel(pid: string) {
  const m = llmProviders.value[pid]
  if (!m) return pid
  return m.label || m.model || pid
}

function syncScenarioDraftFromSelected() {
  scenarioLeaderSkillSearch.value = ''
  const s = selectedScenarioPreset.value
  if (!s) {
    scenarioDraft.value = { id: '', name: '', agent_ids: [], agent_refs: [], description: '' }
    scenarioLeaderDisplayName.value = ''
    scenarioLeaderSkillIds.value = []
    scenarioLeaderSystemPrompt.value = ''
    scenarioLeaderLlmId.value = ''
    scenarioLeaderFileCaps.value = { read: true, edit: true, write: true, rename: true, mkdir: true, list_dir: true }
    scenarioLeaderUrlCapability.value = true
    return
  }
  const ids = [...(s.agent_ids || [])].filter((id) => id !== VIRTUAL_SCENE_HOST_ID)
  scenarioDraft.value = {
    id: s.id,
    name: s.name || '',
    agent_ids: ids,
    agent_refs: mergeReferenceRowsForIds(ids, s.agent_refs || []),
    description: s.description || '',
  }
  const hc = s.host_config
  if (hc && typeof hc === 'object') {
    scenarioLeaderDisplayName.value = (hc.display_name as string) || ''
    scenarioLeaderSkillIds.value = normalizeScenarioLeaderSkillIds(hc.skill_ids, hc.skill_refs)
    scenarioLeaderSystemPrompt.value = (hc.system_prompt as string) || ''
    scenarioLeaderLlmId.value = (hc.llm_provider_id as string) || ''
    const fc = (hc.file_capabilities || {}) as Record<string, boolean>
    scenarioLeaderFileCaps.value = {
      read: fc.read !== false,
      edit: fc.edit !== false,
      write: fc.write !== false,
      rename: fc.rename !== false,
      mkdir: fc.mkdir !== false,
      list_dir: fc.list_dir !== false,
    }
    scenarioLeaderUrlCapability.value = hc.url_capability !== false
  } else {
    scenarioLeaderDisplayName.value = ''
    scenarioLeaderSkillIds.value = []
    scenarioLeaderSystemPrompt.value = ''
    scenarioLeaderLlmId.value = ''
    scenarioLeaderFileCaps.value = { read: true, edit: true, write: true, rename: true, mkdir: true, list_dir: true }
    scenarioLeaderUrlCapability.value = true
  }
}
function toggleScenarioLeaderSkill(skillId: string) {
  const set = new Set(scenarioLeaderSkillIds.value)
  if (set.has(skillId)) set.delete(skillId)
  else set.add(skillId)
  scenarioLeaderSkillIds.value = Array.from(set)
}

function createScenarioPreset() {
  const ts = Date.now().toString(36)
  const id = `scenario-${ts}`
  const draftIds = new Set(scenarioDraftIds.value)
  const next: ScenarioPreset = {
    id,
    name: '',
    agent_ids: [],
    agent_refs: [],
    description: '',
    leader_agent_id: VIRTUAL_SCENE_HOST_ID,
    host_config: { skill_ids: [] },
  }
  scenarioPresets.value = [
    next,
    ...(scenarioPresets.value || []).filter((p) => !draftIds.has(p.id) && !isUnsavedScenarioDraftPreset(p)),
  ]
  scenarioDraftIds.value = [id]
  selectedId.value = id
  creatingScenarioId.value = id
  syncScenarioDraftFromSelected()
}

function removeScenarioExpert(dhaId: string) {
  scenarioDraft.value.agent_ids = (scenarioDraft.value.agent_ids || []).filter((x) => x !== dhaId)
  scenarioDraft.value.agent_refs = mergeReferenceRowsForIds(
    scenarioDraft.value.agent_ids || [],
    scenarioDraft.value.agent_refs,
    dhaNameLookup(),
  )
}

function addScenarioExpert(dhaId: string) {
  if (!dhaId) return
  if ((scenarioDraft.value.agent_ids || []).includes(dhaId)) return
  scenarioDraft.value.agent_ids = [...(scenarioDraft.value.agent_ids || []), dhaId]
  scenarioDraft.value.agent_refs = mergeReferenceRowsForIds(
    scenarioDraft.value.agent_ids || [],
    scenarioDraft.value.agent_refs,
    dhaNameLookup(),
  )
}

async function persistScenarioPresets(nextPresets: ScenarioPreset[]) {
  const payload = {
    presets: nextPresets.map((p) => {
      const row: Record<string, unknown> = {
        id: p.id,
        name: (p.name || '').trim(),
        agent_ids: [...(p.agent_ids || [])],
        agent_refs: mergeReferenceRowsForIds(p.agent_ids || [], p.agent_refs || [], dhaNameLookup()),
        description: p.description || '',
        discussion_goal_example: (p as { discussion_goal_example?: string }).discussion_goal_example || '',
      }
      if (p.host_config && typeof p.host_config === 'object') {
        row.host_config = p.host_config
        row.leader_agent_id = VIRTUAL_SCENE_HOST_ID
      } else {
        row.leader_agent_id = p.leader_agent_id || VIRTUAL_SCENE_HOST_ID
      }
      return row
    }),
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
  const rawIds = [...(scenarioDraft.value.agent_ids || [])]
  if (!name) {
    window.alert('场景名称不能为空')
    return
  }
  if (!rawIds.length) {
    window.alert('请至少选择 1 位协作专家')
    return
  }
  const skillIds = normalizeScenarioLeaderSkillIds(
    scenarioLeaderSkillIds.value,
    selectedScenarioPreset.value?.host_config?.skill_refs || [],
  )
  const host_config: ScenarioHostConfig = {
    skill_ids: skillIds,
    skill_refs: mergeReferenceRowsForIds(skillIds, selectedScenarioPreset.value?.host_config?.skill_refs || [], skillNameLookup()),
    system_prompt: scenarioLeaderSystemPrompt.value || undefined,
    llm_provider_id: scenarioLeaderLlmId.value || undefined,
    file_capabilities: { ...scenarioLeaderFileCaps.value },
    url_capability: scenarioLeaderUrlCapability.value,
  }
  const leaderName = scenarioLeaderDisplayName.value.trim()
  if (leaderName) {
    host_config.display_name = leaderName
  }
  const dhaIds = rawIds
  scenarioSaving.value = true
  try {
    const next = (scenarioPresets.value || []).map((p) =>
      p.id === cur.id
        ? {
            ...p,
            name,
            description: scenarioDraft.value.description || '',
            agent_ids: dhaIds,
            agent_refs: mergeReferenceRowsForIds(dhaIds, scenarioDraft.value.agent_refs, dhaNameLookup()),
            leader_agent_id: VIRTUAL_SCENE_HOST_ID,
            host_config,
          }
        : p,
    )
    await persistScenarioPresets(next)
    scenarioPresets.value = next
    if (creatingScenarioId.value === cur.id) creatingScenarioId.value = null
    scenarioDraftIds.value = scenarioDraftIds.value.filter((id) => id !== cur.id)
    syncScenarioDraftFromSelected()
    void ensureScenarioSharePublishedSilent()
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
    scenarioDraftIds.value = scenarioDraftIds.value.filter((draftId) => draftId !== id)
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
        scenarioDraftIds.value = []
      }
      syncScenarioDraftFromSelected()
      void fetchScenarioShareLink()
    }
  } catch {
    scenarioPresets.value = []
    syncScenarioDraftFromSelected()
  } finally {
    scenarioLoading.value = false
  }
}

function pickScenarioImportFile() {
  scenarioImportFileInputRef.value?.click()
}

function closeScenarioImportModal() {
  scenarioImportModalOpen.value = false
  pendingBundleFile.value = null
  scenarioBundlePreview.value = null
  scenarioImportResult.value = null
}

function closeSharePreviewModal() {
  sharePreviewModalOpen.value = false
  sharePreviewResult.value = null
  sharePreviewData.value = null
  if (route.path === '/share/run') {
    router.replace('/workspace')
  }
}

function onSharePreviewBackdropClick() {
  if (sharePreviewCommitting.value) return
  closeSharePreviewModal()
}

async function commitSharePreviewImport() {
  const d = sharePreviewData.value
  if (!d?.share_id) return
  sharePreviewCommitting.value = true
  sharePreviewResult.value = null
  try {
    const fd = new FormData()
    fd.append('dry_run', 'false')
    const importR = await fetch(`/api/settings/shares/${encodeURIComponent(d.share_id)}/import`, { method: 'POST', body: fd })
    const importJ = (await importR.json().catch(() => ({}))) as { status?: string; detail?: string; data?: any }
    if (importJ?.status !== 'ok') throw new Error(importJ?.detail || '导入失败')
    await fetchScenarioPresets()
    await fetchDHA()
    await fetchSkills()
    await fetchMCP()
    window.dispatchEvent(new CustomEvent('dha-session-presets-updated'))
    const summary = importJ?.data?.summary || {}
    sharePreviewResult.value = { ok: true, message: `导入完成\n${formatShareJson(summary)}` }
    scenarioShareRouteHandled.value = d.share_id
  } catch (e) {
    sharePreviewResult.value = { ok: false, message: (e as Error).message || '导入失败' }
  } finally {
    sharePreviewCommitting.value = false
  }
}

function onScenarioImportBackdropClick() {
  if (scenarioImportCommitting.value || scenarioImportResult.value) return
  closeScenarioImportModal()
}

async function onScenarioImportFile(ev: Event) {
  const input = ev.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  const lower = file.name.toLowerCase()
  if (!lower.endsWith('.zip')) {
    window.alert('请上传 ZIP 场景包（.zip）')
    return
  }
  pendingBundleFile.value = file
  scenarioBundlePreview.value = null
  try {
    const fd = new FormData()
    fd.append('file', file)
    fd.append('dry_run', 'true')
    fd.append('overwrite_experts', 'true')
    fd.append('overwrite_skills', 'true')
    fd.append('mcp_skip_existing', 'false')
    fd.append('preset_id_conflict', 'overwrite')
    const r = await fetch('/api/settings/session-presets/import-bundle', { method: 'POST', body: fd })
    const j = (await r.json().catch(() => ({}))) as {
      status?: string
      detail?: string
      data?: typeof scenarioBundlePreview.value
    }
    if (j?.status !== 'ok') {
      throw new Error(j.detail || '场景包预览失败')
    }
    scenarioBundlePreview.value = j.data || null
    scenarioImportModalOpen.value = true
  } catch (e) {
    window.alert((e as Error).message || '无法读取场景包')
    pendingBundleFile.value = null
  }
}

async function commitScenarioImport() {
  if (!pendingBundleFile.value) return
  scenarioImportResult.value = null
  scenarioImportCommitting.value = true
  try {
    const fd = new FormData()
    fd.append('file', pendingBundleFile.value)
    fd.append('dry_run', 'false')
    fd.append('overwrite_experts', 'true')
    fd.append('overwrite_skills', 'true')
    fd.append('mcp_skip_existing', 'false')
    fd.append('preset_id_conflict', 'overwrite')
    const r = await fetch('/api/settings/session-presets/import-bundle', { method: 'POST', body: fd })
    const j = (await r.json().catch(() => ({}))) as {
      status?: string
      detail?: string
      data?: {
        summary?: {
          preset_imported_ids?: string[]
          skills_imported?: string[]
          skills_skipped?: string[]
          skipped_by_name?: string[]
          overwritten_existing_ids?: string[]
          mcp_added?: number
        }
      }
    }
    if (j?.status !== 'ok') {
      throw new Error(j.detail || '导入失败')
    }
    const s = j.data?.summary
    const msg = s
      ? `场景 id：${(s.preset_imported_ids || []).join(', ') || '—'}\n场景同名覆盖：${(s.overwritten_existing_ids || []).length} 个，跳过：${(s.skipped_by_name || []).length} 个\n技能写入：${(s.skills_imported || []).length} 个，跳过：${(s.skills_skipped || []).length} 个\n新增 MCP 配置：${s.mcp_added ?? 0} 条`
      : '导入成功'
    await fetchScenarioPresets()
    await fetchDHA()
    await fetchSkills()
    await fetchMCP()
    window.dispatchEvent(new CustomEvent('dha-session-presets-updated'))
    scenarioImportResult.value = { ok: true, message: msg }
    if (route.path === '/scenario/run') {
      const importedPid = (s?.preset_imported_ids || [])[0]
      if (importedPid) {
        const preset = scenarioPresets.value.find((x) => x.id === importedPid)
        if (preset && (preset.agent_ids || []).length) {
          await router.push('/workspace')
          await nextTick()
          await workspaceContentRef.value?.createSessionFromScenarioPreset?.({
            id: preset.id,
            name: preset.name,
            agent_ids: preset.agent_ids,
            leader_agent_id: preset.leader_agent_id,
            host_config: preset.host_config,
            description: preset.description || '',
            discussion_goal_example: preset.discussion_goal_example || '',
          })
        }
      }
      router.replace('/workspace')
    }
  } catch (e) {
    scenarioImportResult.value = { ok: false, message: (e as Error).message || '导入失败' }
  } finally {
    scenarioImportCommitting.value = false
  }
}

async function exportScenarioBundle() {
  const cur = selectedScenarioPreset.value
  if (!cur?.id || isCreatingScenario.value) return
  try {
    const r = await fetch(`/api/settings/session-presets/${encodeURIComponent(cur.id)}/export-bundle`)
    if (!r.ok) {
      const j = (await r.json().catch(() => ({}))) as { detail?: string }
      throw new Error(j.detail || '导出失败')
    }
    const blob = await r.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `scenario-bundle-${cur.id.replace(/[/\\]/g, '_')}.zip`
    a.click()
    URL.revokeObjectURL(url)
  } catch (e) {
    window.alert((e as Error).message || '导出失败')
  }
}

function canAutoPublishFromPreset(p: ScenarioPreset | null): boolean {
  if (!p?.id) return false
  const name = (p.name || '').trim()
  const ids = p.agent_ids || []
  return !!name && ids.length > 0
}

/** 静默发布/刷新推广包（链接 id 不变），用于打开场景页与保存后自动生成 */
async function ensureScenarioSharePublishedSilent() {
  const cur = selectedScenarioPreset.value
  if (!cur?.id || isCreatingScenario.value || !canAutoPublishFromPreset(cur)) return
  if (scenarioShareAutoPublishing.value) return
  scenarioShareAutoPublishing.value = true
  try {
    const r = await fetch(
      `/api/settings/session-presets/${encodeURIComponent(cur.id)}/publish-share`,
      { method: 'POST' }
    )
    const j = (await r.json().catch(() => ({}))) as {
      status?: string
      data?: { share_id?: string }
    }
    if (r.ok && j?.status === 'ok' && j.data?.share_id) {
      scenarioShareLinkData.value = { share_id: j.data.share_id }
    }
  } catch {
    // 静默失败，由「访问方式」区提示补充条件
  } finally {
    scenarioShareAutoPublishing.value = false
  }
}

async function fetchScenarioShareLink() {
  scenarioShareLinkData.value = { share_id: null }
  const p = selectedScenarioPreset.value
  if (!p?.id || isCreatingScenario.value) return
  try {
    const r = await fetch(`/api/settings/session-presets/${encodeURIComponent(p.id)}/share-link`)
    const j = (await r.json().catch(() => ({}))) as {
      status?: string
      data?: { share_id?: string | null }
    }
    if (j?.status === 'ok' && j.data?.share_id) {
      scenarioShareLinkData.value = { share_id: j.data.share_id }
      return
    }
    if (canAutoPublishFromPreset(p)) {
      await ensureScenarioSharePublishedSilent()
    }
  } catch {
    scenarioShareLinkData.value = { share_id: null }
  }
}

async function tryOpenScenarioShareFromRoute() {
  if (route.path !== '/scenario/run' && route.path !== '/share/run') return
  const raw = route.query.id
  const id = typeof raw === 'string' ? raw.trim() : ''
  if (!id) return
  if (scenarioShareRouteHandled.value === id) return
  if (scenarioShareOpenInFlight.value) return
  scenarioShareOpenInFlight.value = true
  scenarioShareRouteImportLoading.value = true
  try {
    if (route.path === '/scenario/run') {
      // 兼容旧链接：直接走场景分享
      const metaR = await fetch(`/api/public/scenarios/${encodeURIComponent(id)}`)
      if (!metaR.ok) {
        window.alert('分享链接无效或已失效')
        router.replace('/workspace')
        return
      }
      const bundleR = await fetch(`/api/public/scenarios/${encodeURIComponent(id)}/bundle`)
      if (!bundleR.ok) {
        window.alert('无法下载场景包')
        router.replace('/workspace')
        return
      }
      const blob = await bundleR.blob()
      const file = new File([blob], `scenario-share-${id}.zip`, { type: 'application/zip' })
      pendingBundleFile.value = file
      scenarioBundlePreview.value = null
      resourceMenuExpanded.value = true
      ensureMiddleColumnOpen()
      await router.replace('/resources/scenario')
      const fd = new FormData()
      fd.append('file', file)
      fd.append('dry_run', 'true')
      fd.append('overwrite_experts', 'true')
      fd.append('overwrite_skills', 'true')
      fd.append('mcp_skip_existing', 'false')
      fd.append('preset_id_conflict', 'overwrite')
      const r = await fetch('/api/settings/session-presets/import-bundle', { method: 'POST', body: fd })
      const j = (await r.json().catch(() => ({}))) as {
        status?: string
        detail?: string
        data?: typeof scenarioBundlePreview.value
      }
      if (j?.status !== 'ok') throw new Error(j.detail || '场景包预览失败')
      scenarioBundlePreview.value = j.data || null
      scenarioImportModalOpen.value = true
      scenarioShareRouteHandled.value = id
      return
    }

    const metaR = await fetch(`/api/public/shares/${encodeURIComponent(id)}/meta`)
    if (!metaR.ok) {
      window.alert('分享链接无效或已失效')
      router.replace('/workspace')
      return
    }
    const mj = (await metaR.json().catch(() => ({}))) as {
      status?: string
      data?: { object_type?: string; title?: string; summary?: Record<string, unknown> }
    }
    if (mj?.status !== 'ok' || !mj.data?.object_type) {
      throw new Error('无法读取分享元数据')
    }
    const fd = new FormData()
    fd.append('dry_run', 'true')
    const previewR = await fetch(`/api/settings/shares/${encodeURIComponent(id)}/import`, { method: 'POST', body: fd })
    const previewJ = (await previewR.json().catch(() => ({}))) as {
      status?: string
      detail?: string
      data?: Record<string, unknown>
    }
    if (previewJ?.status !== 'ok') throw new Error(previewJ?.detail || '预览失败')
    sharePreviewData.value = {
      share_id: id,
      meta: {
        object_type: String(mj.data.object_type || 'unknown'),
        title: String(mj.data.title || id),
        summary: (mj.data.summary || {}) as Record<string, unknown>,
      },
      preview: (previewJ.data?.preview || previewJ.data || {}) as Record<string, unknown>,
    }
    sharePreviewResult.value = null
    sharePreviewModalOpen.value = true
  } catch (e) {
    window.alert((e as Error).message || '无法加载分享场景')
    router.replace('/workspace')
  } finally {
    scenarioShareRouteImportLoading.value = false
    scenarioShareOpenInFlight.value = false
  }
}

watch(
  () => [route.path, typeof route.query.id === 'string' ? route.query.id : ''] as const,
  () => {
    void tryOpenScenarioShareFromRoute()
  },
  { immediate: true }
)

watch(
  () => route.path,
  (p) => {
    if (p !== '/scenario/run' && p !== '/share/run') scenarioShareRouteHandled.value = ''
  }
)

function pickDhaImportFile() {
  dhaImportFileInputRef.value?.click()
}

function closeDhaImportModal() {
  dhaImportModalOpen.value = false
  pendingDhaBundleFile.value = null
  dhaBundlePreview.value = null
  dhaImportResult.value = null
}

function onDhaImportBackdropClick() {
  if (dhaImportCommitting.value || dhaImportResult.value) return
  closeDhaImportModal()
}

async function onDhaImportFile(ev: Event) {
  const input = ev.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  const lower = file.name.toLowerCase()
  if (!lower.endsWith('.zip')) {
    window.alert('请上传 ZIP 专家包（.zip）')
    return
  }
  pendingDhaBundleFile.value = file
  dhaBundlePreview.value = null
  try {
    const fd = new FormData()
    fd.append('file', file)
    fd.append('dry_run', 'true')
    fd.append('overwrite_skills', 'true')
    fd.append('mcp_skip_existing', 'false')
    fd.append('id_conflict', 'overwrite')
    const r = await fetch('/api/dha/instances/import-bundle', { method: 'POST', body: fd })
    const j = (await r.json().catch(() => ({}))) as {
      status?: string
      detail?: string
      data?: typeof dhaBundlePreview.value
    }
    if (j?.status !== 'ok') {
      throw new Error(j.detail || '专家包预览失败')
    }
    dhaBundlePreview.value = j.data || null
    dhaImportModalOpen.value = true
  } catch (e) {
    window.alert((e as Error).message || '无法读取专家包')
    pendingDhaBundleFile.value = null
  }
}

async function commitDhaImport() {
  if (!pendingDhaBundleFile.value) return
  dhaImportResult.value = null
  dhaImportCommitting.value = true
  try {
    const fd = new FormData()
    fd.append('file', pendingDhaBundleFile.value)
    fd.append('dry_run', 'false')
    fd.append('overwrite_skills', 'true')
    fd.append('mcp_skip_existing', 'false')
    fd.append('id_conflict', 'overwrite')
    const r = await fetch('/api/dha/instances/import-bundle', { method: 'POST', body: fd })
    const j = (await r.json().catch(() => ({}))) as {
      status?: string
      detail?: string
      data?: {
        summary?: {
          imported_agent_id?: string
          skills_imported?: string[]
          skipped_by_name?: boolean
          overwritten_agent_ids?: string[]
        }
      }
    }
    if (j?.status !== 'ok') {
      throw new Error(j.detail || '导入失败')
    }
    const summary = j.data?.summary
    const aid = summary?.imported_agent_id
    const msg = summary?.skipped_by_name
      ? `未导入：存在同名专家（技能写入 ${(summary.skills_imported || []).length} 个）`
      : aid
        ? `导入成功，专家 id：${aid}（同名覆盖 ${(summary?.overwritten_agent_ids || []).length} 个；技能写入 ${(summary?.skills_imported || []).length} 个）`
        : '导入成功'
    await fetchDHA()
    await fetchSkills()
    await fetchMCP()
    dhaImportResult.value = { ok: true, message: msg }
  } catch (e) {
    dhaImportResult.value = { ok: false, message: (e as Error).message || '导入失败' }
  } finally {
    dhaImportCommitting.value = false
  }
}

async function fetchSkills(options: { silent?: boolean } = {}) {
  const showLoading = !options.silent && skills.value.length === 0
  if (showLoading) skillsLoading.value = true
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
    if (showLoading) skillsLoading.value = false
  }
}

function upsertGroupSessionRow(row?: Partial<GroupSessionRow> | null) {
  const id = String(row?.id || '').trim()
  if (!id) return
  const next: GroupSessionRow = {
    id,
    title: String(row?.title || '新对话'),
    updated_at: String(row?.updated_at || new Date().toISOString()),
    agent_ids: Array.isArray(row?.agent_ids) ? row.agent_ids : [],
  }
  groupSessions.value = [next, ...groupSessions.value.filter((s) => s.id !== id)]
}

function sessionNotice(sessionId: string): SessionNotice {
  return sessionNotices.value[sessionId] || {}
}

function isSessionCurrentlyVisible(sessionId: string): boolean {
  return currentModule.value === 'workspace' && selectedGroupSessionId.value === sessionId
}

function patchSessionNotice(sessionId: string, patch: SessionNotice) {
  if (!sessionId) return
  const prev = sessionNotices.value[sessionId] || {}
  sessionNotices.value = {
    ...sessionNotices.value,
    [sessionId]: { ...prev, ...patch },
  }
}

function clearSessionUpdateNotice(sessionId: string) {
  if (!sessionId) return
  const prev = sessionNotices.value[sessionId]
  if (!prev?.hasUpdate) return
  patchSessionNotice(sessionId, { hasUpdate: false })
}

function onSessionRunState(sessionId: string, running: boolean) {
  const prev = sessionNotices.value[sessionId] || {}
  const shouldMarkUpdated = !running && prev.running && !isSessionCurrentlyVisible(sessionId)
  patchSessionNotice(sessionId, {
    running,
    hasUpdate: shouldMarkUpdated ? true : prev.hasUpdate,
  })
}

function syncSessionRuntimeNotices(sessions: GroupSessionRow[]) {
  for (const session of sessions) {
    if (session.runtime_state?.running === true) {
      patchSessionNotice(session.id, { running: true })
    }
  }
}

function protectNewGroupSession(id: string) {
  if (!id) return
  protectedGroupSessionIds.add(id)
  window.setTimeout(() => protectedGroupSessionIds.delete(id), 5000)
}

async function fetchGroupSessions() {
  const seq = ++groupSessionsFetchSeq
  groupSessionsLoading.value = true
  try {
    const r = await fetch('/api/sessions')
    const j = await r.json()
    if (seq !== groupSessionsFetchSeq) return
    if (j.status === 'ok' && j.data?.sessions) {
      let nextSessions = (j.data.sessions || []) as GroupSessionRow[]
      for (const protectedId of protectedGroupSessionIds) {
        if (!nextSessions.some((s) => s.id === protectedId)) {
          const optimistic = groupSessions.value.find((s) => s.id === protectedId)
          if (optimistic) nextSessions = [optimistic, ...nextSessions]
        }
      }
      groupSessions.value = nextSessions
      syncSessionRuntimeNotices(nextSessions)
      const current = selectedGroupSessionId.value
      const ids = groupSessions.value.map((s) => s.id)
      if (current && !ids.includes(current)) {
        if (protectedGroupSessionIds.has(current)) return
        selectedGroupSessionId.value = groupSessions.value.length > 0 ? groupSessions.value[0].id : null
      } else if (!current && groupSessions.value.length > 0) {
        selectedGroupSessionId.value = groupSessions.value[0].id
      }
    }
  } finally {
    if (seq === groupSessionsFetchSeq) groupSessionsLoading.value = false
  }
}

const workspaceContentRef = ref<{
  refresh: () => void
  createSessionFromScenarioPreset: (p: {
    id: string
    name: string
    agent_ids: string[]
    leader_agent_id?: string
    host_config?: ScenarioHostConfig
    description?: string
    discussion_goal_example?: string
  }) => Promise<string | null>
} | null>(null)
async function onChatMessageSent() {
  workspaceContentRef.value?.refresh()
  await fetchGroupSessions()
}

/** 从场景预设新建会话后：切到新会话并刷新列表 */
async function onScenarioNewSession(sessionId: string, session?: Partial<GroupSessionRow>) {
  protectNewGroupSession(sessionId)
  upsertGroupSessionRow(session || { id: sessionId })
  selectedGroupSessionId.value = sessionId
  await fetchGroupSessions()
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
      protectNewGroupSession(j.data.id)
      upsertGroupSessionRow(j.data)
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
  clearSessionUpdateNotice(id)
}

watch(
  [currentModule, selectedGroupSessionId],
  ([moduleId, sessionId]) => {
    if (moduleId === 'workspace' && sessionId) clearSessionUpdateNotice(sessionId)
  },
)

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



async function fetchDHA() {
  dhaInstancesLoading.value = true
  try {
    const r = await fetch('/api/agents')
    const j = await r.json()
    if (j.status === 'ok' && j.data?.instances) {
      dhaInstances.value = j.data.instances
      // 资源中心 专家：默认选中第一个，且当当前选中项失效时自动回退
      if (currentModule.value === 'resource' && resourceSubModule.value === 'agent') {
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

async function fetchMCP(options: { silent?: boolean } = {}) {
  const showLoading = !options.silent && mcpServers.value.length === 0
  if (showLoading) mcpLoading.value = true
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
    if (showLoading) mcpLoading.value = false
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
      if (resourceSubModule.value === 'llm') {
        const ids = Object.keys(llmProviders.value)
        if (selectedId.value === '__new__') return
        if (selectedId.value && !ids.includes(selectedId.value)) {
          selectedId.value = ids.includes(llmDefault.value) ? llmDefault.value : (ids[0] || null)
        } else if (!selectedId.value && ids.length > 0) {
          selectedId.value = ids.includes(llmDefault.value) ? llmDefault.value : ids[0]
        }
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
    skillImportResult.value = { ok: false, message: '仅支持导入 ZIP 文件' }
    skillImportModalOpen.value = true
    return
  }
  pendingSkillZipFile.value = file
  skillImportResult.value = null
  skillImportModalOpen.value = true
}

function closeSkillImportModal() {
  skillImportModalOpen.value = false
  pendingSkillZipFile.value = null
  skillImportResult.value = null
}

function onSkillImportBackdropClick() {
  if (skillZipImporting.value || skillImportResult.value) return
  closeSkillImportModal()
}

async function commitSkillZipImport() {
  if (!pendingSkillZipFile.value || skillZipImporting.value) return
  skillImportResult.value = null
  skillZipImporting.value = true
  try {
    const fd = new FormData()
    fd.append('file', pendingSkillZipFile.value)
    fd.append('name_conflict', 'overwrite')
    const r = await fetch('/api/settings/skills/import-zip', {
      method: 'POST',
      body: fd,
    })
    const j = await r.json().catch(() => ({}))
    if (j?.status === 'ok') {
      await fetchSkills()
      if (j?.data?.id) selectedId.value = j.data.id
      skillImportResult.value = {
        ok: true,
        message: j?.data?.skipped_by_name
          ? `未导入：存在同名技能 "${j?.data?.name || '未知'}"`
          : `导入成功：${j?.data?.name || j?.data?.id || '技能'}`,
      }
    } else {
      skillImportResult.value = { ok: false, message: j?.detail || '导入技能失败' }
    }
  } catch (err) {
    console.error(err)
    skillImportResult.value = { ok: false, message: '导入技能失败，请检查网络或 ZIP 格式' }
  } finally {
    skillZipImporting.value = false
  }
}

function triggerMcpZipImport() {
  if (mcpZipImporting.value) return
  mcpZipInputRef.value?.click()
}

async function onMcpZipSelected(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file || mcpZipImporting.value) return
  const isZip = file.name.toLowerCase().endsWith('.zip') || file.type === 'application/zip' || file.type === 'application/x-zip-compressed'
  if (!isZip) {
    window.alert('仅支持导入 ZIP 文件')
    return
  }
  mcpZipImporting.value = true
  try {
    const fd = new FormData()
    fd.append('file', file)
    const r = await fetch('/api/settings/mcp/import-zip', {
      method: 'POST',
      body: fd,
    })
    const j = await r.json().catch(() => ({}))
    if (j?.status !== 'ok') {
      throw new Error(j?.detail || '导入工具失败')
    }
    await fetchMCP()
    const summary = j?.data?.summary || {}
    window.alert(`导入成功：新增 ${summary.mcp_added ?? 0} 个，更新 ${summary.mcp_updated ?? 0} 个，跳过 ${summary.mcp_skipped ?? 0} 个`)
  } catch (err) {
    window.alert((err as Error).message || '导入工具失败，请检查网络或 ZIP 格式')
  } finally {
    mcpZipImporting.value = false
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
  resourceMenuExpanded.value = mod === 'resource'
  if (mod === 'resource') {
    if (resourceSubModule.value === 'scenario') fetchScenarioPresets()
    if (resourceSubModule.value === 'skill') fetchSkills()
    if (resourceSubModule.value === 'mcp') fetchMCP()
    if (resourceSubModule.value === 'agent') fetchDHA()
    if (resourceSubModule.value === 'llm') fetchLLM()
    if (resourceSubModule.value === 'files') fetchFileSessions()
  }
  if (mod === 'settings') selectedId.value = settingsSection.value
  if (mod === 'workspace') {
    fetchGroupSessions()
    fetchDHA()
    fetchSkills()
  }
}, { immediate: true })

watch(settingsSection, (section) => {
  if (currentModule.value === 'settings') selectedId.value = section
})

watch(resourceSubModule, (sub) => {
  // 切换子栏目时收起搜索，避免“跨栏目残留过滤”造成误解
  showDhaSearch.value = false
  showSkillSearch.value = false
  showMcpSearch.value = false
  dhaSearch.value = ''
  skillSearch.value = ''
  mcpSearch.value = ''
  scenarioSearch.value = ''
  // 切到「场景」时保留/由 fetch 校验 selectedId，避免右侧表单短暂空白；其它子栏目仍清空选中
  if (sub === 'scenario') {
    fetchScenarioPresets()
    return
  }
  selectedId.value = null
  if (sub === 'agent') fetchDHA()
  if (sub === 'skill') fetchSkills()
  if (sub === 'mcp') fetchMCP()
  if (sub === 'llm') fetchLLM()
  if (sub === 'files') fetchFileSessions()
})

watch(selectedScenarioPreset, () => {
  if (resourceSubModule.value !== 'scenario') return
  syncScenarioDraftFromSelected()
  void fetchScenarioShareLink()
})

// 初始加载：切到对应模块时再请求数据
</script>
