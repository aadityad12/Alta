import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

const SERVER = 'http://localhost:8000'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/ws': { target: SERVER, ws: true },
      '/labs': SERVER,
      '/health': SERVER,
    },
  },
})
