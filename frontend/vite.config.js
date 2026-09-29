import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: { proxy: { '/api': 'http://127.0.0.1:8000' } },
  // lazily loaded chunks: alphaTab ~1.2 MB, Verovio (WebAssembly inlined) ~8 MB
  build: { chunkSizeWarningLimit: 9000 },
  test: { environment: 'node' },
})
