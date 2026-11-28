// Every researcher input is saved through `safeWrite`, so nothing typed or
// clicked is ever lost silently. A write is tried, retried twice with a short
// backoff, and only then fails loud: the original payload is parked in the
// server's outbox (or in this browser when the API itself is down) and a sticky
// red toast names the action. The error is rethrown, so the caller can set its
// optimistic UI back to what the server says.
import React from "react";
import api from "../api";

const RETRIES = 2;
const RETRY_MS = 250;
const LOCAL_OUTBOX = "lmdOutbox";

const readLocal = () => JSON.parse(window.localStorage.getItem(LOCAL_OUTBOX) || "[]");
function parkLocally(item) {
  try {
    window.localStorage.setItem(LOCAL_OUTBOX, JSON.stringify([...readLocal(), item]));
  } catch {
    /* storage blocked: the toast still says it wasn't saved */
  }
}

// `notify` shows the toast. `online` is true while the event stream is
// connected, the signal that the API is back: inputs parked in this browser are
// then sent on to the server's outbox.
export function useSafeWrite(notify, online) {
  const failLoud = React.useCallback(
    (op, payload, err) => {
      const error = err?.message || "request failed";
      api
        .post("/api/outbox/", { op, payload, error })
        .catch(() => parkLocally({ op, payload, error, ts: Date.now() }));
      notify("error", "Not saved", op);
    },
    [notify],
  );

  React.useEffect(() => {
    if (!online) return;
    let parked;
    try {
      parked = readLocal();
    } catch {
      return;
    }
    if (!parked.length) return;
    window.localStorage.removeItem(LOCAL_OUTBOX);
    parked.forEach((item) => api.post("/api/outbox/", item).catch(() => parkLocally(item)));
  }, [online]);

  // `op` names the action in the toast and the outbox; `body` is posted to `url`.
  return React.useCallback(
    async (op, url, body) => {
      for (let attempt = 0; ; attempt++) {
        try {
          return await api.post(url, body);
        } catch (e) {
          if (attempt >= RETRIES) {
            failLoud(op, body, e);
            throw e;
          }
          await new Promise((r) => setTimeout(r, RETRY_MS * (attempt + 1)));
        }
      }
    },
    [failLoud],
  );
}
