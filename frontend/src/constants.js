// The dashboard's fixed values in one place: the colours of runs, episodes and
// triggers, the trigger names, and the few timing and size numbers. Theme
// colours live in styles/base.css as --lmd-* custom properties.

// ----- runs: coloured by edit distance to the run before -----
// 0 = an identical re-run, 1..12 = an edit, >= 13 = a big change (what Explorer counts).
export const EXPLORER_ED = 13;
export const ED_ZERO = "#7c8794"; // grey: no change
export const ED_SMALL = "#3a6ea5"; // blue: an edit
export const ED_BIG = "#8a5cc0"; // purple: a big change
export function edColor(d) {
  if (d == null) return "var(--lmd-faint)"; // the first run has nothing to compare with
  if (d === 0) return ED_ZERO;
  return d >= EXPLORER_ED ? ED_BIG : ED_SMALL;
}

// ----- episodes: coloured by type, with hatched pauses between them -----
export const EP = { CODE: "#3a6ea5", RUN: "#2f9467", RESET: "#8a5cc0" };
export const HATCH_RED =
  "repeating-linear-gradient(45deg,#d0433c 0 4px,var(--lmd-hatch-red-bg) 4px 8px)";
export const HATCH_AMBER =
  "repeating-linear-gradient(45deg,#d38b12 0 4px,var(--lmd-hatch-amber-bg) 4px 8px)";
export const PAUSE_FILL = { INACTIVE_PAUSE: HATCH_RED, POST_RUN_PAUSE: HATCH_AMBER };
export const PAUSE_LEGEND = [
  ["INACTIVE", HATCH_RED],
  ["POST RUN PAUSE", HATCH_AMBER],
];

// ----- triggers: the five alerts, in the order the Triggers panel lists them -----
// `c` is the trigger's hue. Text in that hue uses the theme's contrast-safe step
// for it (--lmd-signal-<hex>, see lib/status.js).
export const TRIGGERS = {
  wheel_spin: { c: "#d0433c", icon: "wheelSpin", label: "Wheel-spinning" },
  resilience: { c: "#2f9467", icon: "resilience", label: "Resilience" },
  inactive: { c: "#d38b12", icon: "inactive", label: "Inactive" },
  explorer: { c: "#8a5cc0", icon: "explorer", label: "Explorer" },
  iterative: { c: "#3a6ea5", icon: "iterative", label: "Step-by-Step" },
};
export const TRIGGER_FALLBACK = { c: "#7c8794", icon: "trigger", label: "Trigger" };
// When a student has several triggers at once, the first in this list is their
// headline status (only wheel_spin before resilience matters in practice).
export const TRIGGER_PRIORITY = ["wheel_spin", "inactive", "resilience", "explorer", "iterative"];
export const STATUS_OK = { c: "#2f9467", label: "OK" };

// ----- timing and size -----
export const POLL_MS = 1500; // the poll interval while the event stream is down
export const COMPACT_TAIL = 10; // a card shows the last N runs and episodes; the sheet shows all

// The Turnstile site key is public by design: it pairs with the secret key,
// which never leaves the server (see TurnstileGate.jsx).
export const TURNSTILE_SITE_KEY = "0x4AAAAAAD9y1rcwgwx5PODV";
