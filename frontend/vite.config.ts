import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'path'

const disableApiProxy = process.env.VITE_DISABLE_API_PROXY === '1'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src')
    }
  },
  server: {
    port: 5173,
    proxy: disableApiProxy ? undefined : {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        timeout: 180000,
        proxyTimeout: 180000
      }
    }
  }
})
