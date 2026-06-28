import type { CSSProperties } from 'vue'

export function workspaceIconStyle(iconUrl: string): CSSProperties {
  return {
    '--workspace-icon-url': `url("${iconUrl}")`,
  } as CSSProperties
}
