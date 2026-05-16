import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    hmr: false,
    proxy: {
      '/ws': { target: 'ws://127.0.0.1:8000', ws: true },
      '/alerts': 'http://127.0.0.1:8000',
      '/signals': 'http://127.0.0.1:8000',
      '/backtest': 'http://127.0.0.1:8000',
      '/paper-trades': 'http://127.0.0.1:8000',
      '/journal': 'http://127.0.0.1:8000',
      '/health': 'http://127.0.0.1:8000',
      '/debug': 'http://127.0.0.1:8000',
      '/options': 'http://127.0.0.1:8000',
      '/sentiment': 'http://127.0.0.1:8000',
      '/snapshot': 'http://127.0.0.1:8000',
      '/ai-ict': 'http://127.0.0.1:8000',
      '/news': 'http://127.0.0.1:8000',
      '/scanner': 'http://127.0.0.1:8000',
      '/risk': 'http://127.0.0.1:8000',
    },
  },
})
