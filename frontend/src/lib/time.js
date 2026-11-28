// Reading and writing times. Every API time is ISO with an offset.

export function parseTs(ts) {
  if (!ts) return null;
  const d = new Date(ts);
  return Number.isNaN(d.getTime()) ? null : d;
}

// How long ago, in its largest unit: "45s", "12m", "3h", "2d".
export function relTime(iso) {
  const d = parseTs(iso);
  if (!d) return "-";
  const s = Math.max(0, (Date.now() - d.getTime()) / 1000);
  if (s < 60) return `${Math.round(s)}s`;
  if (s < 3600) return `${Math.round(s / 60)}m`;
  if (s < 86400) return `${Math.round(s / 3600)}h`;
  return `${Math.round(s / 86400)}d`;
}

// A duration as whole units, largest first: "45s", "1m 12s", "2h 5m".
export function fmtDur(s) {
  if (s == null) return "-";
  const t = Math.max(0, Math.round(s));
  if (t < 60) return `${t}s`;
  if (t < 3600) return t % 60 ? `${Math.floor(t / 60)}m ${t % 60}s` : `${t / 60}m`;
  const m = Math.floor((t % 3600) / 60);
  return m ? `${Math.floor(t / 3600)}h ${m}m` : `${Math.floor(t / 3600)}h`;
}

// The wall-clock time something happened, in the viewer's locale: "10:24 AM".
export function clockTime(iso) {
  const d = parseTs(iso);
  if (!d) return "-";
  return d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

// When a note was written, in the viewer's time zone: "8:57 PM" today,
// "Yesterday, 8:57 PM", then "Sep 23, 8:57 PM" (with the year once it differs).
export function noteTime(ts, now = new Date()) {
  const d = parseTs(ts);
  if (!d) return ts || "-";
  const time = d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  const day = (x) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const days = Math.round((day(now) - day(d)) / 86400000);
  if (days === 0) return time;
  if (days === 1) return `Yesterday, ${time}`;
  const date = d.toLocaleDateString([], {
    month: "short",
    day: "numeric",
    ...(d.getFullYear() !== now.getFullYear() && { year: "numeric" }),
  });
  return `${date}, ${time}`;
}

// The full stamp for a hover title: "Thu, Sep 25, 2026, 8:57:18 PM".
export function fullTime(ts) {
  const d = parseTs(ts);
  return d
    ? d.toLocaleString([], {
        weekday: "short",
        year: "numeric",
        month: "short",
        day: "numeric",
        hour: "numeric",
        minute: "2-digit",
        second: "2-digit",
      })
    : "";
}
