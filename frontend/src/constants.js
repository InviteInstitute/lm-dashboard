// Every tunable constant for the dashboard in one place: palette, per-state and
// per-episode colors, trigger metadata, pause legend, and the few magic numbers.
// Change the look/behavior here, not scattered through the component.

// ----- theme / palette -----
// Values are CSS custom properties (see index.css's :root / [data-theme="dark"])
// rather than literal hex, so a theme switch is just flipping the data-theme
// attribute on <html> -- no React state threading needed for any of this.
export const T = {
  bg: "var(--lmd-bg)",
  panel: "var(--lmd-panel)",
  border: "var(--lmd-border)",
  ink: "var(--lmd-ink)",
  sub: "var(--lmd-sub)",
  faint: "var(--lmd-faint)",
  track: "var(--lmd-track)",
  code: "var(--lmd-code)",
};
export const FONT =
  "'Source Sans Pro',-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif";
export const HEADFONT =
  "'Montserrat',-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif";
export const MONO = "'SF Mono','JetBrains Mono',ui-monospace,monospace";

// ----- per-run edit_distance buckets (the run track colours) -----
// 0 = identical re-run, 1..12 = incremental edit, >=13 = a big change (explorer).
export const EXPLORER_ED = 13;
export const ED_ZERO = "#6b7280"; // grey: no change
export const ED_SMALL = "#3b82f6"; // blue: incremental edit
export const ED_BIG = "#a855f7"; // purple: large change
export function edColor(d) {
  if (d == null) return T.faint; // first run, no predecessor
  if (d === 0) return ED_ZERO;
  return d >= EXPLORER_ED ? ED_BIG : ED_SMALL;
}

// ----- episodes -----
export const EP = { CODE: "#3b82f6", RUN: "#22c55e", RESET: "#a855f7" };
export const SOFT_COLOR = "#3a4150"; // greyed sub-tile for absorbed soft (UI) events

// Hatched fills for the two pause kinds, plus the legend rows that render them.
export const HATCH_RED =
  "repeating-linear-gradient(45deg,#ef4444 0 4px,var(--lmd-hatch-red-bg) 4px 8px)";
export const HATCH_AMBER =
  "repeating-linear-gradient(45deg,#f59e0b 0 4px,var(--lmd-hatch-amber-bg) 4px 8px)";
export const PAUSE_FILL = { INACTIVE_PAUSE: HATCH_RED, POST_RUN_PAUSE: HATCH_AMBER };
export const PAUSE_LEGEND = [
  ["INACTIVE", HATCH_RED],
  ["POST RUN PAUSE", HATCH_AMBER],
];

// ----- triggers (intervention alerts) -----
export const TRIGGERS = {
  wheel_spin: { c: "#ef4444", icon: "⟳", label: "Wheel-spinning" },
  resilience: { c: "#22c55e", icon: "✦", label: "Resilience" },
  inactive: { c: "#f59e0b", icon: "⏸", label: "Inactive" },
  explorer: { c: "#a855f7", icon: "✎", label: "Explorer" },
  iterative: { c: "#3b82f6", icon: "◇", label: "Step-by-Step" },
};
export const TRIGGER_FALLBACK = { c: "#6b7280", icon: "•", label: "Trigger" };
export const TRIGGER_ROWS = [
  ["wheel_spin", "Wheel-spinning"],
  ["resilience", "Resilience"],
  ["inactive", "Inactive"],
  ["explorer", "Explorer"],
  ["iterative", "Step-by-Step"],
];
// Headline-status precedence when a student has several active triggers at once
// (only wheel_spin > resilience is load-bearing).
export const TRIGGER_PRIORITY = ["wheel_spin", "inactive", "resilience", "explorer", "iterative"];
export const STATUS_OK = { c: "#22c55e", label: "OK" };

// ----- misc -----
export const POLL_MS = 1500;
export const COMPACT_TAIL = 10; // compact cards show only the most recent N runs/episodes; the modal shows all (scrollable)

// Turnstile site key is public by design (paired server-side with the secret
// key, which never leaves the backend) -- see TurnstileGate.jsx.
export const TURNSTILE_SITE_KEY = "0x4AAAAAAD9y1rcwgwx5PODV";
