<template>
  <div class="flex flex-col h-full bg-card text-primary overflow-y-auto">
    <header class="border-b border-border px-4 py-3 flex items-center justify-between gap-2">
      <!-- 可编辑文件名 -->
      <div class="flex-1 min-w-0 flex items-center gap-2">
        <input
          v-if="editingName"
          ref="nameInputRef"
          v-model="editFileName"
          class="flex-1 px-2 py-1 text-lg font-semibold border border-input-border bg-input-bg text-primary rounded focus:outline-none focus:ring-2 focus:ring-input-focus-ring"
          @blur="saveName"
          @keydown.enter="saveName"
        />
        <h1
          v-else
          class="text-lg font-semibold text-primary truncate cursor-pointer hover:bg-list-hover rounded px-1 -mx-1"
          :title="'点击编辑文件名'"
          @dblclick="startEditName"
        >
          {{ displayName }}
        </h1>
        <button
          v-if="!editingName && isEditableText"
          class="px-2 py-1 text-xs text-muted hover:text-accent"
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
          class="px-3 py-1.5 text-sm bg-accent text-text-inverse rounded-lg hover:bg-accent-hover"
        >
          下载
        </a>
      </div>
    </header>
    <div ref="scrollContainerRef" class="flex-1 overflow-auto p-4 flex flex-col">
      <!-- 图片预览 -->
      <img
        v-if="isImage"
        :src="downloadUrl"
        :alt="path"
        class="max-w-full h-auto rounded border border-border"
      />
      <!-- PDF 预览 -->
      <div v-else-if="isPDF" class="flex-1 min-h-0">
        <VuePdfEmbed :source="downloadUrl" class="pdf-viewer" />
      </div>
      <!-- DOCX 预览 -->
      <div v-else-if="isDocx" class="flex-1 min-h-0">
        <div v-if="docxLoading" class="text-sm text-muted py-8">加载中...</div>
        <div v-else-if="docxError" class="text-sm text-red-500 py-4">{{ docxError }}</div>
        <div v-show="!docxLoading && !docxError" ref="docxContainerRef" class="docx-preview overflow-auto" />
      </div>
      <!-- Excel 预览 -->
      <div v-else-if="isExcel" class="flex-1 min-h-0">
        <div v-if="excelLoading" class="text-sm text-muted py-8">加载中...</div>
        <div v-else-if="excelError" class="text-sm text-red-500 py-4">{{ excelError }}</div>
        <div v-show="!excelLoading && !excelError" class="excel-preview overflow-auto" v-html="excelHtml" />
      </div>
      <!-- 文本可编辑 -->
      <template v-else-if="isEditableText">
        <div v-if="editingContent" class="flex-1 flex flex-col min-h-0">
          <textarea
            ref="contentTextareaRef"
            v-model="editContent"
            class="flex-1 w-full p-3 text-sm font-sans border border-input-border bg-input-bg text-primary rounded resize-none focus:outline-none focus:ring-2 focus:ring-input-focus-ring"
            spellcheck="false"
          />
          <div class="mt-2 flex justify-end gap-2 px-4 py-3 flex-shrink-0">
            <button
              class="px-4 py-2 bg-accent text-text-inverse rounded-lg hover:bg-accent-hover"
              @click="saveContent"
            >
              保存
            </button>
            <button
              class="px-4 py-2 border border-input-border rounded-lg hover:bg-list-hover"
              @click="cancelEditContent"
            >
              取消
            </button>
          </div>
        </div>
        <div v-else class="flex flex-col gap-2">
          <!-- .md 默认渲染为 Markdown，可切换为源文件 -->
          <div v-if="isMarkdown && !showMdSource" class="file-detail-article-layout">
            <nav v-if="tocItems.length" class="file-detail-toc" aria-label="文章目录">
              <div class="file-detail-toc-title">目录</div>
              <button
                v-for="it in tocItems"
                :key="it.id"
                type="button"
                class="file-detail-toc-item"
                :class="it.id === activeTocId ? 'file-detail-toc-item-active' : ''"
                @click="jumpToHeading(it.id)"
                :title="it.text"
              >
                {{ it.text }}
              </button>
            </nav>

            <div
              ref="markdownContainerRef"
              class="prose prose-sm max-w-none text-primary file-detail-markdown"
              v-html="renderMarkdown(previewText ?? '')"
            />
          </div>
          <pre v-else class="text-sm text-primary whitespace-pre-wrap break-words font-sans">{{ previewText ?? '' }}</pre>
          <div class="flex flex-wrap items-center gap-2 mt-1">
            <button
              v-if="isMarkdown"
              class="px-3 py-1.5 text-sm border border-input-border rounded-lg hover:bg-list-hover"
              @click="showMdSource = !showMdSource"
            >
              {{ showMdSource ? '显示渲染' : '显示源文件' }}
            </button>
            <button
              class="px-3 py-1.5 text-sm border border-input-border rounded-lg hover:bg-list-hover"
              @click="startEditContent"
            >
              编辑内容
            </button>
          </div>
        </div>
      </template>
      <div v-else class="text-sm text-muted">不支持预览或编辑，请下载查看</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick, onBeforeUnmount } from 'vue'
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

