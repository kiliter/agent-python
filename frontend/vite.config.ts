// #Created By AiCoding(codex) Vite 构建与开发服务器配置（代理 Python 后端 /api 接口）
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url))
    }
  },
  server: {
    port: 5175,
    // 端口被占用时直接报错，不自动换到其它端口
    strictPort: true,
    host: '0.0.0.0',
    proxy: {
      '/api': {
        target: process.env.VITE_BACKEND_PROXY || 'http://127.0.0.1:8000',
        changeOrigin: true
      }
    }
  },
  build: {
    chunkSizeWarningLimit: 900,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('node_modules')) {
            if (id.includes('element-plus') || id.includes('@element-plus')) {
              return 'element-plus'
            }
            if (id.includes('@codemirror') || id.includes('@lezer') || id.includes('codemirror')) {
              return 'codemirror'
            }
            if (id.includes('lucide-vue-next')) {
              return 'icons'
            }
            return 'vendor'
          }
        }
      }
    }
  }
})
