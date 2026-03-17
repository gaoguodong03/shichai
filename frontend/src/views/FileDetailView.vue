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
      <!-- PDF 预览 -->
      <div v-else-if="isPDF" class="flex-1 min-h-0">
        <VuePdfEmbed :source="downloadUrl" class="pdf-viewer" />
      </div>
      <!-- DOCX 预览 -->
      <div v-else-if="isDocx" class="flex-1 min-h-0">
        <div v-if="docxLoading" class="text-sm text-gray-500 py-8">加载中...</div>
        <div v-else-if="docxError" class="text-sm text-red-500 py-4">{{ docxError }}</div>
        <div v-show="!docxLoading && !docxError" ref="docxContainerRef" class="docx-preview overflow-auto" />
      </div>
      <!-- Excel 预览 -->
      <div v-else-if="isExcel" class="flex-1 min-h-0">
        <div v-if="excelLoading" class="text-sm text-gray-500 py-8">加载中...</div>
        <div v-else-if="excelError" class="text-sm text-red-500 py-4">{{ excelError }}</div>
        <div v-show="!excelLoading && !excelError" class="excel-preview overflow-auto" v-html="excelHtml" />
      </div>
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
        <div v-else class="flex flex-col gap-2">
          <!-- .md 默认渲染为 Markdown，可切换为源文件 -->
          <div v-if="isMarkdown && !showMdSource" class="prose prose-sm max-w-none text-gray-800 file-detail-markdown" v-html="renderMarkdown(previewText ?? '')" />
          <pre v-else class="text-sm text-gray-800 whitespace-pre-wrap break-words font-sans">{{ previewText ?? '' }}</pre>
          <div class="flex flex-wrap items-center gap-2 mt-1">
            <button
              v-if="isMarkdown"
              class="px-3 py-1.5 text-sm border border-gray-300 rounded-lg hover:bg-gray-100"
              @click="showMdSource = !showMdSource"
            >
              {{ showMdSource ? '显示渲染' : '显示源文件' }}
            </button>
            <button
              class="px-3 py-1.5 text-sm border border-gray-300 rounded-lg hover:bg-gray-100"
              @click="startEditContent"
            >
              编辑内容
            </button>
          </div>
        </div>
      </template>
      <div v-else class="text-sm text-gray-500">不支持预览或编辑，请下载查看</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick } from 'vue'
import VuePdfEmbed from 'vue-pdf-embed'
import { renderAsync } from 'docx-preview'
import * as XLSX from 'xlsx'
import MarkdownIt from 'markdown-it'

const props = defineProps<{ path: string; workspaceId?: string }>()
const emit = defineEmits<{ (e: 'renamed', newPath: string): void }>()

const downloadUrl = computed(() => {
  const p = currentPath.value
  if (props.workspaceId) {
    return `/api/workspaces/${encodeURIComponent(props.workspaceId)}/files/download?path=${encodeURIComponent(p)}`
  }
  return `/api/files/download?path=${encodeURIComponent(p)}`
})

const imageExtensions = /\.(jpe?g|png|gif|webp|bmp|svg)$/i
const isImage = computed(() => imageExtensions.test(currentPath.value))

const pdfExtensions = /\.pdf$/i
const isPDF = computed(() => pdfExtensions.test(currentPath.value))

const docxExtensions = /\.docx?$/i
const isDocx = computed(() => docxExtensions.test(currentPath.value))

const excelExtensions = /\.(xlsx|xls|csv)$/i
const isExcel = computed(() => excelExtensions.test(currentPath.value))

const textExts = ['txt', 'md', 'json', 'yaml', 'yml', 'html', 'css', 'js', 'ts', 'py', 'log']
const isEditableText = computed(() => {
  const ext = currentPath.value.split('.').pop()?.toLowerCase()
  return !isImage.value && !isPDF.value && !isDocx.value && !isExcel.value && textExts.includes(ext || '')
})

const isMarkdown = computed(() => /\.md$/i.test(currentPath.value))
const showMdSource = ref(false)
// 与对话区保持一致：单个换行当空格处理
const md = new MarkdownIt({ html: false, linkify: true, breaks: false })
function renderMarkdown(text: string): string {
  if (!text) return ''
  try {
    return md.render(text)
  } catch {
    return text
  }
}

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

// DOCX 预览
const docxContainerRef = ref<HTMLElement | null>(null)
const docxLoading = ref(false)
const docxError = ref<string | null>(null)

// Excel 预览
const excelHtml = ref('')
const excelLoading = ref(false)
const excelError = ref<string | null>(null)

