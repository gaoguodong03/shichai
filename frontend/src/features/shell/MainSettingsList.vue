<template>
  <button
    v-for="category in settingsCategories"
    :key="category.id"
    @click="$emit('select', category.id)"
    :class="[
      'w-full text-left px-3 py-2.5 rounded-lg text-sm transition-colors',
      settingsSection === category.id ? 'bg-accent-subtle text-accent-subtle-text' : 'hover:bg-list-hover text-list-hover-text'
    ]"
  >
    {{ category.label }}
  </button>
</template>

<script setup lang="ts">
import { settingsCategories, type SettingsCategoryId } from '@/features/shell/mainNavigation'

defineProps<{
  settingsSection: SettingsCategoryId
}>()

defineEmits<{
  (event: 'select', id: SettingsCategoryId): void
}>()
</script>
