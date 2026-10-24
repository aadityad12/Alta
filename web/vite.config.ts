import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

const SERVER = 'http://localhost:8000'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    fs: { allow: ['..'] }, // /dev/board reads docs/samples and labs/ from the repo root
    proxy: {
      '/ws': { target: SERVER, ws: true },
      '/labs': SERVER,
      '/health': SERVER,
    },
  },
})
