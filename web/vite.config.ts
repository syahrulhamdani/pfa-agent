import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The browser calls /api/*; the dev server forwards it to the FastAPI app, so
// no CORS setup is needed. Override the target with VITE_API_TARGET.
const apiTarget = process.env.VITE_API_TARGET ?? 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: apiTarget,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
})
