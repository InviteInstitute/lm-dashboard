// The one client for every call to the read API. Import this rather than
// hitting the server directly so the base URL and headers stay in one place.

// Same-origin by default. In dev the base is relative and Vite proxies /api to
// :8000 (see vite.config.js); the prod build sets VITE_API_URL='' and FastAPI
// serves both the SPA and /api on one host (behind nginx). `??` not `||` so an
// empty string is honored as "relative" rather than falling back to a host.
export const API_URL = import.meta.env.VITE_API_URL ?? "";

// A stable per-browser id, persisted in localStorage. It decides which isolated
// board this browser lands on: it's sent on every request (X-Board-Id header, and
// as ?board_id= on the SSE stream, which can't carry headers), and the server maps
// it to a workspace. A fresh browser gets a fresh board. The API itself is gated
// by Cloudflare Turnstile rather than a login -- see TurnstileGate.jsx.
export function boardId() {
  let id = localStorage.getItem("lm_board_id");
  if (!id) {
    id = window.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`;
    localStorage.setItem("lm_board_id", id);
  }
  return id;
}

// fetch with the shape callers rely on: resolves to { data, status }, rejects
// on a non-2xx with err.response = { status, data }. `params` becomes the query
// string; `responseType: "blob"` returns the body as a Blob (the export zip).
async function request(method, url, body, { params, responseType } = {}) {
  const qs = params ? `?${new URLSearchParams(params)}` : "";
  const res = await fetch(`${API_URL}${url}${qs}`, {
    method,
    // sends the ts_verified cookie the Turnstile gate sets
    credentials: "include",
    headers: { "Content-Type": "application/json", "X-Board-Id": boardId() },
    body: body == null ? undefined : JSON.stringify(body),
  });
  const data =
    responseType === "blob" && res.ok ? await res.blob() : await res.json().catch(() => null);
  if (!res.ok) {
    // The server's TurnstileGateMiddleware 403s any /api/* call from a browser
    // that hasn't solved the widget yet. Surface that as a DOM event so
    // TurnstileGate.jsx (mounted once, above everything else) can show the
    // challenge -- every caller gets this for free.
    if (res.status === 403 && data?.error === "turnstile_required") {
      window.dispatchEvent(new CustomEvent("turnstile:required"));
    }
    const err = new Error(`Request failed with status ${res.status}`);
    err.response = { status: res.status, data };
    throw err;
  }
  return { data, status: res.status };
}

const api = {
  get: (url, opts) => request("GET", url, null, opts),
  post: (url, body, opts) => request("POST", url, body, opts),
};

export default api;
