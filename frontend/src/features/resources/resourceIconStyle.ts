import type { CSSProperties } from 'vue'

export function resourceIconStyle(iconUrl: string): CSSProperties {
  return {
    '--resource-icon-url': `url("${iconUrl}")`,
  } as CSSProperties
}
