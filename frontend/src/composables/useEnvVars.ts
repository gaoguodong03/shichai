import { apiRequest } from '@/api/base'
import { ref, type Ref } from 'vue'

export type EnvVarItem = { name: string; label: string; value_set: boolean }

export function useEnvVars() {
  const envVarItems: Ref<EnvVarItem[]> = ref([])

  async function loadEnvVars() {
    try {
      const r = await apiRequest('/settings/env-vars')
      const j = await r.json()
      if (j?.status === 'ok' && j?.data?.items) {
        envVarItems.value = j.data.items
      } else {
        envVarItems.value = []
      }
    } catch {
      envVarItems.value = []
    }
  }

  /** 解析 transport.headers 中形如 prefix${env:NAME} 的项 */
  function parseEnvHeader(headers?: Record<string, string>): {
    headerName: string
    prefix: string
    envRef: string
  } {
    if (!headers || typeof headers !== 'object') {
      return { headerName: 'Authorization', prefix: 'Bearer ', envRef: '' }
    }
    for (const [hn, val] of Object.entries(headers)) {
      const m = /^([\s\S]*?)\$\{env:([^}]+)\}\s*$/.exec(val)
      if (m) {
        return { headerName: hn, prefix: m[1], envRef: m[2] }
      }
    }
    return { headerName: 'Authorization', prefix: 'Bearer ', envRef: '' }
  }

  return { envVarItems, loadEnvVars, parseEnvHeader }
}
