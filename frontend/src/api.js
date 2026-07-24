// Shared axios instance for every call to the read API. Import this rather than
// hitting the server directly so the base URL and headers stay in one place.
import axios from 'axios';

// Same-origin by default. In dev the base is relative and Vite proxies /api to
// :8000 (see vite.config.js); the prod build sets VITE_API_URL='' and FastAPI
// serves both the SPA and /api on one host (behind nginx). `??` not `||` so an
// empty string is honored as "relative" rather than falling back to a host.
export const API_URL = import.meta.env.VITE_API_URL ?? '';

// A stable per-browser id, persisted in localStorage. It decides which isolated
// board this browser lands on: it's sent on every request (X-Board-Id header, and
// as ?board_id= on the SSE stream, which can't carry headers), and the server maps
// it to a workspace. A fresh browser gets a fresh board. Auth itself is the
// browser's native HTTP Basic dialog, handled by the browser, not this code.
export function boardId() {
  let id = localStorage.getItem('lm_board_id');
  if (!id) {
    id = window.crypto?.randomUUID?.()
      || `${Date.now()}-${Math.random().toString(36).slice(2)}`;
    localStorage.setItem('lm_board_id', id);
  }
  return id;
}

const api = axios.create({
  baseURL: API_URL,
  // withCredentials keeps the browser's cached Basic-Auth header on same-origin
  // XHR (and cross-origin in dev via the proxy).
  withCredentials: true,
  headers: {
    'Content-Type': 'application/json',
    'ngrok-skip-browser-warning': 'true',
    'X-Board-Id': boardId(),          // per-browser board isolation
  },
});

export default api;
