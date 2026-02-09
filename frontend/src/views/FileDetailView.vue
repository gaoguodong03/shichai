<template>
  <div class="flex flex-col h-full bg-white overflow-y-auto">
    <header class="border-b border-gray-200 px-4 py-3 flex items-center justify-between gap-2">
      <!-- 可编辑文件名 -->
      <div class="flex-1 min-w-0 flex items-center gap-2">
        <input
          v-if="editingName"
          ref="nameInputRef"
          v-model="editFileName"
          class="flex-1 px-2 py-1 text-lg font-semibold border border-gray-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500"
          @blur="saveName"
          @keydown.enter="saveName"
        />
        <h1
          v-else
          class="text-lg font-semibold text-gray-800 truncate cursor-pointer hover:bg-gray-100 rounded px-1 -mx-1"
          :title="'点击编辑文件名'"
          @dblclick="startEditName"
        >
          {{ displayName }}
        </h1>
        <button
          v-if="!editingName && isEditableText"
          class="px-2 py-1 text-xs text-gray-500 hover:text-blue-600"
          @click="startEditName"
        >
          重命名
        </button>
      </div>
      <div class="flex items-center gap-2 flex-shrink-0">
        <a
          :href="downloadUrl"
          target="_blank"
          rel="noopener noreferrer"
          class="px-3 py-1.5 text-sm bg-blue-500 text-white rounded-lg hover:bg-blue-600"
        >
          下载
        </a>
      </div>
    </header>
    <div class="flex-1 overflow-auto p-4 flex flex-col">
      <!-- 图片预览 -->
      <img
        v-if="isImage"
        :src="downloadUrl"
        :alt="path"
        class="max-w-full h-auto rounded border border-gray-200"
      />
      <!-- 文本可编辑 -->
      <template v-else-if="isEditableText">
        <div v-if="editingContent" class="flex-1 flex flex-col min-h-0">
          <textarea
            ref="contentTextareaRef"
            v-model="editContent"
            class="flex-1 w-full p-3 text-sm font-sans border border-gray-300 rounded resize-none focus:outline-none focus:ring-2 focus:ring-blue-500"
            spellcheck="false"
          />
          <div class="mt-2 flex gap-2">
            <button
              class="px-4 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600"
              @click="saveContent"
            >
              保存
            </button>
            <button
              class="px-4 py-2 border border-gray-300 rounded-lg hover:bg-gray-100"
              @click="cancelEditContent"
            >
              取消
            </button>
          </div>
        </div>
        <div v-else>
          <pre class="text-sm text-gray-800 whitespace-pre-wrap break-words font-sans">{{ previewText ?? '' }}</pre>
          <button
            class="mt-2 px-3 py-1.5 text-sm border border-gray-300 rounded-lg hover:bg-gray-100"
            @click="startEditContent"
          >
            编辑内容
          </button>
        </div>
      </template>
      <div v-else class="text-sm text-gray-500">不支持预览或编辑，请下载查看</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'

const props = defineProps<{ path: string }>()
const emit = defineEmits<{ (e: 'renamed', newPath: string): void }>()

const downloadUrl = computed(() => `/api/files/download?path=${encodeURIComponent(currentPath.value)}`)

const imageExtensions = /\.(jpe?g|png|gif|webp|bmp|svg)$/i
const isImage = computed(() => imageExtensions.test(currentPath.value))

const textExts = ['txt', 'md', 'json', 'yaml', 'yml', 'html', 'css', 'js', 'ts', 'py', 'log']
const isEditableText = computed(() => {
  const ext = currentPath.value.split('.').pop()?.toLowerCase()
  return !isImage.value && textExts.includes(ext || '')
})

const currentPath = ref(props.path)
const displayName = computed(() => {
  const p = currentPath.value
  return p.split('/').pop() || p
})

const previewText = ref<string | null>(null)
const editingName = ref(false)
const editFileName = ref('')
const nameInputRef = ref<HTMLInputElement | null>(null)

const editingContent = ref(false)
const editContent = ref('')
const contentTextareaRef = ref<HTMLTextAreaElement | null>(null)

async function loadContent() {
  if (!currentPath.value || isImage.value) return
  if (!isEditableText.value) {
    previewText.value = null
    return
  }
  try {
    const r = await fetch(downloadUrl.value)
    if (r.ok) {
      const t = await r.text()
      previewText.value = t
    } else {
      previewText.value = null
    }
  } catch {
    previewText.value = null
  }
}

function startEditName() {
  editFileName.value = displayName.value
  editingName.value = true
  setTimeout(() => nameInputRef.value?.focus(), 50)
}

async function saveName() {
  if (!editingName.value) return
  const newName = editFileName.value.trim()
  if (!newName || newName === displayName.value) {
    editingName.value = false
    return
  }
  try {
    const r = await fetch(`/api/files/rename?path=${encodeURIComponent(currentPath.value)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ new_name: newName }),
    })
    const j = await r.json()
    if (j.status === 'ok' && j.data?.path) {
      currentPath.value = j.data.path
      emit('renamed', j.data.path)
      await loadContent()
    }
  } catch (e) {
    console.error('重命名失败', e)
  }
  editingName.value = false
}

function startEditContent() {
  editContent.value = previewText.value ?? ''
  editingContent.value = true
  setTimeout(() => contentTextareaRef.value?.focus(), 50)
}

function cancelEditContent() {
  editingContent.value = false
}

async function saveContent() {
  try {
    const r = await fetch(`/api/files/content?path=${encodeURIComponent(currentPath.value)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content: editContent.value }),
    })
    const j = await r.json()
    if (j.status === 'ok') {
      previewText.value = editContent.value
      editingContent.value = false
    }
  } catch (e) {
    console.error('保存失败', e)
  }
}

watch(() => props.path, (p) => { currentPath.value = p }, { immediate: true })
watch(currentPath, loadContent, { immediate: true })
</script>
