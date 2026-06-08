import { onUnmounted, type Ref } from 'vue'
import { sanitizeWorkspaceDownloadUrl } from '../workspaceMessageUtils'

export function useAuthenticatedMessageImages(groupMessagesRef: Ref<HTMLElement | null>) {
  let authImageHydrateRaf = 0
  const authImageObjectUrls: string[] = []

  function scheduleHydrateAuthImages() {
    if (authImageHydrateRaf) return
    authImageHydrateRaf = window.requestAnimationFrame(async () => {
      authImageHydrateRaf = 0
      await hydrateAuthImages()
    })
  }

  async function hydrateAuthImages() {
    const container = groupMessagesRef.value
    if (!container) return

    const imgs = Array.from(container.querySelectorAll<HTMLImageElement>('img[data-agent-auth-src]'))
    for (const img of imgs) {
      if (img.dataset.agentHydrated === '1') continue
      const rawSrc = sanitizeWorkspaceDownloadUrl(img.getAttribute('data-agent-auth-src') || '')
      if (!rawSrc) continue

      img.dataset.agentHydrated = '1'
      try {
        const r = await fetch(rawSrc)
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        const blob = await r.blob()
        const objUrl = URL.createObjectURL(blob)
        authImageObjectUrls.push(objUrl)
        img.src = objUrl
      } catch {
        img.alt = `${img.alt || '图片'}（加载失败）`
      }
    }
  }

  onUnmounted(() => {
    if (authImageHydrateRaf) {
      window.cancelAnimationFrame(authImageHydrateRaf)
      authImageHydrateRaf = 0
    }
    for (const url of authImageObjectUrls) {
      try {
        URL.revokeObjectURL(url)
      } catch {
        // ignore revoke failures
      }
    }
    authImageObjectUrls.length = 0
  })

  return {
    scheduleHydrateAuthImages,
  }
}
