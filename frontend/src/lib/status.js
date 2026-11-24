// A student's headline status and the colours that carry it.
import { TRIGGERS, TRIGGER_FALLBACK, TRIGGER_PRIORITY, STATUS_OK } from "../constants";

export const triggerMeta = (type) => TRIGGERS[type] || TRIGGER_FALLBACK;

// The status a student's card and sheet show: their highest-priority active
// trigger, "OK" with data and no trigger, "No data" before any state exists.
export function statusMeta(triggerType, hasData) {
  if (triggerType) return triggerMeta(triggerType);
  if (!hasData) return { c: "#2a2d3a", label: "No data" };
  return STATUS_OK;
}

// The headline trigger type per student, from the alerts on the board.
export function headlineTriggers(alerts) {
  const by = {};
  alerts.forEach((t) => {
    const cur = by[t.studentID];
    if (cur == null || TRIGGER_PRIORITY.indexOf(t.trigger_type) < TRIGGER_PRIORITY.indexOf(cur))
      by[t.studentID] = t.trigger_type;
  });
  return by;
}

// A trigger hue as text colour: the theme's contrast-safe step for it
// (--lmd-signal-<hex> in styles/base.css), or the hue itself.
export const signal = (c) => `var(--lmd-signal-${c.slice(1)}, ${c})`;

// A tinted surface for something in an alert state: the fill colour (for
// backgrounds and borders) and its contrast-safe text colour.
export const toneVars = (c) => ({ "--tone": c, "--tone-text": signal(c) });
