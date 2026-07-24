import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Proxy /api (and /healthz) to the FastAPI server in dev, so the browser talks to
// its own origin and the SameSite=Lax session cookie is sent same-origin. Prod
// serves the SPA and /api from one host, so no proxy is needed there.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    proxy: {
      '/api': { target: 'http://localhost:8000', changeOrigin: true },
      '/healthz': { target: 'http://localhost:8000', changeOrigin: true },
    },
  },
});
