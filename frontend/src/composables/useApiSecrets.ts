import { ref, type Ref } from 'vue'

export type ApiSecretItem = { id: string; label: string; key_set: boolean }

export function useApiSecrets() {
  const secretItems: Ref<ApiSecretItem[]> = ref([])

  async function loadApiSecrets() {
    try {
      const r = await fetch('/api/settings/api-secrets')
      const j = await r.json()
      if (j?.status === 'ok' && j?.data?.items) {
        secretItems.value = j.data.items
      } else {
        secretItems.value = []
      }
    } catch {
      secretItems.value = []
    }
  }

  /** 解析 transport.headers 中形如 prefix${vault:id} 的项 */
  function parseVaultHeader(headers?: Record<string, string>): {
    headerName: string
    prefix: string
    vaultRef: string
  } {
    if (!headers || typeof headers !== 'object') {
      return { headerName: 'Authorization', prefix: 'Bearer ', vaultRef: '' }
    }
    for (const [hn, val] of Object.entries(headers)) {
      const m = /^([\s\S]*?)\$\{vault:([^}]+)\}\s*$/.exec(val)
      if (m) {
        return { headerName: hn, prefix: m[1], vaultRef: m[2] }
      }
    }
    return { headerName: 'Authorization', prefix: 'Bearer ', vaultRef: '' }
  }

  return { secretItems, loadApiSecrets, parseVaultHeader }
}
