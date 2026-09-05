import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { copyFileSync, existsSync } from 'node:fs'
import { resolve } from 'node:path'

// The app is served by FastAPI at /app, not from the root, so every asset URL
// has to carry that prefix -- a default base of '/' builds a bundle whose
// script tags 404 the moment it is mounted anywhere but the root.
//
// In development Vite serves the app itself and proxies /api to uvicorn. That
// keeps the browser on ONE origin in both modes, so the CORS configuration in
// api/main.py is exercised the same way in dev as in production, instead of
// being a rule that only ever runs in one of them.
export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    {
      /* GITHUB PAGES HAS NO REWRITE RULES.
       *
       * Cloudflare and Vercel are told to serve index.html for unknown paths;
       * Pages cannot be told anything. What it does have is a 404 page, and it
       * serves that with the URL intact -- so a byte-identical copy of
       * index.html at 404.html boots the same app, the router reads the path
       * off the URL, and a deep link works. It is a hack, and it is the
       * documented one. */
      name: 'spa-404',
      closeBundle() {
        const index = resolve(__dirname, 'dist', 'index.html')
        if (existsSync(index)) {
          copyFileSync(index, resolve(__dirname, 'dist', '404.html'))
        }
      },
    },
  ],
  /* WHERE THE BUNDLE WILL BE SERVED FROM.
   *
   * Served by FastAPI it is mounted at /app/. On a static host it depends
   * entirely on the host: Cloudflare Pages and Vercel serve from the root,
   * GitHub Pages serves a project site from /<repo>/. A bundle built with the
   * wrong base has asset URLs that 404 with no clue why, so it is an input
   * rather than a constant. */
  base: process.env.VITE_BASE ?? '/app/',
  server: {
    port: 5173,
    proxy: { '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true } },
  },
  resolve: { alias: { '@': resolve(__dirname, 'src') } },
  build: { outDir: 'dist', sourcemap: true },
})
