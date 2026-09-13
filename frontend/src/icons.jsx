// A small, self-authored stroke-icon set so the dashboard draws its icons
// instead of borrowing unicode glyphs/emoji. Every glyph shares one geometry:
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
  pause: (
    <>
      <path d="M9 5v14" />
      <path d="M15 5v14" />
    </>
  ),
  play: <path d="M7 5l12 7-12 7z" />,
  reset: <path d="M3 12a9 9 0 1 0 2.64-6.36M3 4v4h4" />,
  download: <path d="M12 4v11m-4.5-4.5L12 15l4.5-4.5M5 20h14" />,
  // triggers config: three sliders
  sliders: (
    <>
      <path d="M5 8h9M18 8h1M5 16h1M10 16h9" />
      <circle cx="16" cy="8" r="2" />
      <circle cx="8" cy="16" r="2" />
    </>
  ),
  sun: (
    <>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
    </>
  ),
  moon: <path d="M20 13.5A8 8 0 1 1 10.5 4a6.5 6.5 0 0 0 9.5 9.5z" />,
  close: <path d="M6 6l12 12M18 6L6 18" />,
  swap: <path d="M7 4L3 8l4 4M3 8h13M17 20l4-4-4-4M21 16H8" />,
  alert: <path d="M12 4l9 16H3z M12 10v4 M12 17.5h.01" />,
  check: <path d="M20 6L9 17l-5-5" />,
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

export default Icon;
