// #Created By AiCoding(codex) Vite 构建与开发服务器配置（代理 Python 后端 /api 接口 + 多入口精细拆包）
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5175,
    // 端口被占用时直接报错，不自动换到其它端口
    strictPort: true,
    host: '0.0.0.0',
    proxy: {
      '/api': {
        target: process.env.VITE_BACKEND_PROXY || 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    chunkSizeWarningLimit: 900,
    rollupOptions: {
      // 多页面入口：管理端 index.html + 嵌入式聊天窗口 embed.html（后者不加载管理端重型依赖）
      input: {
        index: fileURLToPath(new URL('./index.html', import.meta.url)),
        embed: fileURLToPath(new URL('./embed.html', import.meta.url)),
      },
      output: {
        manualChunks(id) {
          if (!id.includes('node_modules')) return undefined
          if (/node_modules\/(@vue|vue)\//.test(id)) {
            return 'vue-core'
          }
          if (/node_modules\/(pinia|vue-router)\//.test(id)) {
            return 'vue-state'
          }
          if (/node_modules\/marked\//.test(id)) {
            return 'markdown-lib'
          }
          if (/node_modules\/lucide-vue-next\//.test(id)) {
            return 'icons'
          }
          if (/node_modules\/(element-plus|@element-plus)\//.test(id)) {
            return 'element-plus'
          }
          if (
            /node_modules\/(@popperjs|@floating-ui|lodash-es|dayjs|async-validator|@ctrl\/tinycolor|normalize-wheel-es|escape-html|memoize-one)\//.test(
              id,
            )
          ) {
            return 'element-deps'
          }
          if (
            /node_modules\/(@codemirror|@lezer|codemirror|crelt|style-mod|w3c-keyname)\//.test(id)
          ) {
            return 'codemirror'
          }
          if (/node_modules\/(yaml|diff)\//.test(id)) {
            return 'workbench-libs'
          }
          return undefined
        },
      },
    },
  },
})
