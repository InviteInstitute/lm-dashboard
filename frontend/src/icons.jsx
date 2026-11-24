// The dashboard's own stroke icons: one per trigger, plus the swap and alert
// marks. Carbon's icon set covers the buttons. Every glyph shares one geometry:
// a 24x24 viewBox, no fill, currentColor stroke at 1.75, round caps and joins.
// Size and color come from the caller (font-size-like `size`, `currentColor`),
// so an icon sits inline with its label and inherits the label's color.
import React from "react";

const PATHS = {
  // wheel-spinning: a closed rotation, the "running the same thing again" signal
  wheelSpin: <path d="M21 12a9 9 0 1 1-2.64-6.36M21 4v4h-4" />,
  // resilience: recovery, a line that dips and climbs back
  resilience: <path d="M3 14l4-4 3 3 5-6 3 3 3-3" />,
  // inactive: a clock, time passing with no activity
  inactive: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M12 7.5V12l3 1.8" />
    </>
  ),
  // explorer: a compass, ranging widely across the space
  explorer: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M15.6 8.4l-2 5.2-5.2 2 2-5.2z" />
    </>
  ),
  // step-by-step: a staircase of deliberate moves
  iterative: <path d="M3 19h4v-4h4v-4h4v-4h5" />,
  // trigger (fallback): a small target
  trigger: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <circle cx="12" cy="12" r="2.5" />
    </>
  ),
  swap: <path d="M7 4L3 8l4 4M3 8h13M17 20l4-4-4-4M21 16H8" />,
  alert: <path d="M12 4l9 16H3z M12 10v4 M12 17.5h.01" />,
};

export function Icon({ name, size = 16, style, ...rest }) {
  const glyph = PATHS[name] || PATHS.trigger;
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      style={{ display: "block", flexShrink: 0, ...style }}
      {...rest}
    >
      {glyph}
    </svg>
  );
}
