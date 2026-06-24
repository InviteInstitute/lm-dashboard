// Every tunable constant for the dashboard in one place: palette, per-state and
// per-episode colors, trigger metadata, pause legend, and the few magic numbers.
// Change the look/behavior here, not scattered through the component.

// ----- theme / palette -----
export const T = {
    bg: '#0b0e13', panel: '#0f131a', border: '#1f2530', borderSoft: '#171c24',
    ink: '#e6e9ef', sub: '#7d8694', faint: '#5a626e', track: '#0d1117',
};
export const FONT = "'Inter','SF Pro Display',system-ui,sans-serif";
export const MONO = "'SF Mono','JetBrains Mono',ui-monospace,monospace";

// ----- strategy (HMM) states -----
export const STATE = {
    0: { c: '#3b82f6', label: 'Iterator' },
    1: { c: '#a855f7', label: 'Explorer' },
    2: { c: '#ef4444', label: 'Stuck' },
};
export const NOSTATE = { c: '#6b7280', label: 'No runs yet' };
export const WHEEL_STATE = 2;   // HMM "stuck" == wheel-spinning

// ----- episodes -----
export const EP = { CODE: '#3b82f6', RUN: '#22c55e', RESET: '#a855f7' };
export const SOFT_COLOR = '#3a4150';   // greyed sub-tile for absorbed soft (UI) events

// Hatched fills for the two pause kinds, plus the legend rows that render them.
export const HATCH_RED = 'repeating-linear-gradient(45deg,#ef4444 0 4px,#3a1416 4px 8px)';
export const HATCH_AMBER = 'repeating-linear-gradient(45deg,#f59e0b 0 4px,#3a2a10 4px 8px)';
export const PAUSE_FILL = { INACTIVE_PAUSE: HATCH_RED, POST_RUN_PAUSE: HATCH_AMBER };
export const PAUSE_LEGEND = [
    ['INACTIVE', HATCH_RED],
    ['POST RUN PAUSE', HATCH_AMBER],
];

// ----- triggers (intervention alerts) -----
export const TRIGGERS = {
    wheel_spin: { c: '#ef4444', icon: '⟳', label: 'Wheel-spinning' },
    inactive:   { c: '#f59e0b', icon: '⏸', label: 'Inactive' },
    big_change: { c: '#a855f7', icon: '✎', label: 'Big rewrite' },
};
export const TRIGGER_FALLBACK = { c: '#6b7280', icon: '•', label: 'Trigger' };
export const TRIGGER_ROWS = [['wheel_spin', 'Wheel-spinning'], ['inactive', 'Inactive'], ['big_change', 'Big rewrite']];

// ----- misc -----
export const POLL_MS = 1500;
export const COMPACT_TAIL = 10;   // compact cards show only the most recent N runs/episodes; the modal shows all (scrollable)
