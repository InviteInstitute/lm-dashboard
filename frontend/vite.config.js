import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Proxy /api (and /healthz) to the FastAPI server in dev, so the browser talks to
// its own origin and the SameSite=Lax session cookie is sent same-origin. Prod
// serves the SPA and /api from one host, so no proxy is needed there.
// VITE_PROXY_TARGET lets the dev container reach the api service on the compose
// network (http://api:8000); it defaults to localhost for a plain `npm run dev`.
const proxyTarget = process.env.VITE_PROXY_TARGET || 'http://localhost:8000';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    proxy: {
      '/api': { target: proxyTarget, changeOrigin: true },
      '/healthz': { target: proxyTarget, changeOrigin: true },
    },
  },
});
