import { onUnmounted, ref } from 'vue'

const MIN_MIDDLE_COLUMN_WIDTH = 220
const MAX_MIDDLE_COLUMN_WIDTH = 420
const DEFAULT_MIDDLE_COLUMN_WIDTH = 240

export function useMiddleColumnLayout() {
  const middleColumnWidth = ref(DEFAULT_MIDDLE_COLUMN_WIDTH)
  const middleColumnOpen = ref(true)
  const middleColumnPrevWidth = ref(DEFAULT_MIDDLE_COLUMN_WIDTH)
  const isResizingMiddle = ref(false)

  let resizeStartX = 0
  let resizeStartWidth = DEFAULT_MIDDLE_COLUMN_WIDTH

  function toggleMiddleColumn() {
    if (middleColumnOpen.value) {
      middleColumnPrevWidth.value = middleColumnWidth.value
      middleColumnOpen.value = false
    } else {
      middleColumnOpen.value = true
      middleColumnWidth.value = middleColumnPrevWidth.value || DEFAULT_MIDDLE_COLUMN_WIDTH
    }
  }

  function ensureMiddleColumnOpen() {
    if (!middleColumnOpen.value) {
      middleColumnOpen.value = true
      middleColumnWidth.value = middleColumnPrevWidth.value || DEFAULT_MIDDLE_COLUMN_WIDTH
    }
  }

  function onMiddleResizeMouseMove(e: MouseEvent) {
    if (!isResizingMiddle.value) return
    const delta = e.clientX - resizeStartX
    middleColumnWidth.value = Math.min(
      MAX_MIDDLE_COLUMN_WIDTH,
      Math.max(MIN_MIDDLE_COLUMN_WIDTH, resizeStartWidth + delta),
    )
  }

  function onMiddleResizeMouseUp() {
    if (!isResizingMiddle.value) return
    isResizingMiddle.value = false
    window.removeEventListener('mousemove', onMiddleResizeMouseMove)
    window.removeEventListener('mouseup', onMiddleResizeMouseUp)
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

  onUnmounted(() => {
    window.removeEventListener('mousemove', onMiddleResizeMouseMove)
    window.removeEventListener('mouseup', onMiddleResizeMouseUp)
  })

  return {
    middleColumnWidth,
    middleColumnOpen,
    toggleMiddleColumn,
    ensureMiddleColumnOpen,
    onMiddleResizeMouseDown,
  }
}
