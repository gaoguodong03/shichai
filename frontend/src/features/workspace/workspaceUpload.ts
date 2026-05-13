export type WorkspaceUploadProgress = {
  loaded: number
  total: number | null
  percent: number | null
}

export type WorkspaceUploadResponse = {
  status?: string
  detail?: string
  data?: {
    path?: string
    [key: string]: unknown
  }
  [key: string]: unknown
}

const TOKEN_STORAGE_KEY = 'dha_token'

export function uploadWorkspaceFile(
  workspaceId: string,
  file: File,
  dirPath = '',
  onProgress?: (progress: WorkspaceUploadProgress) => void,
): Promise<WorkspaceUploadResponse> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    const query = dirPath ? `?path=${encodeURIComponent(dirPath)}` : ''
    xhr.open('POST', `/api/workspaces/${encodeURIComponent(workspaceId)}/files/upload${query}`)
    const token = localStorage.getItem(TOKEN_STORAGE_KEY)
    if (token) xhr.setRequestHeader('Authorization', `Bearer ${token}`)

    xhr.upload.onprogress = (event) => {
      const total = event.lengthComputable ? event.total : null
      onProgress?.({
        loaded: event.loaded,
        total,
        percent: total ? Math.min(100, Math.max(0, Math.round((event.loaded / total) * 100))) : null,
      })
    }

    xhr.onload = () => {
      let payload: WorkspaceUploadResponse = {}
      try {
        payload = xhr.responseText ? JSON.parse(xhr.responseText) : {}
      } catch {
        payload = { detail: xhr.responseText || '上传失败' }
      }
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(payload)
        return
      }
      reject(new Error(payload.detail || `上传失败 (${xhr.status})`))
    }

    xhr.onerror = () => reject(new Error('上传失败，请检查网络或后端'))
    xhr.onabort = () => reject(new Error('上传已取消'))

    const form = new FormData()
    form.append('file', file)
    xhr.send(form)
  })
}
