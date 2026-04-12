/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** 对外展示推广链接等使用的站点根地址（无尾部斜杠），如 http://10.129.236.188:8100 */
  readonly VITE_PUBLIC_APP_ORIGIN?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}

