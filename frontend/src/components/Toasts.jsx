// Toasts in the bottom-right corner: identity switches as they happen, and the
// outcome of an action. Most leave on their own after a few seconds. A failed
// save stays until dismissed, since an error that vanishes by itself isn't loud.
import React from "react";
import { ToastNotification } from "@carbon/react";

const TOAST_MS = 6000;

// The toast list and the ways to add to it. `push` takes a toast with an `id`;
// `notify(kind, title, sub)` makes one, sticky when `kind` is "error".
export function useToasts() {
  const [toasts, setToasts] = React.useState([]);
  const seq = React.useRef(0);
  const dismiss = React.useCallback((id) => setToasts((t) => t.filter((x) => x.id !== id)), []);
  const push = React.useCallback(
    (toast, sticky = false) => {
      setToasts((t) => [...t, toast]);
      if (!sticky) setTimeout(() => dismiss(toast.id), TOAST_MS);
    },
    [dismiss],
  );
  const notify = React.useCallback(
    (kind, title, sub) => push({ id: `note-${++seq.current}`, kind, title, sub }, kind === "error"),
    [push],
  );
  const clear = React.useCallback(() => setToasts([]), []);
  return { toasts, push, notify, dismiss, clear };
}

export const Toasts = ({ toasts, onClose }) =>
  toasts.length > 0 && (
    <div className="toast-stack">
      {toasts.map((t) => (
        <ToastNotification
          key={t.id}
          kind={t.kind || "warning"}
          lowContrast
          timeout={0}
          title={t.title}
          subtitle={t.sub}
          onClose={() => {
            onClose(t.id);
            return false;
          }}
        />
      ))}
    </div>
  );
