// Full-screen Cloudflare Turnstile challenge, shown when the server's
// TurnstileGateMiddleware 403s an /api/* call (see api.js's response
// interceptor, which fires the 'turnstile:required' event this listens for).
// Solving posts the token to /api/turnstile/verify/, which sets the cookie
// the middleware checks; a page reload then re-runs every fetch for real.
import { useEffect, useRef, useState } from "react";
import api from "./api";
import { T, FONT, TURNSTILE_SITE_KEY } from "./constants";

export default function TurnstileGate() {
  const [open, setOpen] = useState(false);
  const [error, setError] = useState(false);
  const elRef = useRef(null);
  const widgetId = useRef(null);

  useEffect(() => {
    const onRequired = () => setOpen(true);
    window.addEventListener("turnstile:required", onRequired);
    return () => window.removeEventListener("turnstile:required", onRequired);
  }, []);

  useEffect(() => {
    if (!open || widgetId.current) return;

    const doRender = () => {
      if (widgetId.current || !window.turnstile || !elRef.current) return;
      widgetId.current = window.turnstile.render(elRef.current, {
        sitekey: TURNSTILE_SITE_KEY,
        action: "turnstile-spin-v2",
        callback: async (token) => {
          try {
            await api.post("/api/turnstile/verify/", { token });
            window.location.reload();
          } catch {
            setError(true);
            window.turnstile.reset(widgetId.current);
          }
        },
        "error-callback": () => setError(true),
      });
    };

    // The Cloudflare api.js is loaded async+defer, so window.turnstile often
    // isn't ready yet when the gate first opens on a fresh page load. Poll until
    // it is, then render; give up after ~15s (script blocked/unreachable) and
    // show the error rather than hanging on "Verifying...".
    if (window.turnstile) {
      doRender();
      return;
    }
    let waited = 0;
    const iv = setInterval(() => {
      if (window.turnstile) {
        clearInterval(iv);
        doRender();
      } else if ((waited += 150) >= 15000) {
        clearInterval(iv);
        setError(true);
      }
    }, 150);
    return () => clearInterval(iv);
  }, [open]);

  if (!open) return null;
  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 9999,
        background: T.bg,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: 16,
        fontFamily: FONT,
        color: T.ink,
      }}
    >
      <p>Verifying you're not a bot&hellip;</p>
      <div ref={elRef} />
      {error && <p style={{ color: "#ef4444" }}>Verification failed. Please try again.</p>}
    </div>
  );
}
