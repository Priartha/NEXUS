import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/ws': { target: 'ws://localhost:8000', ws: true },
      '/volume-profile': 'http://localhost:8000',
      '/mtf-confluence': 'http://localhost:8000',
      '/alerts': 'http://localhost:8000',
      '/signals': 'http://localhost:8000',
      '/backtest': 'http://localhost:8000',
      '/paper-trades': 'http://localhost:8000',
      '/journal': 'http://localhost:8000',
      '/health': 'http://localhost:8000',
      '/debug': 'http://localhost:8000',
      '/options': 'http://localhost:8000',
      '/sentiment': 'http://localhost:8000',
      '/snapshot': 'http://localhost:8000',
      '/ai-ict': 'http://localhost:8000',
    },
  },
})
