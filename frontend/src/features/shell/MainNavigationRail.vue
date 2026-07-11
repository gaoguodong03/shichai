<template>
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
        @click="$emit('nav-click', 'workspace')"
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
        @click="$emit('nav-click', 'resource')"
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
          @click="$emit('resource-child-click', child.id)"
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
        @click="$emit('nav-click', 'settings')"
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
        @click="$emit('logout')"
        :class="[
          'w-full flex items-center justify-center px-2 py-2.5 rounded-lg text-sm font-medium transition-colors',
          'text-nav-text hover:bg-nav-hover-bg'
        ]"
      >
        登出
      </button>
    </div>
  </nav>
</template>

<script setup lang="ts">
import logoUrl from '@/assets/49logo.png'
import { resourceChildren, type ModuleId, type ResourceSubModule } from '@/features/shell/mainNavigation'

defineProps<{
  currentModule: ModuleId
  resourceSubModule: ResourceSubModule
  resourceMenuExpanded: boolean
}>()

defineEmits<{
  (event: 'nav-click', module: ModuleId): void
  (event: 'resource-child-click', id: ResourceSubModule): void
  (event: 'logout'): void
}>()
</script>