function slugifyHeading(text: string): string {
  const s = (text || '').trim().replace(/\s+/g, '-').replace(/[^\w\u4e00-\u9fff\-]/g, '')
  return s || 'section'
}

// 给 heading_open 自动加 id（用于目录跳转 + 滚动高亮）
md.renderer.rules.heading_open = (tokens, idx, options, env, self) => {
  const token = tokens[idx]
  const inline = tokens[idx + 1]
  const rawText = inline && inline.type === 'inline' ? inline.content : ''
  const base = slugifyHeading(rawText)
  const e = (env || {}) as { counts?: Record<string, number> }
  if (!e.counts) e.counts = {}
  const cur = e.counts[base] ?? 0
  e.counts[base] = cur + 1
  const id = cur === 0 ? base : `${base}-${cur + 1}`

  // markdown-it token 的 attrs 支持 attrSet；若环境不支持则跳过
  if ((token as any).attrSet) (token as any).attrSet('id', id)
  return self.renderToken(tokens, idx, options)
}
function renderMarkdown(text: string): string {
  if (!text) return ''
  try {
    // 每次渲染都用自己的 env，保证同一份 markdown 内 id 可控且唯一
    const env: any = {}
    return md.render(text, env)
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
const markdownContainerRef = ref<HTMLElement | null>(null)
const scrollContainerRef = ref<HTMLElement | null>(null)

type TocItem = { id: string; text: string }
const tocItems = ref<TocItem[]>([])
const activeTocId = ref<string>('')
let tocScrollRaf = 0
let headingsForSpy: HTMLElement[] = []

function getHeadingText(el: HTMLElement): string {
  const t = (el.textContent || '').trim()
  // markdown-it 可能会把 “## 用户” 渲染成带空白/换行的文本，这里做个小清洗
  return t.replace(/\s+/g, ' ')
}

function buildTocFromDom() {
  const root = markdownContainerRef.value
  if (!root) return
  const headings = Array.from(root.querySelectorAll<HTMLElement>('h1[id], h2[id], h3[id]'))

  // “专家回答段落”在导出 markdown 里通常是 h2，且用户/主持人是固定标题
  const filtered = headings.filter((h) => {
    const text = getHeadingText(h)
    if (!text) return false
    if (h.tagName.toLowerCase() !== 'h2') return false
    if (text === '用户') return false
    if (text === '主持人') return false
    return true
  })

  tocItems.value = filtered.map((h) => ({
    id: h.id,
    text: getHeadingText(h),
  }))

  headingsForSpy = filtered
  activeTocId.value = tocItems.value[0]?.id ?? ''
}

function jumpToHeading(id: string) {
  const el = document.getElementById(id)
  if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

function startScrollSpy() {
  const sc = scrollContainerRef.value
  if (!sc) return
  const spyOffset = 90 // 离顶部多远时认为是“当前章节”

  const onScroll = () => {
    if (tocScrollRaf) cancelAnimationFrame(tocScrollRaf)
    tocScrollRaf = requestAnimationFrame(() => {
      const scRect = sc.getBoundingClientRect()
      let best: HTMLElement | null = null
      for (const h of headingsForSpy) {
        const r = h.getBoundingClientRect()
        const relTop = r.top - scRect.top
        // 选择最后一个“已经进入视野顶部”的标题
        if (relTop <= spyOffset) {
          best = h
        } else {
          break
        }
      }
      activeTocId.value = best?.id ?? tocItems.value[0]?.id ?? ''
    })
  }

  sc.addEventListener('scroll', onScroll, { passive: true })
  // 返回清理函数
  return () => {
    sc.removeEventListener('scroll', onScroll)
  }
}

let stopScrollSpy: (() => void) | null = null
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
    excelHtml.value = html || '<p class="text-muted">空表格</p>'
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

watch([previewText, showMdSource, isMarkdown], async () => {
  // 只在渲染 markdown 视图时构建 TOC 与高亮
  if (!isMarkdown.value || showMdSource.value) {
    tocItems.value = []
    headingsForSpy = []
    activeTocId.value = ''
    stopScrollSpy?.()
    stopScrollSpy = null
    return
  }

  await nextTick()
  buildTocFromDom()
  stopScrollSpy?.()
  stopScrollSpy = startScrollSpy() ?? null
})

onBeforeUnmount(() => {
  stopScrollSpy?.()
  stopScrollSpy = null
  if (tocScrollRaf) cancelAnimationFrame(tocScrollRaf)
})
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
  border: 1px solid var(--color-border-light);
  padding: 0.25rem 0.5rem;
}
.excel-preview :deep(th) {
  background: var(--color-list-hover);
  font-weight: 600;
}
.file-detail-markdown :deep(h1) { font-size: 1.5rem; font-weight: 700; margin-top: 0.5rem; margin-bottom: 0.5rem; }
.file-detail-markdown :deep(h2) { font-size: 1.25rem; font-weight: 600; margin-top: 0.75rem; margin-bottom: 0.25rem; }
.file-detail-markdown :deep(h3) { font-size: 1.125rem; font-weight: 600; margin-top: 0.5rem; }
.file-detail-markdown :deep(p) { margin-bottom: 0.5rem; }
.file-detail-markdown :deep(ul) { list-style-type: disc; margin-left: 1.5rem; margin-bottom: 0.5rem; }
.file-detail-markdown :deep(ol) { list-style-type: decimal; margin-left: 1.5rem; margin-bottom: 0.5rem; }
.file-detail-markdown :deep(pre) { background: var(--color-list-hover); padding: 0.5rem 0.75rem; border-radius: 0.25rem; overflow-x: auto; margin: 0.5rem 0; }
.file-detail-markdown :deep(code) { background: var(--color-list-hover); padding: 0.125rem 0.25rem; border-radius: 0.125rem; font-size: 0.875em; }
.file-detail-markdown :deep(a) { color: var(--color-accent); text-decoration: underline; }

.file-detail-article-layout {
  display: flex;
  align-items: flex-start;
  gap: 16px;
  min-width: 0;
}

.file-detail-toc {
  position: sticky;
  top: 12px;
  /* 固定宽度，避免不同文件标题长短导致 flex 收缩/重排 */
  width: 220px;
  min-width: 220px;
  max-width: 220px;
  flex: 0 0 220px;
  flex-shrink: 0;
  max-height: calc(100vh - 96px);
  overflow: auto;
  padding: 10px 10px;
  border-radius: 14px;
  background: rgba(17, 24, 39, 0.55);
  backdrop-filter: blur(10px);
  color: rgba(255, 255, 255, 0.72);
  border: 1px solid rgba(255, 255, 255, 0.12);
}

.file-detail-toc-title {
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.02em;
  margin-bottom: 8px;
  color: rgba(255, 255, 255, 0.85);
}

.file-detail-toc-item {
  display: block;
  width: 100%;
  text-align: left;
  padding: 7px 8px;
  border-radius: 10px;
  font-size: 12px;
  line-height: 1.25;
  color: rgba(255, 255, 255, 0.72);
  border: none;
  background: transparent;
  cursor: pointer;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  transition: background 0.15s, color 0.15s;
}

.file-detail-toc-item:hover {
  background: rgba(255, 255, 255, 0.08);
  color: rgba(255, 255, 255, 0.92);
}

.file-detail-toc-item-active {
  background: rgba(37, 99, 235, 0.22);
  border: 1px solid rgba(37, 99, 235, 0.45);
  color: rgba(255, 255, 255, 0.95);
}
</style>
