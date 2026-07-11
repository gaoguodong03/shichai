<template>
  <div class="flex flex-1 min-h-0 min-w-0 bg-page">
    <MainNavigationRail
      :current-module="currentModule"
      :resource-sub-module="resourceSubModule"
      :resource-menu-expanded="resourceMenuExpanded"
      @nav-click="onNavClick"
      @resource-child-click="onResourceChildClick"
      @logout="logout"
    />

    <aside
      class="flex-shrink-0 flex flex-col bg-sidebar overflow-hidden"
      :style="{ width: middleColumnOpen ? middleColumnWidth + 'px' : '0px' }"
    >
      <div v-if="currentModule === 'workspace'" ref="newSessionMenuRoot" class="px-3 pt-3 pb-3 flex-shrink-0 relative">
        <button
          type="button"
          aria-haspopup="menu"
          :aria-expanded="newSessionMenuOpen ? 'true' : 'false'"
          @click.stop="toggleNewSessionMenu"
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
          v-if="newSessionMenuOpen"
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
            @click="createBlankSessionFromMenu"
          >
            <span class="new-session-menu-item-title">空会话</span>
          </button>
          <div class="new-session-menu-divider" />
          <div v-if="scenarioLoading" class="new-session-menu-status">场景加载中...</div>
          <div v-else-if="!newSessionMenuScenarios.length" class="new-session-menu-status">暂无场景</div>
          <button
            v-else
            v-for="scenario in newSessionMenuScenarios"
            :key="scenario.name"
            type="button"
            role="menuitem"
            class="new-session-menu-item"
            @click="createScenarioSessionFromMenu(scenario)"
          >
            <span class="new-session-menu-item-title">{{ scenario.name || '未命名场景' }}</span>
            <span class="new-session-menu-item-meta">{{ (scenario.agent_names || []).length }} 位专家</span>
          </button>
        </div>
      </div>
      <div
        class="flex-1 overflow-y-auto middle-column-scrollbar"
        :class="currentModule === 'resource' ? 'pt-3' : ''"
      >
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
              <SessionMemberAvatars
                :agent-names="s.agent_names || []"
                :agent-instances="agentInstances"
                :updated-at="s.updated_at"
              />
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
        <template v-else-if="currentModule === 'resource'">
          <template v-if="resourceSubModule === 'scenario'">
            <div class="mb-2 px-3 space-y-2">
              <div class="flex items-center gap-2">
                <button
                  type="button"
                  class="flex-1 h-10 px-3 rounded-xl text-sm font-semibold flex items-center justify-center gap-1 transition-colors shadow-sm bg-nav-selected-bg text-nav-selected-text hover:bg-nav-hover-bg"
                  @click="createScenarioPreset"
                >
                  <span class="main-sidebar-asset-icon" :style="resourceIconStyle(resourceNewIconUrl)" aria-hidden="true" />
                  <span>新建场景</span>
                </button>
                <button
                  type="button"
                  class="w-10 h-10 rounded-xl bg-list-hover text-primary hover:bg-nav-hover-bg transition-colors flex items-center justify-center"
                  title="导入场景包（ZIP）"
                  @click="pickScenarioImportFile"
                >
                  <ResourceImportIcon class="main-sidebar-svg-icon" aria-hidden="true" />
                </button>
                <button
                  type="button"
                  class="w-10 h-10 rounded-xl bg-list-hover text-primary hover:bg-nav-hover-bg transition-colors flex items-center justify-center"
                  title="搜索场景"
                  @click="toggleSearch('scenario')"
                >
                  <span class="main-sidebar-asset-icon" :style="resourceIconStyle(resourceSearchIconUrl)" aria-hidden="true" />
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
              :key="s.name"
              :class="[
                'w-full flex items-center gap-1 px-3 py-2.5 rounded-lg text-sm transition-colors cursor-pointer group',
                selectedId === s.name ? 'bg-accent-subtle text-accent-subtle-text' : 'hover:bg-list-hover text-list-hover-text'
              ]"
              @click="selectedId = s.name"
            >
              <div class="flex-1 min-w-0 text-left">
                <div class="truncate font-medium">{{ s.name }}</div>
                <div class="truncate text-xs text-muted mt-0.5">{{ (s.agent_names || []).length }} 位专家</div>
              </div>
              <button
                type="button"
                class="p-1.5 rounded text-muted hover:text-danger hover:bg-danger-subtle opacity-0 group-hover:opacity-100"
                title="删除"
                @click.stop="deleteScenarioPreset(s.name)"
              >
                ×
              </button>
            </div>
          </template>
          <template v-else-if="resourceSubModule === 'agent'">
            <div class="mb-2 px-3 space-y-2">
              <div class="flex items-center gap-2">
                <button
                  type="button"
                  class="flex-1 h-10 px-3 rounded-xl text-sm font-semibold flex items-center justify-center gap-1 transition-colors shadow-sm bg-nav-selected-bg text-nav-selected-text hover:bg-nav-hover-bg"
                  @click="selectedId = '__new__'"
                >
                  <span class="main-sidebar-asset-icon" :style="resourceIconStyle(resourceNewIconUrl)" aria-hidden="true" />
                  <span>新建专家</span>
                </button>
                <button
                  type="button"
                  class="w-10 h-10 rounded-xl bg-list-hover text-primary hover:bg-nav-hover-bg transition-colors flex items-center justify-center"
                  title="导入专家包（ZIP）"
                  @click="pickAgentImportFile"
                >
                  <ResourceImportIcon class="main-sidebar-svg-icon" aria-hidden="true" />
                </button>
                <button
                  type="button"
                  class="w-10 h-10 rounded-xl bg-list-hover text-primary hover:bg-nav-hover-bg transition-colors flex items-center justify-center"
                  title="搜索专家"
                  @click="toggleSearch('agent')"
                >
                  <span class="main-sidebar-asset-icon" :style="resourceIconStyle(resourceSearchIconUrl)" aria-hidden="true" />
                </button>
              </div>
              <input
                v-if="showAgentSearch"
                v-model="agentSearch"
                type="text"
                placeholder="搜索专家（名称/描述）"
                class="w-full px-3 py-2 text-sm bg-input-bg border border-input-border rounded-lg text-primary placeholder-muted focus:outline-none focus:ring-2 focus:ring-input-focus-ring"
              />
              <input
                ref="agentImportFileInputRef"
                type="file"
                accept=".zip,application/zip"
                class="hidden"
                @change="onAgentImportFile"
              />
            </div>
            <div v-if="agentInstancesLoading" class="px-3 py-4 text-sm text-muted">加载中...</div>
            <div v-else-if="!filteredAgentInstances.length" class="px-3 py-4 text-sm text-muted">暂无专家</div>
            <div
              v-else
              v-for="d in filteredAgentInstances"
              :key="d.name"
              :class="[
                'w-full flex items-center gap-1 px-3 py-2.5 rounded-lg text-sm transition-colors cursor-pointer group',
                selectedId === d.name ? 'bg-accent-subtle text-accent-subtle-text' : 'hover:bg-list-hover text-list-hover-text'
              ]"
              @click="selectedId = d.name"
            >
              <div
                class="shrink-0 w-9 h-9 rounded-xl border border-border-light overflow-hidden bg-page flex items-center justify-center text-muted text-sm font-semibold"
              >
                <span>{{ (d.name || '?').trim().charAt(0) || '?' }}</span>
              </div>
              <div class="flex-1 min-w-0 text-left">
              <div class="truncate font-medium">{{ d.name }}</div>
                <div class="truncate text-xs text-muted mt-0.5">{{ d.description || '（无描述）' }}</div>
              </div>
              <button
                type="button"
                class="p-1.5 rounded text-muted hover:text-danger hover:bg-danger-subtle opacity-0 group-hover:opacity-100"
                title="删除专家"
                @click.stop="deleteAgentInstance(d.name)"
              >
                ×
              </button>
            </div>
          </template>
          <template v-else-if="resourceSubModule === 'skill'">
            <div class="mb-2 px-3 space-y-2">
              <div class="flex items-center gap-2">
                <button
                  type="button"
                  class="flex-1 h-10 px-3 rounded-xl text-sm font-semibold flex items-center justify-center gap-1 transition-colors shadow-sm bg-nav-selected-bg text-nav-selected-text hover:bg-nav-hover-bg"
                  @click="createEmptySkill"
                >
                  <span class="main-sidebar-asset-icon" :style="resourceIconStyle(resourceNewIconUrl)" aria-hidden="true" />
                  <span>新建技能</span>
                </button>
                <button
                  type="button"
                  class="w-10 h-10 rounded-xl bg-list-hover text-primary hover:bg-nav-hover-bg transition-colors flex items-center justify-center"
                  title="导入技能包（ZIP）"
                  @click="triggerSkillZipImport"
                >
                  <ResourceImportIcon class="main-sidebar-svg-icon" aria-hidden="true" />
                </button>
                <button
                  type="button"
                  class="w-10 h-10 rounded-xl bg-list-hover text-primary hover:bg-nav-hover-bg transition-colors flex items-center justify-center"
                  title="搜索技能"
                  @click="toggleSearch('skill')"
                >
                  <span class="main-sidebar-asset-icon" :style="resourceIconStyle(resourceSearchIconUrl)" aria-hidden="true" />
                </button>
              </div>
              <input
                v-if="showSkillSearch"
                v-model="skillSearch"
                type="text"
                placeholder="搜索技能（名称/描述）"
                class="w-full px-3 py-2 text-sm bg-input-bg border border-input-border rounded-lg text-primary placeholder-muted focus:outline-none focus:ring-2 focus:ring-input-focus-ring"
              />
              <input
                ref="skillZipInputRef"
                type="file"
                accept=".zip,application/zip"
                class="hidden"
                @change="onSkillZipSelected"
              />
            </div>
            <div v-if="skillsLoading" class="px-3 py-4 text-sm text-muted">加载中...</div>
            <div v-else-if="!filteredSkills.length" class="px-3 py-4 text-sm text-muted">暂无技能</div>
            <div
              v-else
              v-for="s in filteredSkills"
              :key="s.directory_name"
              class="relative group"
            >
              <button
                type="button"
                @click="selectedId = s.directory_name"
                :class="[
                  'w-full text-left px-3 py-2.5 pr-10 rounded-lg text-sm transition-colors',
                  selectedId === s.directory_name ? 'bg-accent-subtle text-accent-subtle-text' : 'hover:bg-list-hover text-list-hover-text'
                ]"
              >
                <div class="truncate font-medium">{{ s.name }}</div>
                <div class="truncate text-xs text-muted mt-0.5 min-h-4">
                  {{ s.description || '（无描述）' }}
                </div>
              </button>
              <button
                type="button"
                class="absolute right-2 top-1/2 -translate-y-1/2 p-1.5 rounded text-muted hover:text-danger hover:bg-danger-subtle opacity-0 group-hover:opacity-100 group-focus-within:opacity-100 transition-opacity"
                :aria-label="`删除技能 ${s.name || s.directory_name}`"
                :title="`删除技能 ${s.name || s.directory_name}`"
                @click.stop="deleteSkill(s.directory_name)"
              >
                ×
              </button>
            </div>
          </template>
          <template v-else-if="resourceSubModule === 'mcp'">
            <div class="mb-2 px-3 space-y-2">
              <div class="flex items-center gap-2">
                <button
                  type="button"
                  class="flex-1 h-10 px-3 rounded-xl text-sm font-semibold flex items-center justify-center gap-1 transition-colors shadow-sm bg-nav-selected-bg text-nav-selected-text hover:bg-nav-hover-bg"
                  @click="selectedId = '__new__'"
                >
                  <span class="main-sidebar-asset-icon" :style="resourceIconStyle(resourceNewIconUrl)" aria-hidden="true" />
                  <span>新建工具</span>
                </button>
                <button
                  type="button"
                  class="w-10 h-10 rounded-xl bg-list-hover text-primary hover:bg-nav-hover-bg transition-colors flex items-center justify-center"
                  title="导入工具包（ZIP）"
                  :disabled="mcpZipImporting"
                  @click="triggerMcpZipImport"
                >
                  <ResourceImportIcon class="main-sidebar-svg-icon" aria-hidden="true" />
                </button>
                <button
                  type="button"
                  class="w-10 h-10 rounded-xl bg-list-hover text-primary hover:bg-nav-hover-bg transition-colors flex items-center justify-center"
                  title="搜索工具"
                  @click="toggleSearch('mcp')"
                >
                  <span class="main-sidebar-asset-icon" :style="resourceIconStyle(resourceSearchIconUrl)" aria-hidden="true" />
                </button>
              </div>
              <input
                v-if="showMcpSearch"
                v-model="mcpSearch"
                type="text"
                placeholder="搜索工具（名称/描述）"
                class="w-full px-3 py-2 text-sm bg-input-bg border border-input-border rounded-lg text-primary placeholder-muted focus:outline-none focus:ring-2 focus:ring-input-focus-ring"
              />
              <input
                ref="mcpZipInputRef"
                type="file"
                accept=".zip,application/zip"
                class="hidden"
                @change="onMcpZipSelected"
              />
            </div>
            <div v-if="mcpLoading" class="px-3 py-4 text-sm text-muted">加载中...</div>
            <div v-else-if="!filteredMcpServers.length" class="px-3 py-4 text-sm text-muted">暂无工具</div>
            <div
              v-else
              v-for="s in filteredMcpServers"
              :key="s.name"
              class="relative group"
            >
              <button
                type="button"
                @click="selectedId = s.name"
                :class="[
                  'w-full text-left px-3 py-2.5 pr-10 rounded-lg text-sm transition-colors',
                  selectedId === s.name ? 'bg-accent-subtle text-accent-subtle-text' : 'hover:bg-list-hover text-list-hover-text'
                ]"
              >
                <div class="truncate font-medium">{{ s.name }}</div>
                <div class="truncate text-xs text-muted mt-0.5 min-h-4">
                  {{ s.description || s.metadata?.description || '（无描述）' }}
                </div>
              </button>
              <button
                type="button"
                class="absolute right-2 top-1/2 -translate-y-1/2 p-1.5 rounded text-muted hover:text-danger hover:bg-danger-subtle opacity-0 group-hover:opacity-100 group-focus-within:opacity-100 transition-opacity"
                :aria-label="`删除工具 ${s.name}`"
                :title="`删除工具 ${s.name}`"
                @click.stop="deleteMcpServer(s.name)"
              >
                ×
              </button>
            </div>
          </template>
          <template v-else-if="resourceSubModule === 'llm'">
            <div class="mb-2 px-3 space-y-2">
              <div class="flex items-center gap-2">
                <button
                  type="button"
                  class="flex-1 h-10 px-3 rounded-xl text-sm font-semibold flex items-center justify-center gap-1 transition-colors shadow-sm bg-nav-selected-bg text-nav-selected-text hover:bg-nav-hover-bg"
                  @click="selectedId = '__new__'"
                >
                  <span class="main-sidebar-asset-icon" :style="resourceIconStyle(resourceNewIconUrl)" aria-hidden="true" />
                  <span>新建模型</span>
                </button>
                <button
                  type="button"
                  class="w-10 h-10 rounded-xl bg-list-hover text-primary hover:bg-nav-hover-bg transition-colors flex items-center justify-center"
                  title="导入模型包（ZIP）"
                  @click="pickLlmImportFile"
                >
                  <ResourceImportIcon class="main-sidebar-svg-icon" aria-hidden="true" />
                </button>
                <button
                  type="button"
                  class="w-10 h-10 rounded-xl bg-list-hover text-primary hover:bg-nav-hover-bg transition-colors flex items-center justify-center"
                  title="搜索模型"
                  @click="toggleSearch('llm')"
                >
                  <span class="main-sidebar-asset-icon" :style="resourceIconStyle(resourceSearchIconUrl)" aria-hidden="true" />
                </button>
              </div>
              <input
                v-if="showLlmSearch"
                v-model="llmSearch"
                type="text"
                placeholder="搜索模型（名称/模型型号）"
                class="w-full px-3 py-2 text-sm bg-input-bg border border-input-border rounded-lg text-primary placeholder-muted focus:outline-none focus:ring-2 focus:ring-input-focus-ring"
              />
              <input
                ref="llmImportFileInputRef"
                type="file"
                accept=".zip,application/zip"
                class="hidden"
                @change="onLlmImportFile"
              />
            </div>
            <div v-if="llmLoading" class="px-3 py-4 text-sm text-muted">加载中...</div>
            <div v-else-if="!filteredLlmModelNames.length" class="px-3 py-4 text-sm text-muted">暂无模型</div>
            <div
              v-else
              v-for="modelName in filteredLlmModelNames"
              :key="modelName"
              class="relative group"
            >
              <button
                type="button"
                @click="selectedId = modelName"
                :class="[
                  'w-full text-left px-3 py-2.5 pr-10 rounded-lg text-sm transition-colors',
                  selectedId === modelName ? 'bg-accent-subtle text-accent-subtle-text' : 'hover:bg-list-hover text-list-hover-text'
                ]"
              >
                <div class="truncate font-medium flex items-center gap-2">
                  <span class="truncate">{{ modelName }}</span>
                  <span
                    v-if="modelName === llmDefault"
                    class="px-2 py-0.5 text-xs rounded-full bg-accent-subtle text-accent-subtle-text"
                  >
                    默认
                  </span>
                </div>
                <div class="truncate text-xs text-muted mt-0.5">{{ llmProviders[modelName]?.model || '（无模型名）' }}</div>
              </button>
              <button
                type="button"
                class="absolute right-2 top-1/2 -translate-y-1/2 p-1.5 rounded text-muted hover:text-danger hover:bg-danger-subtle opacity-0 group-hover:opacity-100 group-focus-within:opacity-100 transition-opacity"
                :aria-label="`删除模型 ${modelName}`"
                :title="`删除模型 ${modelName}`"
                @click.stop="deleteLlmProvider(modelName)"
              >
                ×
              </button>
            </div>
          </template>
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
        <template v-else-if="currentModule === 'settings'">
          <button
            v-for="c in settingsCategories"
            :key="c.id"
            @click="router.push(settingsRoutePath(c.id))"
            :class="[
              'w-full text-left px-3 py-2.5 rounded-lg text-sm transition-colors',
              settingsSection === c.id ? 'bg-accent-subtle text-accent-subtle-text' : 'hover:bg-list-hover text-list-hover-text'
            ]"
          >
            {{ c.label }}
          </button>
        </template>
      </div>
    </aside>

    <div v-if="middleColumnOpen" class="workspace-resizer" @mousedown="onMiddleResizeMouseDown" />

    <main class="main-right flex-1 flex flex-col min-h-0 overflow-hidden bg-page text-primary">
      <div
        v-show="currentModule === 'workspace'"
        class="flex-1 flex flex-col min-h-0 overflow-hidden"
      >
        <WorkspaceContent
          ref="workspaceContentRef"
          :selected-group-session-id="selectedGroupSessionId"
          :agent-instances="agentInstances"
          :skills="skills"
          :middle-column-open="middleColumnOpen"
          @middle-column-open-request="middleColumnOpen = true"
          @middle-column-toggle="toggleMiddleColumn"
          @message-sent="onChatMessageSent"
          @session-run-state="onSessionRunState"
          @scenario-new-session="onScenarioNewSession"
          @agent-added="onAgentAdded"
        />
      </div>
      <template v-if="currentModule === 'resource'">
        <template v-if="resourceSubModule === 'scenario'">
          <div class="h-full overflow-y-auto themed-scrollbar p-4">
            <div v-if="selectedScenarioPreset" class="max-w-5xl w-full mx-auto">
              <div class="mb-4">
                <h2 class="text-2xl font-semibold text-primary mb-1">
                  {{ isCreatingScenario ? '新建场景' : '配置场景' }}
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
                <div>
                  <label class="block text-sm font-medium text-primary mb-1">场景系统提示词（可选）</label>
                  <textarea
                    v-model="scenarioDraft.system_prompt"
                    rows="6"
                    class="w-full bg-input-bg text-primary border border-input-border rounded-lg px-3 py-2 text-sm leading-relaxed resize-y themed-scrollbar focus:outline-none focus:ring-2 focus:ring-input-focus-ring focus:border-input-focus-ring"
                    placeholder="写入仅适用于该场景的项目规则，会同时提供给主持人和场景内专家。"
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
                        <option v-if="missingScenarioLeaderLlmName" :value="missingScenarioLeaderLlmName">
                          缺失模型：{{ missingScenarioLeaderLlmName }}
                        </option>
                        <option v-for="modelName in llmModelNames" :key="modelName" :value="modelName">
                          {{ scenarioLlmOptionLabel(modelName) }}
                        </option>
                      </select>
                      <p v-if="missingScenarioLeaderLlmName" class="mt-1 text-xs text-red-600">
                        缺失模型：{{ missingScenarioLeaderLlmName }}
                      </p>
                    </div>
                  </div>
                  <div>
                    <label class="block text-sm font-medium text-primary mb-1">主持人系统提示词（可选）</label>
                    <textarea
                      v-model="scenarioLeaderSystemPrompt"
                      rows="6"
                      class="w-full bg-input-bg text-primary border border-input-border rounded-lg px-3 py-2 text-sm leading-relaxed resize-y themed-scrollbar focus:outline-none focus:ring-2 focus:ring-input-focus-ring focus:border-input-focus-ring"
                      placeholder="例如：你是群聊主持人，只负责决定下一位发言人与 next_action，不代写专家正文。"
                    />
                  </div>
                  <div>
                    <label class="block text-sm font-medium text-primary mb-2">技能与基础能力</label>
                    <div class="text-xs font-medium text-muted mb-1.5">主持人技能（单选）</div>
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
                        :key="sk.directory_name"
                        type="button"
                        class="px-3 py-1.5 rounded-full text-xs font-medium transition-colors border"
                        :class="scenarioLeaderSkillIds.some((item) => item.directory_name === sk.directory_name)
                          ? 'bg-accent-subtle text-accent-subtle-text border-accent/40 shadow-sm'
                          : 'bg-card text-muted border-border-light hover:bg-list-hover'"
                        @click="toggleScenarioLeaderSkill(sk.directory_name)"
                      >
                        {{ sk.name || sk.directory_name }}
                      </button>
                    </div>
                    <p v-if="skills.length && !filteredScenarioLeaderSkills.length" class="text-xs text-muted">没有匹配的 Skill</p>
                    <p v-else-if="!skills.length" class="text-xs text-muted">当前技能库为空，请先到左侧“技能”中新建或导入 Skill。</p>
                    <div v-if="missingScenarioLeaderSkillRefs.length" class="mt-3">
                      <div class="text-xs font-medium text-red-600 mb-1.5">缺失技能</div>
                      <div class="flex flex-wrap gap-2">
                        <span
                          v-for="item in missingScenarioLeaderSkillRefs"
                          :key="item.directory_name"
                          class="inline-flex items-center px-3 py-1.5 rounded-full text-xs font-medium border border-red-300 bg-red-50 text-red-700"
                          :title="`缺失技能路径：${item.directory_name}`"
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
                      v-for="name in scenarioDraft.agent_names || []"
                      :key="name"
                      class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium border"
                      :class="scenarioExpertMissing(name)
                        ? 'border-red-300 bg-red-50 text-red-700'
                        : 'border-accent/40 bg-accent-subtle text-accent-subtle-text'"
                      :title="scenarioExpertMissing(name) ? `缺失专家：${name}` : '已选择专家'"
                    >
                      {{ agentDisplayName(name) }}
                      <button
                        type="button"
                        class="ml-0.5 hover:text-danger"
                        :class="scenarioExpertMissing(name) ? 'text-red-700/80' : 'text-accent-subtle-text/80'"
                        @click="removeScenarioExpert(name)"
                      >×</button>
                    </span>
                    <span v-if="!(scenarioDraft.agent_names || []).length" class="text-xs text-muted">暂无专家</span>
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
                        :key="d.name"
                        type="button"
                        class="px-3 py-1.5 rounded-full text-xs font-medium transition-colors border border-border-light bg-card text-muted hover:bg-list-hover"
                        @click="addScenarioExpert(d.name)"
                      >
                        + {{ d.name }}
                      </button>
                      <span v-if="!scenarioAddableExperts.length" class="text-xs text-muted">可添加专家已为空</span>
                      <span v-else-if="!filteredScenarioAddableExperts.length" class="text-xs text-muted">无匹配专家</span>
                    </div>
                    <div v-if="missingScenarioExpertRefs.length" class="mt-3">
                      <div class="text-xs font-medium text-red-600 mb-1.5">缺失专家</div>
                      <div class="flex flex-wrap gap-2">
                        <span
                          v-for="item in missingScenarioExpertRefs"
                          :key="item.name"
                          class="inline-flex items-center px-3 py-1.5 rounded-full text-xs font-medium border border-red-300 bg-red-50 text-red-700"
                          :title="`缺失专家：${item.name}`"
                        >
                          {{ item.name }}
                        </span>
                      </div>
                    </div>
                  </div>
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
                    @click="deleteScenarioPreset(selectedScenarioPreset.name)"
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
          <AgentView
            :selected-agent-id="selectedId"
            :agent-instances="agentInstances"
            @created="onAgentCreated"
            @updated="fetchAgents"
            @cancel="selectedId = null"
          />
        </template>
        <template v-else-if="resourceSubModule === 'skill' && selectedId">
          <SkillDetailView
            :directory-name="selectedId"
            @updated="
              (newDirectoryName?: string) => {
                fetchSkills({ silent: true })
                if (newDirectoryName) selectedId = newDirectoryName
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
          <MCPDetailView :tool-name="selectedId" @updated="fetchMCP({ silent: true })" @deleted="selectedId = null; fetchMCP()" />
        </template>
        <template v-else-if="resourceSubModule === 'mcp'">
          <div class="flex flex-col h-full items-center justify-center text-muted text-sm p-4">
            <p>请从左侧选择 MCP 或添加新 MCP</p>
          </div>
        </template>
        <template v-else-if="resourceSubModule === 'llm'">
          <LLMSettingsView
            :llm-name="selectedId"
            :providers-version="llmProvidersVersion"
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
      <template v-if="currentModule === 'settings'">
        <AppSettingsView v-if="settingsSection === 'app'" />
        <ThemeSettingsView v-else-if="settingsSection === 'theme'" />
        <EnvVarsSettingsView v-else-if="settingsSection === 'env-vars'" />
        <AccountSecuritySettingsView v-else-if="settingsSection === 'account-security'" />
        <SandboxSettingsView v-else-if="settingsSection === 'sandbox'" />
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
          <div class="mb-4 space-y-1 text-sm border border-border-light rounded-lg p-3 bg-page">
            <div class="font-medium text-primary">{{ scenarioBundlePreview.bundle_preview.preset_name }}</div>
            <p class="text-xs text-muted leading-5">场景名称：{{ scenarioBundlePreview.bundle_preview.preset_name }}</p>
            <div v-if="(scenarioBundlePreview.bundle_preview.experts || []).length">
              <p class="text-xs text-muted leading-5">
                专家名称：{{ scenarioBundlePreview.bundle_preview.experts.map((ex) => ex.name).filter(Boolean).join('，') }}
              </p>
            </div>
            <div v-if="(scenarioBundlePreview.bundle_preview.skills || []).length">
              <p class="text-xs text-muted leading-5">
                技能名称：{{ displaySkillNames(scenarioBundlePreview.bundle_preview.skills || [], scenarioBundlePreview.bundle_preview.skill_display_names).join('，') }}
              </p>
            </div>
            <div v-if="(scenarioBundlePreview.bundle_preview.mcps || []).length">
              <p class="text-xs text-muted leading-5">
                工具名称：{{ displayMcpNames(scenarioBundlePreview.bundle_preview.mcps || []).join('，') }}
              </p>
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
                    <li v-for="item in group.items" :key="`${group.key}-${item.source}-${item.name}`">
                      <span>{{ missingReferenceTitle(group, item) }}</span>
                      <span v-if="missingRequiredByText(item)" class="text-red-600 dark:text-red-300">
                        ，被 {{ missingRequiredByText(item) }} 依赖
                      </span>
                    </li>
                  </ul>
                </div>
              </div>
              <p class="mt-2 text-xs">这些内容不会阻止导入，但导入后相关场景、专家或技能可能需要手动补齐。</p>
            </div>
            <div
              v-if="scenarioConflictPreviewRows.length"
              class="rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-amber-800 dark:bg-amber-950/20 dark:border-amber-500/50 dark:text-amber-300"
            >
              <div class="text-xs font-medium mb-1">同名内容将覆盖本地内容，冲突预览：</div>
              <ul class="list-disc pl-4 text-xs space-y-0.5">
                <li v-for="row in scenarioConflictPreviewRows" :key="row">{{ row }}</li>
              </ul>
            </div>
          </div>
        </template>
        <div class="flex justify-start gap-2">
          <button
            type="button"
            class="px-4 py-2 text-sm rounded-lg bg-accent text-text-inverse hover:bg-accent-hover disabled:opacity-50"
            :disabled="scenarioImportCommitting || !canConfirmScenarioImport"
            @click="commitScenarioImport"
          >
            {{ scenarioImportCommitting ? '导入中…' : '确认导入' }}
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

    <div
      v-if="agentImportModalOpen"
      class="fixed inset-0 z-[300] flex items-center justify-center p-4 bg-black/50"
      role="dialog"
      aria-modal="true"
      @click.self="onAgentImportBackdropClick"
    >
      <div
        class="max-w-lg w-full max-h-[85vh] overflow-y-auto rounded-xl border border-border-light bg-card shadow-xl p-5 text-primary themed-scrollbar relative"
        @click.stop
      >
        <div
          v-if="agentImportCommitting"
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
        <template v-if="agentImportResult">
          <h3 class="text-lg font-semibold mb-3">{{ agentImportResult.ok ? '导入成功' : '导入失败' }}</h3>
          <p
            class="text-sm mb-4 whitespace-pre-wrap"
            :class="agentImportResult.ok ? 'text-primary' : 'text-danger'"
          >
            {{ agentImportResult.message }}
          </p>
          <div class="flex justify-start">
            <button
              type="button"
              class="px-4 py-2 text-sm rounded-lg bg-accent text-text-inverse hover:bg-accent-hover"
              @click="closeAgentImportModal"
            >
              关闭
            </button>
          </div>
        </template>
        <template v-else>
        <h3 class="text-lg font-semibold mb-3">导入专家</h3>
        <template v-if="agentBundlePreview?.bundle_preview">
          <div class="mb-4 space-y-1 text-sm border border-border-light rounded-lg p-3 bg-page">
            <div class="font-medium text-primary">{{ agentBundlePreview.bundle_preview.name }}</div>
            <p class="text-xs text-muted leading-5">专家名称：{{ agentBundlePreview.bundle_preview.name || '未命名专家' }}</p>
            <div v-if="(agentBundlePreview.bundle_preview.skills || []).length">
              <p class="text-xs text-muted leading-5">
                技能名称：{{ displaySkillNames(agentBundlePreview.bundle_preview.skills || [], agentBundlePreview.bundle_preview.skill_display_names).join('，') }}
              </p>
            </div>
            <div v-if="(agentBundlePreview.bundle_preview.mcps || []).length">
              <p class="text-xs text-muted leading-5">
                工具名称：{{ displayMcpNames(agentBundlePreview.bundle_preview.mcps || []).join('，') }}
              </p>
            </div>
            <div
              v-if="hasImportMissingReferences(agentBundlePreview.bundle_preview.missing_references)"
              class="rounded-lg border border-red-300 bg-red-50 px-3 py-2 text-red-700 dark:bg-red-950/20 dark:border-red-500/50 dark:text-red-300"
            >
              <div class="text-xs font-medium mb-1">缺失内容</div>
              <div class="space-y-2">
                <div v-for="group in missingReferenceGroups(agentBundlePreview.bundle_preview.missing_references)" :key="group.key">
                  <div class="text-xs font-medium">{{ group.label }}</div>
                  <ul class="mt-1 list-disc pl-4 text-xs space-y-0.5">
                    <li v-for="item in group.items" :key="`${group.key}-${item.source}-${item.name}`">
                      <span>{{ missingReferenceTitle(group, item) }}</span>
                      <span v-if="missingRequiredByText(item)" class="text-red-600 dark:text-red-300">
                        ，被 {{ missingRequiredByText(item) }} 依赖
                      </span>
                    </li>
                  </ul>
                </div>
              </div>
              <p class="mt-2 text-xs">这些内容不会阻止导入，但导入后相关场景、专家或技能可能需要手动补齐。</p>
            </div>
            <div
              v-if="agentConflictPreviewRows.length"
              class="rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-amber-800 dark:bg-amber-950/20 dark:border-amber-500/50 dark:text-amber-300"
            >
              <div class="text-xs font-medium mb-1">同名内容将覆盖本地内容，冲突预览：</div>
              <ul class="list-disc pl-4 text-xs space-y-0.5">
                <li v-for="row in agentConflictPreviewRows" :key="row">{{ row }}</li>
              </ul>
            </div>
          </div>
        </template>
        <div class="flex justify-start gap-2">
          <button
            type="button"
            class="px-4 py-2 text-sm rounded-lg bg-accent text-text-inverse hover:bg-accent-hover disabled:opacity-50"
            :disabled="agentImportCommitting || !canConfirmAgentImport"
            @click="commitAgentImport"
          >
            {{ agentImportCommitting ? '导入中…' : '确认导入' }}
          </button>
          <button
            type="button"
            class="px-4 py-2 text-sm rounded-lg border border-border-light bg-card hover:bg-list-hover disabled:opacity-50"
            :disabled="agentImportCommitting"
            @click="closeAgentImportModal"
          >
            取消
          </button>
        </div>
        </template>
      </div>
    </div>

    <div
      v-if="llmImportModalOpen"
      class="fixed inset-0 z-[300] flex items-center justify-center p-4 bg-black/50"
      role="dialog"
      aria-modal="true"
      @click.self="onLlmImportBackdropClick"
    >
      <div
        class="max-w-lg w-full max-h-[85vh] overflow-y-auto rounded-xl border border-border-light bg-card shadow-xl p-5 text-primary themed-scrollbar relative"
        @click.stop
      >
        <div
          v-if="llmImportCommitting"
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
        <template v-if="llmImportResult">
          <h3 class="text-lg font-semibold mb-3">{{ llmImportResult.ok ? '导入成功' : '导入失败' }}</h3>
          <p
            class="text-sm mb-4 whitespace-pre-wrap"
            :class="llmImportResult.ok ? 'text-primary' : 'text-danger'"
          >
            {{ llmImportResult.message }}
          </p>
          <div class="flex justify-start">
            <button
              type="button"
              class="px-4 py-2 text-sm rounded-lg bg-accent text-text-inverse hover:bg-accent-hover"
              @click="closeLlmImportModal"
            >
              关闭
            </button>
          </div>
        </template>
        <template v-else>
          <h3 class="text-lg font-semibold mb-3">导入模型</h3>
          <template v-if="llmBundlePreview?.bundle_preview">
            <div class="mb-4 space-y-1 text-sm border border-border-light rounded-lg p-3 bg-page">
              <div class="font-medium text-primary">{{ llmBundlePreview.bundle_preview.name }}</div>
              <p class="text-xs text-muted leading-5">
                模型型号：{{ llmBundlePreview.bundle_preview.provider.model || '未填写' }}
              </p>
              <p class="text-xs text-muted leading-5">
                URL：{{ llmBundlePreview.bundle_preview.provider.base_url || '未填写' }}
              </p>
              <p
                v-if="llmBundlePreview.bundle_preview.would_conflict_name"
                class="mt-2 text-xs rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-amber-800 dark:bg-amber-950/20 dark:border-amber-500/50 dark:text-amber-300"
              >
                同名模型已存在，请先删除或改名后再导入；不会导入 API Key 明文。
              </p>
            </div>
          </template>
          <div class="flex justify-start gap-2">
            <button
              type="button"
              class="px-4 py-2 text-sm rounded-lg bg-accent text-text-inverse hover:bg-accent-hover disabled:opacity-50"
              :disabled="llmImportCommitting || !canConfirmLlmImport"
              @click="commitLlmImport"
            >
              {{ llmImportCommitting ? '导入中…' : '确认导入' }}
            </button>
            <button
              type="button"
              class="px-4 py-2 text-sm rounded-lg border border-border-light bg-card hover:bg-list-hover disabled:opacity-50"
              :disabled="llmImportCommitting"
              @click="closeLlmImportModal"
            >
              取消
            </button>
          </div>
        </template>
      </div>
    </div>

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
            <p class="text-xs text-amber-700 dark:text-amber-400">同名技能将覆盖本地内容；名称不同会作为新版本导入。</p>
          </div>
          <div class="flex justify-start gap-2">
            <button
              type="button"
              class="px-4 py-2 text-sm rounded-lg bg-accent text-text-inverse hover:bg-accent-hover disabled:opacity-50"
              :disabled="skillZipImporting || !pendingSkillZipFile"
              @click="commitSkillZipImport"
            >
              {{ skillZipImporting ? '导入中…' : '确认导入' }}
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
import { computed, onBeforeUnmount, onMounted, ref, inject } from 'vue'
import { useRouter, useRoute } from 'vue-router'

import WorkspaceContent from '@/features/workspace/WorkspaceContent.vue'
import WorkspaceFilesView from '@/features/workspace/WorkspaceFilesView.vue'
import AgentView from '@/features/resources/AgentView.vue'
import SkillDetailView from '@/features/resources/SkillDetailView.vue'
import MCPDetailView from '@/features/resources/MCPDetailView.vue'
import MCPAddView from '@/features/resources/MCPAddView.vue'
import LLMSettingsView from '@/features/resources/LLMSettingsView.vue'
import { useBundleImports } from '@/features/resources/useBundleImports'
import { useFileSessions } from '@/features/resources/useFileSessions'
import { useResourceSearch } from '@/features/resources/useResourceSearch'
import { useResourceCollections } from '@/features/resources/useResourceCollections'
import { useScenarioEditor, type ScenarioHostConfig } from '@/features/resources/useScenarioEditor'
import { useZipResourceImports } from '@/features/resources/useZipResourceImports'
import AppSettingsView from '@/features/settings/AppSettingsView.vue'
import ThemeSettingsView from '@/features/settings/ThemeSettingsView.vue'
import AccountSecuritySettingsView from '@/features/settings/AccountSecuritySettingsView.vue'
import SandboxSettingsView from '@/features/settings/SandboxSettingsView.vue'
import EnvVarsSettingsView from '@/features/settings/EnvVarsSettingsView.vue'
import { appConfirm } from '@/composables/useAppDialog'
import { THEME_AUTH_CHANGED_EVENT, useTheme } from '@/composables/useTheme'
import SessionMemberAvatars from '@/features/shell/SessionMemberAvatars.vue'
import MainNavigationRail from '@/features/shell/MainNavigationRail.vue'
import ResourceImportIcon from '@/components/icons/ResourceImportIcon.vue'
import { resourceIconStyle } from '@/features/resources/resourceIconStyle'
import resourceNewIconUrl from '@/assets/icons/resources/new.svg'
import resourceSearchIconUrl from '@/assets/icons/resources/search.svg'
import { displaySessionTitle, formatSessionDate as formatDate } from '@/features/shell/sessionListDisplay'
import { useGroupSessions } from '@/features/shell/useGroupSessions'
import {
  settingsCategories,
  settingsRoutePath,
  useMainRouteState,
} from '@/features/shell/mainNavigation'
import { useMainModuleLifecycle } from '@/features/shell/useMainModuleLifecycle'
import { useMiddleColumnLayout } from '@/features/shell/useMiddleColumnLayout'
import { useSessionNotices } from '@/features/shell/useSessionNotices'
import './MainView.css'

const router = useRouter()
const route = useRoute()
inject<ReturnType<typeof useTheme>>('theme') ?? useTheme()

const LOGIN_STORAGE_KEY = 'dha_logged_in'
const USER_STORAGE_KEY = 'dha_user'
const USER_ID_STORAGE_KEY = 'dha_user_id'
const TOKEN_STORAGE_KEY = 'dha_token'

async function logout() {
  const ok = await appConfirm({
    title: '退出账号',
    message: '确定要退出当前账号吗？',
    variant: 'warning',
    confirmText: '退出',
  })
  if (!ok) return
  localStorage.removeItem(LOGIN_STORAGE_KEY)
  localStorage.removeItem(USER_STORAGE_KEY)
  localStorage.removeItem(USER_ID_STORAGE_KEY)
  localStorage.removeItem(TOKEN_STORAGE_KEY)
  window.dispatchEvent(new Event(THEME_AUTH_CHANGED_EVENT))
  router.push('/login')
}

const selectedId = ref<string | null>(null)
const llmProvidersVersion = ref(0)
const resourceMenuExpanded = ref(false)
const { currentModule, resourceSubModule, settingsSection } = useMainRouteState(route)
const {
  fileSessions,
  fileSessionsLoading,
  fileSessionSearch,
  fileSessionSort,
  visibleFileSessions,
  fetchFileSessions,
} = useFileSessions({ resourceSubModule, selectedId })
const {
  showScenarioSearch,
  showAgentSearch,
  showSkillSearch,
  showMcpSearch,
  showLlmSearch,
  scenarioSearch,
  agentSearch,
  skillSearch,
  mcpSearch,
  llmSearch,
  toggleSearch,
  resetResourceSearchesForSectionChange,
} = useResourceSearch()

const selectedGroupSessionId = ref<string | null>(null)
const {
  skills,
  skillsLoading,
  mcpLoading,
  llmDefault,
  llmProviders,
  llmLoading,
  llmModelNames,
  filteredLlmModelNames,
  agentInstances,
  agentInstancesLoading,
  filteredAgentInstances,
  filteredSkills,
  filteredMcpServers,
  fetchSkills,
  fetchAgents,
  deleteAgentInstance,
  deleteSkill,
  fetchMCP,
  deleteMcpServer,
  fetchLLM,
  deleteLlmProvider,
  createEmptySkill,
  onAgentCreated,
  onMCPCreated,
} = useResourceCollections({
  currentModule,
  resourceSubModule,
  selectedId,
  agentSearch,
  skillSearch,
  mcpSearch,
  llmSearch,
})
const {
  scenarioLoading,
  scenarioSaving,
  scenarioExpertSearch,
  scenarioLeaderSkillSearch,
  scenarioLeaderDisplayName,
  scenarioLeaderSkillIds,
  scenarioLeaderSystemPrompt,
  scenarioLeaderLlmId,
  scenarioDraft,
  isCreatingScenario,
  scenarioPresets,
  filteredScenarioPresets,
  selectedScenarioPreset,
  scenarioAddableExperts,
  filteredScenarioAddableExperts,
  filteredScenarioLeaderSkills,
  missingScenarioExpertRefs,
  missingScenarioLeaderSkillRefs,
  missingScenarioLeaderLlmName,
  agentDisplayName,
  scenarioExpertMissing,
  scenarioLlmOptionLabel,
  toggleScenarioLeaderSkill,
  createScenarioPreset,
  removeScenarioExpert,
  addScenarioExpert,
  saveScenarioPreset,
  deleteScenarioPreset,
  fetchScenarioPresets,
} = useScenarioEditor({
  selectedId,
  resourceSubModule,
  scenarioSearch,
  agentInstances,
  skills,
  llmProviders,
})
const {
  skillZipInputRef,
  skillZipImporting,
  skillImportModalOpen,
  pendingSkillZipFile,
  skillImportResult,
  mcpZipInputRef,
  mcpZipImporting,
  triggerSkillZipImport,
  onSkillZipSelected,
  closeSkillImportModal,
  onSkillImportBackdropClick,
  commitSkillZipImport,
  triggerMcpZipImport,
  onMcpZipSelected,
} = useZipResourceImports({ selectedId, fetchSkills, fetchMCP })
const {
  scenarioImportFileInputRef,
  scenarioImportModalOpen,
  scenarioImportCommitting,
  scenarioImportResult,
  scenarioBundlePreview,
  agentImportFileInputRef,
  agentImportModalOpen,
  agentImportCommitting,
  agentImportResult,
  agentBundlePreview,
  llmImportFileInputRef,
  llmImportModalOpen,
  llmImportCommitting,
  llmImportResult,
  llmBundlePreview,
  canConfirmAgentImport,
  canConfirmScenarioImport,
  canConfirmLlmImport,
  displaySkillNames,
  displayMcpNames,
  hasImportMissingReferences,
  missingReferenceGroups,
  missingRequiredByText,
  missingReferenceTitle,
  scenarioConflictPreviewRows,
  agentConflictPreviewRows,
  pickScenarioImportFile,
  closeScenarioImportModal,
  onScenarioImportBackdropClick,
  onScenarioImportFile,
  commitScenarioImport,
  exportScenarioBundle,
  pickAgentImportFile,
  closeAgentImportModal,
  onAgentImportBackdropClick,
  onAgentImportFile,
  commitAgentImport,
  pickLlmImportFile,
  closeLlmImportModal,
  onLlmImportBackdropClick,
  onLlmImportFile,
  commitLlmImport,
} = useBundleImports({
  skills,
  selectedId,
  selectedScenarioPreset,
  isCreatingScenario,
  fetchScenarioPresets,
  fetchAgents,
  fetchSkills,
  fetchMCP,
  fetchLLM,
  onLlmListChanged: () => {
    llmProvidersVersion.value += 1
  },
})

const {
  middleColumnWidth,
  middleColumnOpen,
  toggleMiddleColumn,
  ensureMiddleColumnOpen,
  onMiddleResizeMouseDown,
} = useMiddleColumnLayout()

const {
  sessionNotice,
  clearSessionUpdateNotice,
  onSessionRunState,
  syncSessionRuntimeNotices,
} = useSessionNotices({ currentModule, selectedGroupSessionId })

const {
  groupSessions,
  groupSessionsLoading,
  creatingSession,
  fetchGroupSessions,
  onScenarioNewSession,
  createNewSession,
  selectGroupSession,
  deleteGroupSession,
} = useGroupSessions({
  selectedGroupSessionId,
  syncSessionRuntimeNotices,
  clearSessionUpdateNotice,
})

const {
  onNavClick,
  onResourceChildClick,
} = useMainModuleLifecycle({
  router,
  currentModule,
  resourceSubModule,
  settingsSection,
  selectedId,
  resourceMenuExpanded,
  ensureMiddleColumnOpen,
  resetResourceSearchesForSectionChange,
  fetchScenarioPresets,
  fetchSkills,
  fetchMCP,
  fetchAgents,
  fetchLLM,
  fetchFileSessions,
  fetchGroupSessions,
})

const workspaceContentRef = ref<{
  refresh: () => void
  createSessionFromScenarioPreset: (p: {
    name: string
    agent_names: string[]
    host?: ScenarioHostConfig
    description?: string
    system_prompt?: string
  }) => Promise<string | null>
} | null>(null)
const newSessionMenuRoot = ref<HTMLElement | null>(null)
const newSessionMenuOpen = ref(false)
const newSessionMenuScenarios = computed(() =>
  (scenarioPresets.value || []).filter((scenario) => (scenario.name || '').trim() || (scenario.agent_names || []).length),
)

function closeNewSessionMenu() {
  newSessionMenuOpen.value = false
}

function toggleNewSessionMenu() {
  if (creatingSession.value) return
  newSessionMenuOpen.value = !newSessionMenuOpen.value
  if (newSessionMenuOpen.value) {
    fetchScenarioPresets()
  }
}

function onDocumentClickForNewSessionMenu(event: MouseEvent) {
  if (!newSessionMenuOpen.value) return
  const root = newSessionMenuRoot.value
  if (root && event.target instanceof Node && root.contains(event.target)) return
  closeNewSessionMenu()
}

function onDocumentKeydownForNewSessionMenu(event: KeyboardEvent) {
  if (event.key === 'Escape') closeNewSessionMenu()
}

async function createBlankSessionFromMenu() {
  closeNewSessionMenu()
  await createNewSession()
}

async function createScenarioSessionFromMenu(scenario: {
  name: string
  agent_names: string[]
  host?: ScenarioHostConfig
  description?: string
  system_prompt?: string
}) {
  closeNewSessionMenu()
  await workspaceContentRef.value?.createSessionFromScenarioPreset(scenario)
}

onMounted(() => {
  document.addEventListener('click', onDocumentClickForNewSessionMenu)
  document.addEventListener('keydown', onDocumentKeydownForNewSessionMenu)
})

onBeforeUnmount(() => {
  document.removeEventListener('click', onDocumentClickForNewSessionMenu)
  document.removeEventListener('keydown', onDocumentKeydownForNewSessionMenu)
})

async function onChatMessageSent() {
  workspaceContentRef.value?.refresh()
  await fetchGroupSessions()
}

async function onAgentAdded() {
  workspaceContentRef.value?.refresh()
  await fetchGroupSessions()
}
</script>
