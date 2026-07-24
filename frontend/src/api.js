// Shared axios instance for every call to the read API. Import this rather than
// hitting the server directly so the base URL, credentials, and headers stay in
// one place.
import axios from 'axios';

// Same-origin by default. In dev the base is relative and Vite proxies /api to
// :8000 (see vite.config.js), so the SameSite=Lax session cookie stays
// same-origin; the prod build also sets VITE_API_URL='' and FastAPI serves both
// the SPA and /api on one host. `??` not `||` so an empty string is honored as
// "relative" rather than falling back to a hardcoded host.
export const API_URL = import.meta.env.VITE_API_URL ?? '';

const api = axios.create({
  baseURL: API_URL,
  // withCredentials: send the researcher's signed session cookie on every request
  // (that's what carries the login + the per-browser board binding).
  withCredentials: true,
  // 'ngrok-skip-browser-warning' tells ngrok's free tier to skip its interstitial
  // HTML page for these calls (otherwise the API would get that page instead of
  // JSON). Any custom header triggers the skip; it's harmless off ngrok.
  headers: { 'Content-Type': 'application/json', 'ngrok-skip-browser-warning': 'true' },
});

// A stable per-browser id, persisted in localStorage. It decides which isolated
// board this browser lands on: it's sent with the login request and the server
// maps it to a workspace (a fresh browser gets a fresh board). Everyone can share
// one login yet each browser stays isolated.
export function boardId() {
  let id = localStorage.getItem('lm_board_id');
  if (!id) {
    id = window.crypto?.randomUUID?.()
      || `${Date.now()}-${Math.random().toString(36).slice(2)}`;
    localStorage.setItem('lm_board_id', id);
  }
  return id;
}

// Let the app react to a dropped/expired session: any 401 outside the login and
// session-probe endpoints bounces back to the login screen instead of surfacing
// as a render error.
let onUnauthorized = null;
export function setOnUnauthorized(cb) { onUnauthorized = cb; }
api.interceptors.response.use(
  (r) => r,
  (err) => {
    const url = err.config?.url || '';
    if (err.response?.status === 401
        && !url.includes('/api/login') && !url.includes('/api/me')) {
      onUnauthorized?.();
    }
    return Promise.reject(err);
  },
);

export default api;
