import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  let base = env.VITE_BASE || '/'
  if (!base.startsWith('/')) base = `/${base}`
  if (base.length > 1 && !base.endsWith('/')) base = `${base}/`

  return {
    base,
    plugins: [react()],
    server: {
      host: env.VITE_DEV_HOST || '127.0.0.1',
      port: Number(env.VITE_DEV_PORT || 5173),
      proxy: {
        '/api': {
          target: env.VITE_API_PROXY || 'http://127.0.0.1:8000',
          changeOrigin: true,
          cookieDomainRewrite: '127.0.0.1',
        },
      },
    },
    preview: {
      host: env.VITE_DEV_HOST || '127.0.0.1',
      port: Number(env.VITE_PREVIEW_PORT || 4173),
      proxy: {
        '/api': {
          target: env.VITE_API_PROXY || 'http://127.0.0.1:8000',
          changeOrigin: true,
          cookieDomainRewrite: '127.0.0.1',
        },
      },
    },
  }
})
