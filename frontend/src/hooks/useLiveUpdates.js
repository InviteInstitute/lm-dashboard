// How the board stays current: one Server-Sent Events stream when it can, a
// poll timer per data source when it can't, and neither while the tab is hidden.
import React from "react";
import { API_URL, boardId } from "../api";
import { POLL_MS } from "../constants";

// The channels the stream reports changes on, one per data source.
export const CHANNELS = ["states", "roster", "triggers", "switches"];

// True while this tab is on screen (Page Visibility API). Every fetch loop is
// gated on it, and since those fetches are also the daemon's "someone is
// watching" signal, a tab no one looks at lets production polling wind down.
export function usePageVisible() {
  const [visible, setVisible] = React.useState(!document.hidden);
  React.useEffect(() => {
    const onChange = () => setVisible(!document.hidden);
    document.addEventListener("visibilitychange", onChange);
    return () => document.removeEventListener("visibilitychange", onChange);
  }, []);
  return visible;
}

// Run `fn` now and every POLL_MS while `active`. Turning `active` back on
// fetches once at once, then resumes the timer.
export function usePoll(fn, active) {
  React.useEffect(() => {
    if (!active) return undefined;
    fn();
    const id = setInterval(fn, POLL_MS);
    return () => clearInterval(id);
  }, [fn, active]);
}

// While `active`, hold one stream to the API and call `onChanged(channels)`
// whenever the server says something moved (and once on connect, with every
// channel, to seed the first fetch). Returns whether the stream is connected.
// Callers poll while it isn't, so a missing EventSource (jsdom) or a dropped
// connection falls back to timers until the browser reconnects.
export function useEventStream(onChanged, active) {
  const [connected, setConnected] = React.useState(false);
  React.useEffect(() => {
    if (!active || typeof EventSource === "undefined") return undefined;
    // EventSource can't set headers, so the board id rides as a query param.
    const es = new EventSource(`${API_URL}/api/stream/?board_id=${encodeURIComponent(boardId())}`);
    es.addEventListener("hello", () => {
      setConnected(true);
      onChanged(CHANNELS);
    });
    es.addEventListener("changed", (e) => {
      let channels = CHANNELS;
      try {
        channels = JSON.parse(e.data).channels || CHANNELS;
      } catch {
        /* unreadable event: refetch everything */
      }
      onChanged(channels);
    });
    es.onopen = () => setConnected(true);
    es.onerror = () => setConnected(false); // the browser reconnects; polling covers the gap
    return () => {
      es.close();
      setConnected(false);
    };
  }, [active, onChanged]);
  return connected;
}
