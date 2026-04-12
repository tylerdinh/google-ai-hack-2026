import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The Python FastAPI backend runs on port 8000.
// All API and SSE paths are proxied there during development.
const BACKEND = 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/research':  { target: BACKEND, changeOrigin: true },
      '/api':       { target: BACKEND, changeOrigin: true },
      '/stocks':    { target: BACKEND, changeOrigin: true },
      '/analyses':  { target: BACKEND, changeOrigin: true },
      '/auth':      { target: BACKEND, changeOrigin: true },
      '/audio':     { target: BACKEND, changeOrigin: true },
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
})
