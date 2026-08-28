import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The app is served by FastAPI at /app, not from the root, so every asset URL
// has to carry that prefix -- a default base of '/' builds a bundle whose
// script tags 404 the moment it is mounted anywhere but the root.
//
// In development Vite serves the app itself and proxies /api to uvicorn. That
// keeps the browser on ONE origin in both modes, so the CORS configuration in
// api/main.py is exercised the same way in dev as in production, instead of
// being a rule that only ever runs in one of them.
export default defineConfig({
  plugins: [react()],
  base: '/app/',
  server: {
    port: 5173,
    proxy: { '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true } },
  },
  build: { outDir: 'dist', sourcemap: true },
})
