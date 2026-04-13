import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const apiPort = env.VITE_API_PORT ?? '8000'
  const apiBase = `http://localhost:${apiPort}`
  const wsBase  = `ws://localhost:${apiPort}`

  return {
    plugins: [react(), tailwindcss()],
    resolve: {
      alias: {
        '@': path.resolve(__dirname, './src'),
      },
    },
    server: {
      proxy: {
        '/api': {
          target: apiBase,
          changeOrigin: true,
        },
        '/ws': {
          target: wsBase,
          ws: true,
          changeOrigin: true,
        },
      },
    },
  }
})
