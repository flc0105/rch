import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { readdir, readFile, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { join, extname } from 'node:path'
import { gzipSync } from 'node:zlib'

// Precompress Vite's hashed assets once at build time. Flask serves these files
// without compressing API responses, SSE streams, WebSockets or downloads.
function gzipStaticAssets() {
  return {
    name: 'gzip-static-assets',
    apply: 'build',
    async closeBundle() {
      const assetsDir = fileURLToPath(new URL('./dist/assets/', import.meta.url))
      let files
      try { files = await readdir(assetsDir) } catch { return }
      for (const filename of files) {
        if (!['.js', '.css'].includes(extname(filename))) continue
        const source = await readFile(join(assetsDir, filename))
        if (source.length < 1024) continue
        const compressed = gzipSync(source, { level: 6 })
        if (compressed.length < source.length) {
          await writeFile(join(assetsDir, `${filename}.gz`), compressed)
        }
      }
    },
  }
}

export default defineConfig({
  plugins: [
    vue(),
    gzipStaticAssets(),
  ],

  resolve: {
    alias: {
      vue: 'vue/dist/vue.esm-bundler.js',
    },
  },

  server: {
    port: 5173,
    host: '0.0.0.0',
    strictPort: true,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8085',
        changeOrigin: true,
        ws: true,
      },

      '/ws': {
        target: 'ws://127.0.0.1:8085',
        changeOrigin: true,
        ws: true,
      },
    },
  },
})