import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    hmr: false,
    proxy: {
      '/ws': { target: 'ws://127.0.0.1:8080', ws: true },
      '/mtf-confluence': 'http://127.0.0.1:8080',
      '/alerts': 'http://127.0.0.1:8080',
      '/signals': 'http://127.0.0.1:8080',
      '/backtest': 'http://127.0.0.1:8080',
      '/paper-trades': 'http://127.0.0.1:8080',
      '/journal': 'http://127.0.0.1:8080',
      '/health': 'http://127.0.0.1:8080',
      '/debug': 'http://127.0.0.1:8080',
      '/options': 'http://127.0.0.1:8080',
      '/sentiment': 'http://127.0.0.1:8080',
      '/snapshot': 'http://127.0.0.1:8080',
      '/ai-ict': 'http://127.0.0.1:8080',
    },
  },
})
