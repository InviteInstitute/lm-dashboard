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
// One family for the whole tool: IBM Plex Sans for UI and headings, Plex Mono
// for student IDs, code and measurements. Defined once as CSS vars in index.css.
export const FONT = "var(--lmd-font)";
export const HEADFONT = FONT;
export const MONO = "var(--lmd-mono)";

// ----- per-run edit_distance buckets (the run track colours) -----
// 0 = identical re-run, 1..12 = incremental edit, >=13 = a big change (explorer).
export const EXPLORER_ED = 13;
export const ED_ZERO = "#7c8794"; // grey: no change
export const ED_SMALL = "#3a6ea5"; // blue: incremental edit
export const ED_BIG = "#8a5cc0"; // purple: large change
export function edColor(d) {
  if (d == null) return T.faint; // first run, no predecessor
  if (d === 0) return ED_ZERO;
  return d >= EXPLORER_ED ? ED_BIG : ED_SMALL;
}

// ----- episodes -----
export const EP = { CODE: "#3a6ea5", RUN: "#2f9467", RESET: "#8a5cc0" };
export const SOFT_COLOR = "#3a4150"; // greyed sub-tile for absorbed soft (UI) events

// Hatched fills for the two pause kinds, plus the legend rows that render them.
export const HATCH_RED =
  "repeating-linear-gradient(45deg,#d0433c 0 4px,var(--lmd-hatch-red-bg) 4px 8px)";
export const HATCH_AMBER =
  "repeating-linear-gradient(45deg,#d38b12 0 4px,var(--lmd-hatch-amber-bg) 4px 8px)";
export const PAUSE_FILL = { INACTIVE_PAUSE: HATCH_RED, POST_RUN_PAUSE: HATCH_AMBER };
export const PAUSE_LEGEND = [
  ["INACTIVE", HATCH_RED],
  ["POST RUN PAUSE", HATCH_AMBER],
];

// ----- triggers (intervention alerts) -----
export const TRIGGERS = {
  wheel_spin: { c: "#d0433c", icon: "wheelSpin", label: "Wheel-spinning" },
  resilience: { c: "#2f9467", icon: "resilience", label: "Resilience" },
  inactive: { c: "#d38b12", icon: "inactive", label: "Inactive" },
  explorer: { c: "#8a5cc0", icon: "explorer", label: "Explorer" },
  iterative: { c: "#3a6ea5", icon: "iterative", label: "Step-by-Step" },
};
export const TRIGGER_FALLBACK = { c: "#7c8794", icon: "trigger", label: "Trigger" };
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
export const STATUS_OK = { c: "#2f9467", label: "OK" };

// ----- misc -----
export const POLL_MS = 1500;
export const COMPACT_TAIL = 10; // compact cards show only the most recent N runs/episodes; the modal shows all (scrollable)

// Turnstile site key is public by design (paired server-side with the secret
// key, which never leaves the backend) -- see TurnstileGate.jsx.
export const TURNSTILE_SITE_KEY = "0x4AAAAAAD9y1rcwgwx5PODV";
