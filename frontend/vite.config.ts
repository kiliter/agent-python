// #Created By AiCoding(codex) Vite 构建与开发服务器配置（代理 Python 后端 /api 接口 + 多入口精细拆包 + embed 体积守卫）
import { defineConfig, type Plugin } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

const FORBIDDEN_EMBED_CHUNKS = [
  'element-plus',
  'element-deps',
  'codemirror',
  'workbench-libs',
  'vue-state',
] as const

const FORBIDDEN_EMBED_ASSET_RE = new RegExp(
  `(?:^|[/"'])(${FORBIDDEN_EMBED_CHUNKS.join('|')})(?:-[A-Za-z0-9_-]+)?\\.(?:js|mjs|css)(?=$|[?"'\\s>])`,
)

/**
 * 构建期守卫：检查 embed.html 产物源码及其直接/传递静态导入链，
 * 严禁嵌入式聊天窗口意外混入管理工作台重型依赖包。
 */
function embedBundleGuard(): Plugin {
  const forbiddenSet = new Set<string>(FORBIDDEN_EMBED_CHUNKS)
  return {
    name: 'embed-bundle-guard',
    generateBundle(_options, bundle) {
      const embedHtmlAsset = bundle['embed.html']
      if (embedHtmlAsset && embedHtmlAsset.type === 'asset') {
        const htmlSource =
          typeof embedHtmlAsset.source === 'string'
            ? embedHtmlAsset.source
            : Buffer.from(embedHtmlAsset.source).toString('utf-8')
        const htmlMatch = htmlSource.match(FORBIDDEN_EMBED_ASSET_RE)
        if (htmlMatch) {
          this.error(
            `[embedBundleGuard] embed.html 产物包含被禁止的管理端重型 chunk 引用 "${htmlMatch[1]}"，请检查共享模块导入边界！`,
          )
        }
      }

      const entryChunks = Object.values(bundle).filter(
        (item): item is Extract<(typeof bundle)[string], { type: 'chunk' }> =>
          item.type === 'chunk' &&
          item.isEntry &&
          (item.name === 'embed' ||
            Boolean(item.facadeModuleId && item.facadeModuleId.replace(/\\/g, '/').endsWith('/embed.html'))),
      )

      const visited = new Set<string>()
      const queue = entryChunks.map(c => c.fileName)
      while (queue.length > 0) {
        const fileName = queue.shift()!
        if (visited.has(fileName)) continue
        visited.add(fileName)

        const chunk = bundle[fileName]
        if (!chunk || chunk.type !== 'chunk') continue

        if (forbiddenSet.has(chunk.name) || FORBIDDEN_EMBED_ASSET_RE.test(chunk.fileName)) {
          this.error(
            `[embedBundleGuard] embed 静态导入链混入了被禁止的 chunk "${chunk.name}" (${chunk.fileName})！`,
          )
        }

        const metaCss = (chunk as { viteMetadata?: { importedCss?: Set<string> } }).viteMetadata?.importedCss
        if (metaCss) {
          for (const cssFile of metaCss) {
            if (FORBIDDEN_EMBED_ASSET_RE.test(cssFile)) {
              this.error(`[embedBundleGuard] embed 静态导入链混入了被禁止的样式产物 "${cssFile}"！`)
            }
          }
        }

        for (const imported of chunk.imports) {
          if (!visited.has(imported)) {
            queue.push(imported)
          }
        }
      }
    },
  }
}

export default defineConfig({
  // 默认使用相对路径，使同一份构建产物可直接部署在根路径 / 或任意 Nginx 反代子路径（如 /agent/）下
  base: process.env.VITE_BASE_PATH || './',
  plugins: [vue(), embedBundleGuard()],
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