async function loadDocx() {
  if (!currentPath.value || !isDocx.value) return
  docxLoading.value = true
  docxError.value = null
  try {
    const r = await fetch(downloadUrl.value)
    if (!r.ok) throw new Error('加载失败')
    const blob = await r.blob()
    await nextTick()
    const container = docxContainerRef.value
    if (!container) return
    container.innerHTML = ''
    await renderAsync(blob, container)
  } catch (e) {
    docxError.value = e instanceof Error ? e.message : '预览失败，请下载查看'
  } finally {
    docxLoading.value = false
  }
}

async function loadExcel() {
  if (!currentPath.value || !isExcel.value) return
  excelLoading.value = true
  excelError.value = null
  excelHtml.value = ''
  try {
    const r = await fetch(downloadUrl.value)
    if (!r.ok) throw new Error('加载失败')
    const buffer = await r.arrayBuffer()
    const wb = XLSX.read(buffer, { type: 'array' })
    const firstSheetName = wb.SheetNames[0]
    if (!firstSheetName) throw new Error('无工作表')
    const sheet = wb.Sheets[firstSheetName]
    const html = XLSX.utils.sheet_to_html(sheet, { id: 'excel-table', editable: false })
    excelHtml.value = html || '<p class="text-gray-500">空表格</p>'
  } catch (e) {
    excelError.value = e instanceof Error ? e.message : '预览失败，请下载查看'
  } finally {
    excelLoading.value = false
  }
}

async function loadContent() {
  if (!currentPath.value || isImage.value) return
  if (!isEditableText.value) {
    previewText.value = null
    return
  }
  try {
    const r = await fetch(downloadUrl.value, { cache: 'no-store' })
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
    const path = currentPath.value
    const url = props.workspaceId
      ? `/api/workspaces/${encodeURIComponent(props.workspaceId)}/files/rename?path=${encodeURIComponent(path)}`
      : `/api/files/rename?path=${encodeURIComponent(path)}`
    const r = await fetch(url, {
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
    const path = currentPath.value
    const url = props.workspaceId
      ? `/api/workspaces/${encodeURIComponent(props.workspaceId)}/files/content?path=${encodeURIComponent(path)}`
      : `/api/files/content?path=${encodeURIComponent(path)}`
    const r = await fetch(url, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content: editContent.value }),
    })
    const j = await r.json()
    if (j.status === 'ok') {
      previewText.value = editContent.value
      editingContent.value = false
    } else {
      alert('保存失败：' + (j.detail || '未知错误'))
    }
  } catch (e) {
    console.error('保存失败', e)
    alert('保存失败，请检查网络或后端服务')
  }
}

watch(() => props.path, (p) => {
  currentPath.value = p
  showMdSource.value = false
}, { immediate: true })
watch(currentPath, loadContent, { immediate: true })
watch([currentPath, isDocx], () => {
  if (isDocx.value) loadDocx()
  else { docxError.value = null }
}, { immediate: true })
watch([currentPath, isExcel], () => {
  if (isExcel.value) loadExcel()
  else { excelError.value = null; excelHtml.value = '' }
}, { immediate: true })
</script>

<style scoped>
.pdf-viewer {
  width: 100%;
  min-height: 600px;
}
.docx-preview :deep(*) {
  max-width: 100%;
}
.excel-preview :deep(table) {
  border-collapse: collapse;
  font-size: 0.875rem;
}
.excel-preview :deep(th),
.excel-preview :deep(td) {
  border: 1px solid #e5e7eb;
  padding: 0.25rem 0.5rem;
}
.excel-preview :deep(th) {
  background: #f3f4f6;
  font-weight: 600;
}
.file-detail-markdown :deep(h1) { font-size: 1.5rem; font-weight: 700; margin-top: 0.5rem; margin-bottom: 0.5rem; }
.file-detail-markdown :deep(h2) { font-size: 1.25rem; font-weight: 600; margin-top: 0.75rem; margin-bottom: 0.25rem; }
.file-detail-markdown :deep(h3) { font-size: 1.125rem; font-weight: 600; margin-top: 0.5rem; }
.file-detail-markdown :deep(p) { margin-bottom: 0.5rem; }
.file-detail-markdown :deep(ul) { list-style-type: disc; margin-left: 1.5rem; margin-bottom: 0.5rem; }
.file-detail-markdown :deep(ol) { list-style-type: decimal; margin-left: 1.5rem; margin-bottom: 0.5rem; }
.file-detail-markdown :deep(pre) { background: #f3f4f6; padding: 0.5rem 0.75rem; border-radius: 0.25rem; overflow-x: auto; margin: 0.5rem 0; }
.file-detail-markdown :deep(code) { background: #f3f4f6; padding: 0.125rem 0.25rem; border-radius: 0.125rem; font-size: 0.875em; }
.file-detail-markdown :deep(a) { color: #2563eb; text-decoration: underline; }
</style>
