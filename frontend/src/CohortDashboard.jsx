// The entire dashboard, in one component file.
//
// It polls the read API on a fixed timer and renders three things from what it
// gets back: a grid of per-student cards (strategy + episode sparklines, plus
// present/picked toggles), a "who needs help" alert column on the right, and a
// drill-down modal with the full detail and the notes log. Everything the user
// does writes straight through to the API; nothing is computed here, the daemon
// already did the work.
import React from "react";
import api, { API_URL, boardId } from "./api";
import { Icon } from "./icons";
import {
  T,
  FONT,
  HEADFONT,
  MONO,
  edColor,
  ED_ZERO,
  ED_SMALL,
  ED_BIG,
  EP,
  HATCH_AMBER,
  PAUSE_FILL,
  PAUSE_LEGEND,
  TRIGGERS,
  TRIGGER_FALLBACK,
  TRIGGER_ROWS,
  TRIGGER_PRIORITY,
  STATUS_OK,
  POLL_MS,
  COMPACT_TAIL,
} from "./constants";

const THEME_KEY = "lm_theme";

// Re-exported so existing imports/tests that pull these from the component file
// keep working; the source of truth is ./constants.
export { COMPACT_TAIL } from "./constants";

const triggerMeta = (type) => TRIGGERS[type] || TRIGGER_FALLBACK;

export function relTime(iso) {
  if (!iso) return "-";
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return `${Math.round(s)}s`;
  if (s < 3600) return `${Math.round(s / 60)}m`;
  if (s < 86400) return `${Math.round(s / 3600)}h`;
  return `${Math.round(s / 86400)}d`;
}
export function fmtDur(s) {
  if (s == null) return "-";
  if (s < 60) return `${s.toFixed(1)}s`;
  if (s < 3600) return `${(s / 60).toFixed(1)}m`;
  return `${(s / 3600).toFixed(1)}h`;
}
// Wall-clock time for "at what time did that fire" readouts (alert prev-line,
// trigger-history grid). Locale-aware, e.g. "10:24 AM".
export function clockTime(iso) {
  if (!iso) return "-";
  return new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}
// Save a Blob to the user's computer as `filename`. A browser can't write to
// disk directly, so the trick is to point a temporary <a download> at an
// in-memory object URL for the blob, click it, then release the URL.
export function triggerDownload(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");

  link.href = url;
  link.download = filename;
  link.click();

  // Clean up memory
  URL.revokeObjectURL(url);
}
// Run `fn` now and every POLL_MS, but only while `active` is true. When `active`
// flips false the interval is torn down; when it flips back true we fetch once
// immediately (catch up) before resuming the timer. Gating every poll loop on
// one flag is how the Page Visibility pause reaches all of them at once.
function usePoll(fn, active) {
  React.useEffect(() => {
    if (!active) return;
    fn();
    const id = setInterval(fn, POLL_MS);
    return () => clearInterval(id);
  }, [fn, active]);
}

// Live updates over Server-Sent Events. While `active`, opens one stream to the
// API and calls `onChanged(channels)` whenever the server reports a change (and
// once on connect, with all channels, to seed the first fetch). Returns whether
// the stream is currently connected; the caller gates its poll loops on the
// negation, so polling is the automatic fallback -- when EventSource is missing
// (jsdom under test) or the connection drops, the timers take over until the
// browser reconnects. This is what lets one stream replace four poll loops
// without ever risking a stale board.
function useEventStream(onChanged, active) {
  const [connected, setConnected] = React.useState(false);
  React.useEffect(() => {
    if (!active || typeof EventSource === "undefined") return undefined;
    // EventSource can't set headers, so the per-browser board id rides as a
    // query param (the API accepts it there for the stream).
    const es = new EventSource(`${API_URL}/api/stream/?board_id=${encodeURIComponent(boardId())}`);
    const ALL = ["states", "roster", "triggers", "switches"];
    es.addEventListener("hello", () => {
      setConnected(true);
      onChanged(ALL);
    });
    es.addEventListener("changed", (e) => {
      let channels = ALL;
      try {
        channels = JSON.parse(e.data).channels || ALL;
      } catch {
        /* refetch all */
      }
      onChanged(channels);
    });
    es.onopen = () => setConnected(true);
    es.onerror = () => setConnected(false); // browser auto-reconnects; polls cover the gap
    return () => {
      es.close();
      setConnected(false);
    };
  }, [active, onChanged]);
  return connected;
}

// True while this browser tab is actually on screen, via the Page Visibility
// API. It drives usePoll, so a backgrounded / minimized tab stops polling
// entirely -- and because those polls double as the daemon's "someone is
// watching" signal, a tab no one is looking at lets prod polling wind down.
function usePageVisible() {
  const [visible, setVisible] = React.useState(!document.hidden);
  React.useEffect(() => {
    const onChange = () => setVisible(!document.hidden);
    document.addEventListener("visibilitychange", onChange);
    return () => document.removeEventListener("visibilitychange", onChange);
  }, []);
  return visible;
}

// A student's headline status is derived from their active triggers (highest
// priority wins; wheel_spin > resilience is the only load-bearing rule). No
// active trigger with data -> "OK"; no materialized state yet -> "No data".
export function statusMeta(triggerType, hasData) {
  if (triggerType) return TRIGGERS[triggerType] || TRIGGER_FALLBACK;
  if (!hasData) return { c: "#2a2d3a", label: "No data" };
  return STATUS_OK;
}

// ---------------- timelines ----------------
// A "tile strip" of blocks. Each block is one unit -- an HMM run, or one EPISODE.
//
// Soft-fold (flush=true, episodes only): the hard/soft boundary idea. Soft
// boundaries -- the transitions BETWEEN consecutive work episodes -- are folded
// away: episodes sit flush, so a coding->run->coding stretch reads as ONE
// continuous activity strip (color changes mark the type). The ONLY breaks are
// HARD boundaries: the real pauses (INACTIVE / POST_RUN), drawn as a hatched gap
// with margin. So the bar shows "bursts of work separated by real pauses" rather
// than a gap after every episode. HMM runs keep their normal gapped look.
const leaf = (s, compact, flush) => {
  const r = flush ? 0 : 2; // flush blocks are square; the strip rounds at its ends
  if (s.pause)
    return {
      flex: compact ? "0 0 5px" : "0 0 9px",
      borderRadius: r,
      background: s.bg,
      ...(flush ? { marginInline: compact ? 3 : 5 } : {}), // hard boundary == the only break
    };
  return {
    // episode block or HMM run: every block the same width
    flex: compact ? "1 1 0" : "1 0 14px",
    minWidth: compact ? 0 : 3,
    borderRadius: r,
    background: s.bg,
    opacity: s.faint ? 0.4 : 1,
  };
};

const Track = ({ segments, compact, flush }) => {
  const ref = React.useRef(null);
  React.useLayoutEffect(() => {
    if (!compact && ref.current) ref.current.scrollLeft = ref.current.scrollWidth;
  }, [compact, segments.length]);
  const base = compact ? trkSm : trk;
  const style = flush ? { ...base, gap: 0, overflowY: "hidden" } : base; // flush: fold soft seams
  return (
    <div ref={ref} style={style}>
      {segments.map((s) => (
        <div key={s.key} title={s.title} style={leaf(s, compact, flush)} />
      ))}
    </div>
  );
};

// data -> segment list. Compact slices to the last COMPACT_TAIL units. Each run
// is coloured by its edit_distance: grey = no change, blue = incremental edit,
// purple = a big change (>=13).
function runSegments(data, compact) {
  const all = data.runs || [];
  const runs = compact && all.length > COMPACT_TAIL ? all.slice(-COMPACT_TAIL) : all;
  const off = all.length - runs.length;
  return runs.map((run, i) => {
    const d = run.edit_distance;
    return {
      key: `r${i + off}`,
      bg: edColor(d),
      faint: d == null,
      title: `Run #${i + off + 1} | ${d == null ? "first run" : `edit distance ${d}`}`,
    };
  });
}

function episodeSegments(data, compact) {
  const all = data.episodes || [];
  const eps = compact && all.length > COMPACT_TAIL ? all.slice(-COMPACT_TAIL) : all;
  const minIdx = eps.length ? eps[0].start_idx : 0;
  const pauseAt = {};
  (data.pauses || []).forEach((p) => {
    pauseAt[p.after_idx] = p;
  });
  const segs = [];
  eps.forEach((ep) => {
    // One equal-width block per episode. The events themselves are summarized
    // in the tooltip (count + duration), not drawn.
    const dur = ep.start_ts != null && ep.end_ts != null ? ep.end_ts - ep.start_ts : null;
    segs.push({
      key: `e${ep.start_idx}`,
      bg: EP[ep.episode_type] || EP.CODE,
      title: `${ep.episode_type} | ${ep.event_count} events${dur != null ? ` | ${fmtDur(dur)}` : ""}`,
    });
    const p = pauseAt[ep.end_idx - 1];
    if (p && p.after_idx >= minIdx) {
      segs.push({
        key: `p${ep.end_idx}`,
        pause: true,
        bg: PAUSE_FILL[p.episode_type] || HATCH_AMBER,
        title: `${p.episode_type} | ${fmtDur(p.duration)}`,
      });
    }
  });
  return segs;
}

const RunTrack = ({ data, compact }) => {
  if (!data || !data.runs || data.runs.length === 0)
    return <div style={emptyTxt(compact)}>No runs yet.</div>;
  return (
    <>
      <Track segments={runSegments(data, compact)} compact={compact} />
      {!compact && (
        <div style={legend}>
          <span>
            <i style={sw(ED_ZERO)} />
            No change
          </span>
          <span>
            <i style={sw(ED_SMALL)} />
            Edit
          </span>
          <span>
            <i style={sw(ED_BIG)} />
            Big change (&gt;=13)
          </span>
        </div>
      )}
    </>
  );
};

const EpisodeTrack = ({ data, compact }) => {
  if (!data || data.event_count === 0) return <div style={emptyTxt(compact)}>No events yet.</div>;
  return (
    <>
      <Track segments={episodeSegments(data, compact)} compact={compact} flush />
      {!compact && (
        <div style={legend}>
          <span>
            <i style={sw(EP.CODE)} />
            CODE
          </span>
          <span>
            <i style={sw(EP.RUN)} />
            RUN
          </span>
          <span>
            <i style={sw(EP.RESET)} />
            RESET
          </span>
          {PAUSE_LEGEND.map(([label, fill]) => (
            <span key={label}>
              <i style={sw(fill)} />
              {label}
            </span>
          ))}
        </div>
      )}
    </>
  );
};

// Equal tiles, consistent 2px gap, slight rounding. Full scrolls; compact hides
// overflow (already windowed to the last COMPACT_TAIL).
const trk = {
  display: "flex",
  gap: 2,
  height: 28,
  background: T.track,
  border: `1px solid ${T.border}`,
  borderRadius: 8,
  padding: 2,
  boxSizing: "border-box",
  overflowX: "auto",
  scrollbarWidth: "thin",
};
const trkSm = { ...trk, height: 18, borderRadius: 6, overflowX: "hidden" };
const legend = {
  display: "flex",
  gap: 14,
  flexWrap: "wrap",
  marginTop: 9,
  fontSize: 11.5,
  color: T.sub,
};
const sw = (bg) => ({
  display: "inline-block",
  width: 11,
  height: 11,
  borderRadius: 3,
  marginRight: 6,
  verticalAlign: "middle",
  background: bg,
});
const emptyTxt = (compact) => ({ color: T.sub, fontSize: compact ? 11.5 : 13 });

// ---------------- goal evidence (inside modal) ----------------
// Per-run goal recognition from the agent-lm goal_strategy engine: for each
// profiled Castle Crashers run, the goals with the rung reached and the
// uncertainty flags. This is EVIDENCE with explicit abstentions, not a score or
// an assessment of the student's ability -- the flags are the whole point.
const _humanize = (s) => (s || "").replace(/_/g, " ");

const goalFlagChip = {
  fontFamily: MONO,
  fontSize: 10.5,
  color: "var(--lmd-signal-amber, #b7791f)",
  border: `1px solid ${T.border}`,
  borderRadius: 5,
  padding: "1px 6px",
  background: T.bg,
  whiteSpace: "nowrap",
};

const GoalEvidence = ({ runs, enabled }) => {
  if (enabled === false)
    return <div style={{ color: T.sub, fontSize: 13 }}>Goal recognition is switched off.</div>;
  if (!runs || runs.length === 0)
    return (
      <div style={{ color: T.sub, fontSize: 13 }}>
        No Castle Crashers runs profiled yet (goal evidence is Castle Crashers only).
      </div>
    );
  return (
    <div
      style={{
        maxHeight: 320,
        overflowY: "auto",
        display: "flex",
        flexDirection: "column",
        gap: 10,
      }}
    >
      {runs.map((r) => (
        <div
          key={r.index}
          style={{
            border: `1px solid ${T.border}`,
            borderRadius: 10,
            padding: "10px 12px",
            background: T.track,
          }}
        >
          <div
            style={{
              fontFamily: MONO,
              fontSize: 11,
              color: T.sub,
              marginBottom: 8,
              letterSpacing: 0.5,
            }}
          >
            RUN {r.index}
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
            {(r.goals || []).map((g) => (
              <div key={g.goal}>
                <div
                  style={{
                    fontSize: 12.5,
                    fontWeight: 700,
                    color: T.ink,
                    marginBottom: 3,
                    textTransform: "capitalize",
                  }}
                >
                  {_humanize(g.goal)}
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
                  {(g.indicators || []).map((ind, i) => (
                    <div
                      key={i}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 8,
                        flexWrap: "wrap",
                        fontSize: 12,
                        fontFamily: MONO,
                      }}
                    >
                      <span style={{ color: T.sub, minWidth: 168 }}>{_humanize(ind.name)}</span>
                      {ind.abstained ? (
                        <span style={{ color: T.faint }}>
                          — {_humanize(ind.abstain_reason) || "abstained"}
                        </span>
                      ) : (
                        <span style={{ color: T.ink }}>{_humanize(ind.rung) || "—"}</span>
                      )}
                      {(ind.flags || []).map((f) => (
                        <span key={f} style={goalFlagChip}>
                          {_humanize(f)}
                        </span>
                      ))}
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
};

// ---------------- detail (inside modal) ----------------
// The body of the drill-down modal for one student: header + state badge, the
// playground prompt, and full-size episode and strategy timelines.
const Detail = ({ s, sid, status, history = [] }) => {
  if (!s)
    return (
      <div style={{ color: T.sub, padding: 30 }}>
        No activity yet for <b style={{ fontFamily: MONO }}>{sid}</b>.
      </div>
    );
  const cur = status || STATUS_OK;
  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 20 }}>
        <span style={{ fontFamily: MONO, fontSize: 20, fontWeight: 700 }}>
          {s.display || s.studentID}
        </span>
        <span
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 7,
            background: "var(--lmd-track)",
            color: `var(--lmd-signal-${cur.c.slice(1)}, ${cur.c})`,
            border: "1px solid var(--lmd-border)",
            borderRadius: 6,
            padding: "4px 11px",
            fontSize: 11,
            fontWeight: 700,
            letterSpacing: 0.5,
            textTransform: "uppercase",
          }}
        >
          <span
            style={{ width: 7, height: 7, borderRadius: "50%", background: cur.c, flexShrink: 0 }}
          />
          {cur.label}
        </span>
        <span
          style={{
            marginLeft: "auto",
            color: T.sub,
            fontSize: 12.5,
            fontVariantNumeric: "tabular-nums",
          }}
        >
          runs <b style={{ color: T.ink }}>{s.run_count}</b> | events{" "}
          <b style={{ color: T.ink }}>{s.event_count}</b>
        </span>
      </div>
      <div style={lbl}>Program</div>
      {s.block && s.block.readable ? (
        <pre style={pre}>{s.block.readable}</pre>
      ) : (
        <div style={{ color: T.sub, fontSize: 13, marginBottom: 22 }}>No program yet</div>
      )}
      <div style={{ ...lbl, marginTop: 22 }}>Playground</div>
      {s.block && s.block.llm_prompt ? (
        <pre style={pre}>{s.block.llm_prompt}</pre>
      ) : (
        <div style={{ color: T.sub, fontSize: 13, marginBottom: 22 }}>
          No playground yet due to no runs
        </div>
      )}
      <div style={{ ...lbl, marginTop: 22 }}>Episode timeline</div>
      <EpisodeTrack data={s.episodes} />
      <div style={{ ...lbl, marginTop: 22 }}>Runs | edit distance per run</div>
      <RunTrack data={s.runs} />
      <div style={{ ...lbl, marginTop: 22 }}>Goal evidence (with uncertainty)</div>
      <GoalEvidence runs={s.goal_runs} enabled={s.goal_recognition_enabled} />
      <div style={{ ...lbl, marginTop: 22 }}>Trigger history</div>
      {history.length === 0 ? (
        <div style={{ color: T.sub, fontSize: 13 }}>No triggers yet this session</div>
      ) : (
        <div style={{ maxHeight: 200, overflowY: "auto" }}>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "auto auto 1fr auto",
              gap: "5px 16px",
              fontSize: 12.5,
              fontFamily: MONO,
              alignItems: "center",
            }}
          >
            {["Time", "Trigger", "Value", "Status"].map((h) => (
              <span
                key={h}
                style={{
                  color: T.faint,
                  fontSize: 10.5,
                  textTransform: "uppercase",
                  letterSpacing: 0.6,
                }}
              >
                {h}
              </span>
            ))}
            {history.map((h) => {
              const m = triggerMeta(h.trigger_type);
              return (
                <React.Fragment key={h.id}>
                  <span style={{ color: T.sub }} title={h.started_at}>
                    {clockTime(h.started_at)}
                  </span>
                  <span
                    style={{
                      color: `var(--lmd-signal-${m.c.slice(1)}, ${m.c})`,
                      fontWeight: 700,
                      display: "inline-flex",
                      alignItems: "center",
                      gap: 6,
                    }}
                  >
                    <Icon name={m.icon} size={14} />
                    {h.label}
                  </span>
                  <span style={{ color: T.ink }}>{h.value || "-"}</span>
                  <span style={{ color: h.status === "active" ? m.c : T.faint }}>{h.status}</span>
                </React.Fragment>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
};
const lbl = {
  fontFamily: HEADFONT,
  fontSize: 11,
  fontWeight: 700,
  letterSpacing: 1,
  color: T.sub,
  textTransform: "uppercase",
  marginBottom: 10,
};
const pre = {
  margin: 0,
  padding: 14,
  background: T.track,
  border: `1px solid ${T.border}`,
  borderRadius: 10,
  fontFamily: MONO,
  fontSize: 12.5,
  lineHeight: 1.5,
  whiteSpace: "pre-wrap",
  color: T.code,
  maxHeight: 280,
  overflow: "auto",
  marginBottom: 4,
};

// ---------------- layout ----------------
// One big style object for the whole screen. Plain inline-style dicts (some are
// functions of an accent color), no CSS framework.
const S = {
  page: {
    background: T.bg,
    minHeight: "100dvh",
    display: "flex",
    flexDirection: "column",
    fontFamily: FONT,
    color: T.ink,
  },
  bar: {
    display: "flex",
    alignItems: "center",
    gap: 14,
    padding: "16px 28px",
    borderBottom: `1px solid ${T.border}`,
    flexWrap: "wrap",
    flexShrink: 0,
  },
  title: {
    fontFamily: HEADFONT,
    fontSize: 18,
    fontWeight: 700,
    letterSpacing: 0.4,
    display: "flex",
    alignItems: "center",
    gap: 9,
  },
  input: {
    background: T.panel,
    border: `1px solid ${T.border}`,
    borderRadius: 8,
    color: T.ink,
    padding: "9px 16px",
    fontSize: 14,
    fontFamily: FONT,
    width: 220,
  },
  export: {
    display: "inline-flex",
    alignItems: "center",
    gap: 7,
    background: "var(--lmd-panel)",
    color: "var(--lmd-sub)",
    border: `1px solid ${T.border}`,
    borderRadius: 8,
    padding: "9px 14px",
    fontSize: 13,
    fontWeight: 600,
    cursor: "pointer",
    fontFamily: FONT,
    whiteSpace: "nowrap",
  },
  reset: {
    display: "inline-flex",
    alignItems: "center",
    gap: 7,
    background: "var(--lmd-panel)",
    color: "var(--lmd-sub)",
    border: `1px solid ${T.border}`,
    borderRadius: 8,
    padding: "9px 14px",
    fontSize: 13,
    fontWeight: 600,
    cursor: "pointer",
    fontFamily: FONT,
    whiteSpace: "nowrap",
  },
  pollPause: {
    display: "inline-flex",
    alignItems: "center",
    gap: 7,
    background: "var(--lmd-panel)",
    color: "var(--lmd-sub)",
    border: `1px solid ${T.border}`,
    borderRadius: 8,
    padding: "9px 14px",
    fontSize: 13,
    fontWeight: 600,
    cursor: "pointer",
    fontFamily: FONT,
    whiteSpace: "nowrap",
  },
  pollResume: {
    display: "inline-flex",
    alignItems: "center",
    gap: 7,
    background: "var(--lmd-panel)",
    color: "var(--lmd-ink)",
    border: `1px solid ${T.border}`,
    borderRadius: 8,
    padding: "9px 14px",
    fontSize: 13,
    fontWeight: 600,
    cursor: "pointer",
    fontFamily: FONT,
    whiteSpace: "nowrap",
  },
  toggleRow: { display: "flex", gap: 6, marginTop: 10 },
  tgBtn: {
    flex: 1,
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    borderRadius: 8,
    padding: "6px 8px",
    fontSize: 13,
    fontWeight: 600,
    cursor: "pointer",
    fontFamily: FONT,
    background: "transparent",
    color: T.sub,
    border: `1px solid ${T.border}`,
  },
  presDot: (on) => ({
    width: 7,
    height: 7,
    borderRadius: "50%",
    flexShrink: 0,
    background: on ? "currentColor" : "transparent",
    border: on ? "none" : "1.5px solid currentColor",
  }),
  triggersBtn: {
    display: "inline-flex",
    alignItems: "center",
    gap: 7,
    background: T.panel,
    color: T.ink,
    border: `1px solid ${T.border}`,
    borderRadius: 8,
    padding: "9px 14px",
    fontSize: 13,
    fontWeight: 600,
    cursor: "pointer",
    fontFamily: FONT,
    whiteSpace: "nowrap",
  },
  themeToggle: {
    background: T.panel,
    color: T.ink,
    border: `1px solid ${T.border}`,
    borderRadius: 8,
    width: 38,
    height: 38,
    fontSize: 15,
    cursor: "pointer",
    fontFamily: FONT,
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    flexShrink: 0,
  },
  popOverlay: { position: "fixed", inset: 0, background: "transparent", zIndex: 40 },
  popPanel: {
    position: "fixed",
    top: 64,
    right: 28,
    width: 240,
    background: T.panel,
    border: `1px solid ${T.border}`,
    borderRadius: 12,
    padding: 12,
    boxShadow: "0 10px 30px #0008",
    zIndex: 41,
  },
  popTitle: {
    fontSize: 12,
    fontWeight: 800,
    color: T.sub,
    textTransform: "uppercase",
    letterSpacing: 0.5,
    marginBottom: 8,
  },
  popRow: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    padding: "6px 0",
    fontSize: 13,
    color: T.ink,
  },
  tgOn: {
    background: "var(--lmd-track)",
    color: "var(--lmd-success)",
    border: `1px solid ${T.border}`,
    borderRadius: 8,
    padding: "4px 14px",
    fontSize: 12,
    fontWeight: 600,
    cursor: "pointer",
    fontFamily: FONT,
  },
  tgOff: {
    background: "transparent",
    color: T.faint,
    border: `1px solid ${T.border}`,
    borderRadius: 8,
    padding: "4px 14px",
    fontSize: 12,
    fontWeight: 600,
    cursor: "pointer",
    fontFamily: FONT,
  },
  noteEditor: { marginTop: 8, display: "flex", flexDirection: "column", gap: 6 },
  noteArea: {
    width: "100%",
    minHeight: 54,
    resize: "vertical",
    background: T.panel,
    border: `1px solid ${T.border}`,
    borderRadius: 8,
    color: T.ink,
    padding: "7px 9px",
    fontSize: 12.5,
    fontFamily: FONT,
    boxSizing: "border-box",
  },
  noteSave: {
    alignSelf: "flex-end",
    background: "var(--lmd-ink)",
    color: "var(--lmd-panel)",
    border: "1px solid var(--lmd-ink)",
    borderRadius: 8,
    padding: "7px 14px",
    fontSize: 12.5,
    fontWeight: 600,
    cursor: "pointer",
    fontFamily: FONT,
  },
  notesPanel: { marginTop: 18, borderTop: `1px solid ${T.border}`, paddingTop: 14 },
  notesItem: { padding: "8px 0", borderBottom: `1px solid ${T.border}` },
  notesMeta: { fontSize: 11, color: T.faint, display: "flex", gap: 8, marginBottom: 3 },
  rosterBar: {
    display: "flex",
    alignItems: "center",
    gap: 8,
    padding: "10px 28px",
    borderBottom: `1px solid ${T.border}`,
    flexWrap: "wrap",
    background: T.panel,
    flexShrink: 0,
  },
  rchip: {
    display: "inline-flex",
    alignItems: "center",
    gap: 7,
    background: T.bg,
    border: `1px solid ${T.border}`,
    borderRadius: 8,
    padding: "5px 6px 5px 11px",
    fontSize: 12.5,
    fontFamily: MONO,
    color: T.ink,
    cursor: "pointer",
  },
  rx: {
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    border: "none",
    background: "transparent",
    color: T.faint,
    cursor: "pointer",
    lineHeight: 1,
    padding: "0 2px",
  },

  main: { display: "flex", flex: 1, minHeight: 0 }, // two-pane shell
  board: { flex: 1, minWidth: 0 },
  grid: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fill, minmax(min(100%, 280px), 1fr))",
    gap: 14,
    alignContent: "start",
  },

  box: (accent) => ({
    background: T.panel,
    border: `1px solid ${T.border}`,
    borderRadius: 12,
    padding: "18px",
    cursor: "pointer",
    position: "relative",
    transition: "transform .08s, border-color .12s",
  }),
  boxHead: { display: "flex", alignItems: "center", gap: 8, marginBottom: 4 },
  sid: {
    fontFamily: MONO,
    fontSize: 15,
    fontWeight: 700,
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  stateBadge: (c) => ({
    marginLeft: "auto",
    display: "inline-flex",
    alignItems: "center",
    gap: 6,
    background: "var(--lmd-track)",
    color: `var(--lmd-signal-${c.slice(1)}, ${c})`,
    border: "1px solid var(--lmd-border)",
    borderRadius: 6,
    padding: "3px 9px",
    fontSize: 10.5,
    fontWeight: 700,
    letterSpacing: 0.5,
    textTransform: "uppercase",
    whiteSpace: "nowrap",
  }),
  stateDot: (c) => ({ width: 6, height: 6, borderRadius: "50%", background: c, flexShrink: 0 }),
  miniLbl: {
    fontFamily: HEADFONT,
    fontSize: 11,
    fontWeight: 700,
    letterSpacing: 1,
    color: T.faint,
    textTransform: "uppercase",
    margin: "11px 0 5px",
  },
  metaRow: {
    display: "flex",
    justifyContent: "space-between",
    marginTop: 12,
    fontSize: 12,
    color: T.sub,
    fontVariantNumeric: "tabular-nums",
  },

  col: {
    flexShrink: 0,
    borderLeft: `1px solid ${T.border}`,
    background: T.panel,
    overflow: "auto",
  },
  colHead: {
    fontFamily: HEADFONT,
    fontSize: 12.5,
    fontWeight: 700,
    letterSpacing: 0.5,
    color: T.ink,
    textTransform: "uppercase",
    display: "flex",
    alignItems: "center",
    gap: 8,
    marginBottom: 16,
  },
  colCount: (c) => ({
    marginLeft: "auto",
    background: "var(--lmd-track)",
    color: `var(--lmd-signal-${c.slice(1)}, ${c})`,
    border: "1px solid var(--lmd-border)",
    borderRadius: 6,
    padding: "1px 8px",
    fontSize: 12,
    fontWeight: 700,
    fontVariantNumeric: "tabular-nums",
  }),
  colItem: (c) => ({
    background: T.bg,
    border: `1px solid ${c}40`,
    borderRadius: 10,
    padding: "11px 13px",
    marginBottom: 10,
    cursor: "pointer",
    position: "relative",
  }),
  colSid: { fontFamily: MONO, fontWeight: 700, fontSize: 14 },
  colSub: (c) => ({
    fontSize: 12,
    color: `var(--lmd-signal-${c.slice(1)}, ${c})`,
    marginTop: 4,
    display: "flex",
    alignItems: "center",
    gap: 6,
  }),
  colEmpty: { color: T.sub, fontSize: 13, lineHeight: 1.5 },
  ackBtn: {
    marginLeft: "auto",
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    background: "transparent",
    border: `1px solid ${T.border}`,
    color: T.faint,
    borderRadius: 8,
    padding: "5px",
    cursor: "pointer",
    fontFamily: FONT,
  },
  switchHead: {
    fontFamily: HEADFONT,
    fontSize: 12.5,
    fontWeight: 700,
    letterSpacing: 0.5,
    color: T.ink,
    textTransform: "uppercase",
    display: "flex",
    alignItems: "center",
    gap: 8,
    margin: "24px 0 14px",
    paddingTop: 18,
    borderTop: `1px solid ${T.border}`,
  },
  toastWrap: {
    position: "fixed",
    top: 72,
    right: 24,
    display: "flex",
    flexDirection: "column",
    gap: 10,
    zIndex: 60,
    alignItems: "flex-end",
    pointerEvents: "none",
  },
  toast: {
    display: "flex",
    alignItems: "center",
    gap: 11,
    minWidth: 250,
    maxWidth: "92vw",
    background: T.panel,
    border: `1px solid ${T.border}`,
    borderRadius: 10,
    padding: "11px 13px",
    boxShadow: "0 12px 30px rgba(15, 23, 42, 0.22)",
    animation: "toastIn .3s cubic-bezier(.2,.8,.25,1)",
    pointerEvents: "auto",
  },
  toastIcon: {
    flexShrink: 0,
    width: 30,
    height: 30,
    borderRadius: 8,
    background: "var(--lmd-track)",
    border: `1px solid ${T.border}`,
    color: "var(--lmd-warning)",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
  },
  toastBody: { display: "flex", flexDirection: "column", gap: 2, lineHeight: 1.25 },
  toastTitle: { fontFamily: MONO, fontSize: 13.5, fontWeight: 700, color: T.ink },
  toastSub: { fontSize: 11.5, color: T.sub, whiteSpace: "nowrap" },
  toastArrow: { fontFamily: MONO },
  toastClose: {
    flexShrink: 0,
    marginLeft: "auto",
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    border: "none",
    background: "transparent",
    color: T.faint,
    lineHeight: 1,
    cursor: "pointer",
    fontFamily: FONT,
  },

  empty: { color: T.sub, fontSize: 14, textAlign: "center", marginTop: 60 },
  modal: {
    background: T.bg,
    border: `1px solid ${T.border}`,
    borderRadius: 16,
    width: "min(860px, 96vw)",
    maxHeight: "88vh",
    overflow: "auto",
    padding: 26,
    position: "relative",
    boxShadow: "0 20px 60px rgba(0,0,0,0.5)",
  },
  modalX: {
    position: "absolute",
    top: 14,
    right: 16,
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    border: `1px solid ${T.border}`,
    borderRadius: 8,
    padding: 6,
    background: "transparent",
    color: T.sub,
    cursor: "pointer",
  },
};

// The notes list plus a composer, shown at the bottom of the detail modal.
const NotesPanel = ({ notes, onAdd }) => {
  const [draft, setDraft] = React.useState("");
  const save = () => {
    const t = draft.trim();
    if (!t) return;
    onAdd(t);
    setDraft("");
  };
  return (
    <div style={S.notesPanel}>
      <div style={S.miniLbl}>Notes &amp; observations ({notes.length})</div>
      {notes.length === 0 && (
        <div style={{ color: T.faint, fontSize: 12.5, padding: "6px 0" }}>No notes yet.</div>
      )}
      {notes.map((n) => (
        <div key={n.id} style={S.notesItem}>
          <div style={S.notesMeta}>
            <span>{n.ts}</span>
            {n.trigger_type && (
              <span style={{ color: "var(--lmd-accent)" }}>| during {n.trigger_type}</span>
            )}
          </div>
          <div style={{ fontSize: 13, color: T.ink, whiteSpace: "pre-wrap" }}>{n.text}</div>
        </div>
      ))}
      <div style={{ display: "flex", flexDirection: "column", gap: 6, marginTop: 10 }}>
        <textarea
          style={S.noteArea}
          value={draft}
          placeholder="Add a manual note..."
          onChange={(e) => setDraft(e.target.value)}
        />
        <button style={S.noteSave} onClick={save}>
          Add Notes
        </button>
      </div>
    </div>
  );
};

// The top-level component: holds all the polled state and wires up every
// action. Each data source has its own fetch callback on the shared POLL_MS
// timer so the views stay current without a single giant request.
const CohortDashboard = () => {
  const detailDialog = React.useRef(null);
  const [states, setStates] = React.useState({}); // studentID -> light payload (grid)
  const [detailFull, setDetailFull] = React.useState(null); // heavy payload for the open student
  const [roster, setRoster] = React.useState([]);
  const [triggers, setTriggers] = React.useState([]); // backend-fired alerts
  const [switches, setSwitches] = React.useState([]); // identity-switch feed
  const [toasts, setToasts] = React.useState([]); // transient switch popups
  const [selected, setSelected] = React.useState(null);
  const [query, setQuery] = React.useState("");
  const [pollingOn, setPollingOn] = React.useState(true); // daemon prod polling
  const [notes, setNotes] = React.useState([]); // notes for `selected`
  const [noteOpen, setNoteOpen] = React.useState(null); // trigger id with an open editor
  const [noteText, setNoteText] = React.useState("");
  React.useEffect(() => {
    if (selected && detailDialog.current && !detailDialog.current.open) {
      const opener = document.activeElement;
      detailDialog.current.showModal();
      return () => {
        if (opener instanceof HTMLElement && opener.isConnected) opener.focus();
      };
    }
  }, [selected]);
  const [triggerCfg, setTriggerCfg] = React.useState({
    wheel_spin: true,
    resilience: true,
    inactive: true,
    explorer: true,
    iterative: true,
  });
  const [triggerPanel, setTriggerPanel] = React.useState(false);
  // Light (INVITE brand) or dark (the dashboard's original look); persisted
  // per-browser like boardId(). No stored preference -> follow the OS.
  const [theme, setTheme] = React.useState(() => {
    try {
      return (
        localStorage.getItem(THEME_KEY) ||
        (window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light")
      );
    } catch {
      return "light";
    }
  });
  React.useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem(THEME_KEY, theme);
    } catch {
      /* ignore */
    }
  }, [theme]);
  const visible = usePageVisible(); // gates every poll loop below; hidden tab -> no polling

  const fetchStates = React.useCallback(async () => {
    try {
      const list = (await api.get("/api/student_states/")).data.students || [];
      const m = {};
      list.forEach((s) => {
        m[s.studentID] = s;
      });
      setStates(m);
    } catch {
      /* keep */
    }
  }, []);

  const fetchRoster = React.useCallback(async () => {
    try {
      setRoster((await api.get("/api/tracked/")).data.tracked || []);
    } catch {
      /* keep */
    }
  }, []);

  const fetchTriggers = React.useCallback(async () => {
    try {
      setTriggers((await api.get("/api/triggers/")).data.triggers || []);
    } catch {
      /* keep */
    }
  }, []);

  const fetchSwitches = React.useCallback(async () => {
    try {
      setSwitches((await api.get("/api/switches/")).data.switches || []);
    } catch {
      /* keep */
    }
  }, []);

  // Refetch only the channels the stream says moved. The map keeps SSE-driven
  // refetches and the fallback poll loops using the exact same fetch callbacks.
  const onStreamChanged = React.useCallback(
    (channels) => {
      if (channels.includes("states")) fetchStates();
      if (channels.includes("roster")) fetchRoster();
      if (channels.includes("triggers")) fetchTriggers();
      if (channels.includes("switches")) fetchSwitches();
    },
    [fetchStates, fetchRoster, fetchTriggers, fetchSwitches],
  );
  // One stream when it's available; otherwise the four timers below. Gating the
  // polls on `!streaming` means exactly one mechanism is live at a time, and a
  // dropped stream silently falls back to polling until it reconnects.
  const streaming = useEventStream(onStreamChanged, visible);
  usePoll(fetchStates, visible && !streaming);
  usePoll(fetchRoster, visible && !streaming);
  usePoll(fetchTriggers, visible && !streaming);
  usePoll(fetchSwitches, visible && !streaming);

  // Most-recent casing for a handle, looked up from the materialized state
  // (the feed itself carries the canonical id, used as the fallback).
  const displayFor = (sid) => (states[sid] && states[sid].display) || sid;

  // Pop a toast for each NEW unacked switch. The first load only seeds the
  // "seen" set (so opening the board doesn't flood you with the backlog);
  // after that a fresh switch toasts and auto-dismisses after 6s.
  const seenSwitch = React.useRef(new Set());
  const firstSwitchLoad = React.useRef(true);
  React.useEffect(() => {
    const fresh = switches.filter((s) => !s.acknowledged && !seenSwitch.current.has(s.id));
    fresh.forEach((s) => seenSwitch.current.add(s.id));
    if (firstSwitchLoad.current) {
      firstSwitchLoad.current = false;
      return;
    }
    if (!fresh.length) return;
    const add = fresh.map((s) => ({
      id: s.id,
      title: displayFor(s.studentID),
      kind: s.kind,
      from: s.from,
      to: s.to,
    }));
    setToasts((t) => [...t, ...add]);
    add.forEach((a) => setTimeout(() => setToasts((t) => t.filter((x) => x.id !== a.id)), 6000));
  }, [switches]); // eslint-disable-line react-hooks/exhaustive-deps

  // ------------------------------------------------------------------
  // Resilient writes. Every researcher input goes through submitWrite: try,
  // retry twice with a short backoff, and only then fail LOUD -- park the
  // original payload in the server-side outbox (or localStorage if the API
  // itself is unreachable) and raise a sticky red toast naming the action.
  // The error is rethrown so each caller's catch can still reconcile its
  // optimistic UI against server truth. Nothing typed or clicked is ever
  // silently dropped.
  const WRITE_RETRIES = 2,
    WRITE_RETRY_MS = 250,
    LS_OUTBOX = "lmdOutbox";
  const errSeq = React.useRef(0);
  const failLoud = React.useCallback((op, payload, err) => {
    const error = err?.message || "request failed";
    api.post("/api/outbox/", { op, payload, error }).catch(() => {
      // API unreachable: last-resort parking in the browser, flushed to
      // the server-side outbox when the stream reconnects.
      try {
        const q = JSON.parse(window.localStorage.getItem(LS_OUTBOX) || "[]");
        q.push({ op, payload, error, ts: Date.now() });
        window.localStorage.setItem(LS_OUTBOX, JSON.stringify(q));
      } catch {
        /* storage blocked: the toast below still fires */
      }
    });
    setToasts((t) => [
      ...t,
      { id: `err-${++errSeq.current}`, error: true, title: "NOT saved", sub: op },
    ]);
  }, []);
  const submitWrite = async (op, payload, post) => {
    for (let attempt = 0; ; attempt++) {
      try {
        return await post();
      } catch (e) {
        if (attempt >= WRITE_RETRIES) {
          failLoud(op, payload, e);
          throw e;
        }
        await new Promise((r) => setTimeout(r, WRITE_RETRY_MS * (attempt + 1)));
      }
    }
  };
  // Drain browser-parked failures into the server outbox once it's reachable
  // again (stream connect is the "API is back" signal).
  React.useEffect(() => {
    if (!streaming) return;
    let q = [];
    try {
      q = JSON.parse(window.localStorage.getItem(LS_OUTBOX) || "[]");
    } catch {
      return;
    }
    if (!q.length) return;
    window.localStorage.removeItem(LS_OUTBOX);
    q.forEach((item) =>
      api.post("/api/outbox/", item).catch(() => {
        // Still failing: put it back rather than lose it.
        try {
          const back = JSON.parse(window.localStorage.getItem(LS_OUTBOX) || "[]");
          back.push(item);
          window.localStorage.setItem(LS_OUTBOX, JSON.stringify(back));
        } catch {
          /* keep */
        }
      }),
    );
  }, [streaming]); // eslint-disable-line react-hooks/exhaustive-deps

  const ackSwitch = async (id) => {
    setSwitches((ss) => ss.filter((s) => s.id !== id));
    setToasts((t) => t.filter((x) => x.id !== id));
    try {
      await submitWrite(`dismiss switch #${id}`, { id }, () =>
        api.post("/api/switches/ack/", { id }),
      );
    } catch {
      fetchSwitches();
    }
  };

  // Pause state and trigger-config are values ONLY the user changes here (the
  // daemon just reads them), so we do NOT poll them on a timer. Polling created
  // a race: a GET already in flight when you click resolves a moment later with
  // the pre-click value and flips the control back. We fetch each once on mount
  // and let the toggle be the source of truth afterward. No competing GET, no
  // flicker. (A second open dashboard won't auto-sync these two controls, which
  // is fine for a single-researcher session.)
  const fetchPolling = React.useCallback(async () => {
    try {
      setPollingOn((await api.get("/api/polling/")).data.enabled);
    } catch {
      /* keep */
    }
  }, []);
  React.useEffect(() => {
    fetchPolling();
  }, [fetchPolling]); // once, no interval
  const togglePolling = async () => {
    const next = !pollingOn;
    setPollingOn(next); // optimistic; the toggle owns this value
    try {
      const r = await submitWrite(`polling ${next ? "on" : "off"}`, { enabled: next }, () =>
        api.post("/api/polling/", { enabled: next }),
      );
      setPollingOn(r.data.enabled);
    } catch {
      fetchPolling();
    }
  };

  const fetchTriggerCfg = React.useCallback(async () => {
    try {
      setTriggerCfg((await api.get("/api/triggers/config/")).data.enabled);
    } catch {
      /* keep */
    }
  }, []);
  React.useEffect(() => {
    fetchTriggerCfg();
  }, [fetchTriggerCfg]); // once, no interval
  const toggleTrigger = async (type) => {
    const next = !triggerCfg[type];
    setTriggerCfg((c) => ({ ...c, [type]: next })); // optimistic
    const body = { trigger_type: type, enabled: next };
    try {
      const r = await submitWrite(`trigger ${type} ${next ? "on" : "off"}`, body, () =>
        api.post("/api/triggers/config/", body),
      );
      setTriggerCfg(r.data.enabled);
    } catch {
      fetchTriggerCfg();
    }
  };
  // Present / picked toggles for the interview workflow. Update the UI first,
  // then persist; because both live on tracked_student they show up in the CSV.
  const setPresence = async (sid, present) => {
    setRoster((rs) => rs.map((r) => (r.studentID === sid ? { ...r, present } : r)));
    const body = { studentID: sid, present };
    try {
      await submitWrite(`${present ? "present" : "absent"}: ${sid}`, body, () =>
        api.post("/api/presence/", body),
      );
    } catch {
      fetchRoster();
    }
  };
  // source is 'roster' (student card) or 'intervention' (alert card); the
  // intervention path also passes the trigger it was clicked from so the pick
  // log records which alert prompted it. Roster picks carry no trigger.
  const setPicked = async (sid, picked, source = "roster", trigger = null) => {
    setRoster((rs) => rs.map((r) => (r.studentID === sid ? { ...r, picked } : r)));
    const body = {
      studentID: sid,
      picked,
      source,
      trigger_id: trigger?.id ?? null,
      trigger_type: trigger?.trigger_type ?? null,
    };
    try {
      await submitWrite(`${picked ? "pick" : "unpick"}: ${sid}`, body, () =>
        api.post("/api/picked/", body),
      );
    } catch {
      fetchRoster();
    }
  };
  // Notes for whichever learner is currently open; reloaded when the modal
  // opens and after a note is added.
  const fetchNotes = React.useCallback(async (sid) => {
    if (!sid) {
      setNotes([]);
      return;
    }
    try {
      setNotes((await api.get("/api/notes/", { params: { studentID: sid } })).data.notes || []);
    } catch {
      setNotes([]);
    }
  }, []);
  React.useEffect(() => {
    fetchNotes(selected);
  }, [selected, fetchNotes]);

  // Trigger history for the open student's grid. Depending on `triggers` too
  // keeps the grid current while the modal is open: whenever the live feed
  // refetches (a new alert, an ack), the history follows on the same beat.
  const [history, setHistory] = React.useState([]);
  React.useEffect(() => {
    if (!selected) {
      setHistory([]);
      return undefined;
    }
    let alive = true;
    api
      .get("/api/triggers/history/", { params: { studentID: selected } })
      .then((r) => {
        if (alive) setHistory(r.data.history || []);
      })
      .catch(() => {
        if (alive) setHistory([]);
      });
    return () => {
      alive = false;
    };
  }, [selected, triggers]);

  // The heavy payload (playground prompt included) for just the open student,
  // fetched on open and re-fetched whenever the cohort states refresh -- so
  // under SSE it's event-driven (states only refreshes when something actually
  // changed) instead of re-shipping the largest payload on a blind timer.
  // Under the polling fallback, states updates each tick, which degrades this
  // to the old POLL_MS cadence automatically. `alive` discards a late response
  // that arrives after you've already switched to a different student.
  React.useEffect(() => {
    if (!selected) {
      setDetailFull(null);
      return;
    }
    if (!visible) return; // tab hidden: keep the open detail, just stop refreshing it
    let alive = true;
    (async () => {
      try {
        const d = (await api.get(`/api/student_states/${encodeURIComponent(selected)}/`)).data;
        if (alive) setDetailFull(d);
      } catch {
        if (alive) setDetailFull(null);
      }
    })();
    return () => {
      alive = false;
    };
  }, [selected, visible, states]);
  const addNote = async (sid, text, trigger) => {
    const t = (text || "").trim();
    if (!sid || !t) return;
    const body = { studentID: sid, text: t };
    if (trigger) {
      body.trigger_id = trigger.id;
      body.trigger_type = trigger.trigger_type;
    }
    // A typed note is the most irreplaceable input on the board; it either
    // lands or gets parked in the outbox with a red toast -- never dropped.
    try {
      await submitWrite(`note on ${sid}`, body, () => api.post("/api/notes/", body));
    } catch {
      /* parked in the outbox; the toast already said so */
    }
    if (sid === selected) fetchNotes(sid);
  };

  const ackTrigger = async (id) => {
    // Drop the row right away so the click feels instant, then persist.
    setTriggers((ts) => ts.filter((t) => t.id !== id));
    if (noteOpen === id) {
      setNoteOpen(null);
      setNoteText("");
    }
    try {
      await submitWrite(`dismiss alert #${id}`, { id }, () =>
        api.post("/api/triggers/ack/", { id }),
      );
    } catch {
      fetchTriggers();
    }
  };

  // Track one or many: split on ';', strip ALL whitespace from each id (ids
  // never contain spaces, so any whitespace is just noise), drop blanks, and
  // de-dupe. Each is added independently so one failure doesn't sink the rest.
  const addTracked = async () => {
    const ids = [
      ...new Set(
        query
          .split(";")
          .map((s) => s.replace(/\s/g, ""))
          .filter(Boolean),
      ),
    ];
    if (ids.length === 0) return;
    await Promise.all(
      ids.map((sid) =>
        submitWrite(`track: ${sid}`, { studentID: sid }, () =>
          api.post("/api/tracked/", { studentID: sid }),
        ).catch(() => {}),
      ),
    );
    setQuery("");
    fetchRoster();
  };
  const removeTracked = async (sid) => {
    const body = { studentID: sid, remove: true };
    try {
      await submitWrite(`untrack: ${sid}`, body, () => api.post("/api/tracked/", body));
    } catch {
      fetchRoster();
    }
    setRoster((r) => r.filter((x) => x.studentID !== sid));
    if (selected === sid) setSelected(null);
    fetchStates();
  };
  const exportData = async () => {
    try {
      // Ask for the response as a binary Blob (not parsed JSON) so we hand
      // the browser the raw zip. The filename comes from the server's
      // Content-Disposition header, with a fallback if it's missing.
      const res = await api.post("/api/export/", null, { responseType: "blob" });
      const name =
        res.headers["content-disposition"]?.match(/filename="(.+)"/)?.[1] ||
        "lm-dashboard_export.zip";
      triggerDownload(res.data, name);
    } catch {
      window.alert("Export failed.");
    }
  };
  const resetAll = async () => {
    if (
      !window.confirm(
        "Reset the board?\n\nThis clears every student's logs, episodes, triggers, flags, your notes & observations, AND the picked toggles + pick history. A CSV backup (notes and picks included) is saved to exports/ automatically first, so nothing is lost.\n\nStudents stay tracked and present/absent is kept; the board rebuilds from new activity. Local only, production is untouched.",
      )
    )
      return;
    try {
      const { data } = await api.post("/api/reset/");
      // Clear the local views at once so nothing lingers until the next
      // poll: the cards, the open detail, the notes, the open note editor,
      // AND the "Needs intervention" alerts (reset wiped trigger_event).
      setSelected(null);
      setStates({});
      setNotes([]);
      setTriggers([]);
      setSwitches([]);
      setToasts([]);
      setNoteOpen(null);
      setNoteText("");
      window.alert("Reset done. Backup saved to:\n" + (data.backup || "exports/"));
    } catch {
      window.alert("Reset failed, data was NOT cleared.");
    }
    fetchStates();
    fetchRoster();
    fetchTriggers();
  };

  // One card per tracked student, each merged with its materialized state.
  // Present students come first; within each group the order is stable (by
  // studentID) so a card never jumps when its own data refreshes. Deciding who
  // needs attention is the alert column's job, not the grid's.
  const boxes = roster
    .map((r) => ({
      studentID: r.studentID,
      display: r.display || r.studentID, // most-recent casing; canonical id stays the key
      has_data: r.has_data,
      present: r.present !== false, // default present for older roster payloads
      picked: !!r.picked,
      st: states[r.studentID] || null,
    }))
    // present students first, then stable by studentID so a card never jumps
    .sort((a, b) =>
      a.present === b.present ? a.studentID.localeCompare(b.studentID) : a.present ? -1 : 1,
    );

  // Keep the alert feed to currently-tracked, PRESENT students with the type
  // enabled. The backend evaluates every student_state row, so this filters out
  // alerts for someone just untracked (and any muted trigger type). Absent
  // students are suppressed too: a kid who left the room would otherwise spam
  // "inactive" alerts forever, sending a TA to an empty seat.
  //
  // We show active AND recently-resolved triggers: the backend keeps a resolved
  // one in the feed for TRIGGER_RECENT_SECONDS (2 min), so an alert lingers for
  // ~2 minutes after a student recovers rather than vanishing instantly.
  const tracked = new Set(roster.map((r) => r.studentID));
  const absent = new Set(roster.filter((r) => r.present === false).map((r) => r.studentID));
  const alerts = triggers.filter(
    (t) =>
      tracked.has(t.studentID) && !absent.has(t.studentID) && triggerCfg[t.trigger_type] !== false,
  );
  // Each student's headline = their highest-priority active trigger (the feed
  // already lingers a momentary alert ~2 min, so the badge persists briefly too).
  const statusBy = {};
  alerts.forEach((t) => {
    const cur = statusBy[t.studentID];
    if (cur == null || TRIGGER_PRIORITY.indexOf(t.trigger_type) < TRIGGER_PRIORITY.indexOf(cur))
      statusBy[t.studentID] = t.trigger_type;
  });
  const headColor = TRIGGERS.wheel_spin.c;
  const unackedSwitches = switches.filter((s) => !s.acknowledged);
  const detail = detailFull; // heavy payload fetched per-open student

  return (
    <div className="dashboard" style={S.page}>
      <header className="dashboard-header" style={S.bar}>
        <h1 style={{ ...S.title, margin: 0 }}>
          <span
            aria-hidden="true"
            style={{
              width: 8,
              height: 8,
              borderRadius: "50%",
              flexShrink: 0,
              background: pollingOn ? "var(--lmd-success)" : "var(--lmd-warning)",
            }}
          />
          Learner Modeling Dashboard
          {!pollingOn && (
            <span
              style={{
                fontSize: 11,
                fontWeight: 700,
                letterSpacing: 0.5,
                textTransform: "uppercase",
                color: "var(--lmd-warning)",
              }}
            >
              Daemon paused
            </span>
          )}
        </h1>
        <form
          className="track-form"
          onSubmit={(e) => {
            e.preventDefault();
            addTracked();
          }}
        >
          <input
            aria-label="Track student IDs"
            style={S.input}
            placeholder="Track student IDs"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <button className="track-submit" type="submit" disabled={!query.trim()}>
            Track
          </button>
        </form>
        <div className="dashboard-actions">
          <button
            style={pollingOn ? S.pollPause : S.pollResume}
            onClick={togglePolling}
            title={
              pollingOn
                ? "Pause the daemon: stop ALL polling of the production server. The board keeps showing the last data. No new events are fetched until you resume. Use this between sessions to stop loading prod."
                : "Polling is paused. The daemon is making no requests to production. Click to resume fetching new events."
            }
          >
            {pollingOn ? (
              <>
                <Icon name="pause" />
                <span>Pause polling</span>
              </>
            ) : (
              <>
                <Icon name="play" />
                <span>Resume polling</span>
              </>
            )}
          </button>
          <button
            className="secondary-action reset-action"
            style={S.reset}
            onClick={resetAll}
            title="Wipe all student data with NO backup. Export first if you want a copy."
          >
            <Icon name="reset" />
            <span>Reset</span>
          </button>
          <button
            className="secondary-action"
            style={S.export}
            onClick={exportData}
            title="Download a zip of CSV snapshots of all data"
          >
            <Icon name="download" />
            <span>Export</span>
          </button>
          <button
            aria-expanded={triggerPanel}
            style={S.triggersBtn}
            onClick={() => setTriggerPanel((p) => !p)}
            title="Turn trigger types on or off"
          >
            <Icon name="sliders" />
            <span>Triggers</span>
          </button>
          <button
            style={S.themeToggle}
            onClick={() => setTheme((t) => (t === "dark" ? "light" : "dark"))}
            title={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
          >
            <Icon name={theme === "dark" ? "sun" : "moon"} size={17} />
          </button>
        </div>
      </header>

      {triggerPanel && (
        <div style={S.popOverlay} onClick={() => setTriggerPanel(false)}>
          <div style={S.popPanel} onClick={(e) => e.stopPropagation()}>
            <div style={S.popTitle}>Triggers</div>
            {TRIGGER_ROWS.map(([type, label]) => {
              const on = triggerCfg[type] !== false;
              return (
                <div key={type} style={S.popRow}>
                  <span>{label}</span>
                  <button style={on ? S.tgOn : S.tgOff} onClick={() => toggleTrigger(type)}>
                    {on ? "On" : "Off"}
                  </button>
                </div>
              );
            })}
          </div>
        </div>
      )}

      <div className="roster-bar" style={S.rosterBar}>
        <span style={{ fontSize: 12, color: T.sub, fontWeight: 700 }}>
          Tracking {roster.length}:
        </span>
        {roster.length === 0 && (
          <span style={{ fontSize: 12.5, color: T.faint }}>Add Student ID to Start Tracking</span>
        )}
        {roster.map((r) => (
          <span
            key={r.studentID}
            style={S.rchip}
            onClick={() => setSelected(r.studentID)}
            title="Open"
          >
            <span
              style={{
                width: 6,
                height: 6,
                borderRadius: "50%",
                flexShrink: 0,
                background: r.has_data ? "var(--lmd-success)" : "var(--lmd-warning)",
              }}
            />
            <button className="student-open" onClick={() => setSelected(r.studentID)}>
              {r.display || r.studentID}
            </button>
            <button
              style={S.rx}
              title="Stop tracking"
              onClick={(e) => {
                e.stopPropagation();
                removeTracked(r.studentID);
              }}
            >
              <Icon name="close" size={15} />
            </button>
          </span>
        ))}
      </div>

      <main className="dashboard-main" style={S.main}>
        {/* left: a box per tracked student */}
        <section className="student-board" aria-label="Students" style={S.board}>
          <div className="board-heading">
            <h2>Students</h2>
            <a className="feed-jump" href="#interventions">
              View alerts ({alerts.length})
            </a>
            <span>
              {boxes.filter((b) => b.present).length} present |{" "}
              {boxes.filter((b) => b.picked).length} picked
            </span>
          </div>
          {boxes.length === 0 ? (
            <div className="board-empty" style={S.empty}>
              <h3>Start with your first student</h3>
              <p>No students added yet. Enter student IDs up top to start.</p>
              <button
                className="empty-action"
                onClick={() => document.querySelector(".track-form input").focus()}
              >
                Track a student
              </button>
            </div>
          ) : (
            <div style={S.grid}>
              {boxes.map((b) => {
                const sm = statusMeta(statusBy[b.studentID], !!b.st);
                const accent = sm.c;
                return (
                  <div
                    key={b.studentID}
                    className="student-card"
                    style={{ ...S.box(accent), opacity: b.present ? 1 : 0.5 }}
                    onClick={() => setSelected(b.studentID)}
                  >
                    <div style={S.boxHead}>
                      <button
                        className="student-open"
                        style={S.sid}
                        title={b.display}
                        onClick={() => setSelected(b.studentID)}
                      >
                        {b.display}
                      </button>
                      <span style={S.stateBadge(accent)}>
                        <span style={S.stateDot(accent)} />
                        {sm.label}
                      </span>
                    </div>
                    {b.st ? (
                      <>
                        <div style={S.miniLbl}>Runs</div>
                        <RunTrack data={b.st.runs} compact />
                        <div style={S.miniLbl}>Episodes</div>
                        <EpisodeTrack data={b.st.episodes} compact />
                        <div style={S.metaRow}>
                          <span>
                            {b.st.run_count} runs | {b.st.event_count} events
                          </span>
                          <span>{relTime(b.st.last_seen)}</span>
                        </div>
                      </>
                    ) : (
                      <div style={{ color: T.faint, fontSize: 12.5, padding: "16px 0 8px" }}>
                        {b.has_data ? "Loading..." : "Waiting for activity..."}
                      </div>
                    )}
                    <div style={S.toggleRow}>
                      <button
                        aria-pressed={b.present}
                        style={
                          b.present
                            ? {
                                ...S.tgBtn,
                                background: "var(--lmd-track)",
                                color: "var(--lmd-success)",
                              }
                            : S.tgBtn
                        }
                        onClick={(e) => {
                          e.stopPropagation();
                          setPresence(b.studentID, !b.present);
                        }}
                        title={
                          b.present ? "Mark absent (drops to the bottom, dimmed)" : "Mark present"
                        }
                      >
                        <span style={S.presDot(b.present)} />
                        <span>{b.present ? "Present" : "Absent"}</span>
                      </button>
                      <button
                        aria-pressed={b.picked}
                        style={
                          b.picked
                            ? {
                                ...S.tgBtn,
                                background: "var(--lmd-track)",
                                color: "var(--lmd-purple)",
                              }
                            : S.tgBtn
                        }
                        onClick={(e) => {
                          e.stopPropagation();
                          setPicked(b.studentID, !b.picked, "roster");
                        }}
                        title={
                          b.picked
                            ? "Picked / interviewed - click to unmark"
                            : "Mark as picked / interviewed"
                        }
                      >
                        {b.picked && <Icon name="check" size={14} />}
                        <span>{b.picked ? "Picked" : "Mark picked"}</span>
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </section>

        {/* right: backend-fired alerts (the five edit-distance / idle triggers) */}
        <aside
          id="interventions"
          className="intervention-feed"
          aria-label="Needs intervention"
          style={S.col}
        >
          <div style={S.colHead}>
            <Icon
              name={TRIGGERS.wheel_spin.icon}
              size={16}
              style={{ color: `var(--lmd-signal-${headColor.slice(1)}, ${headColor})` }}
            />{" "}
            Needs intervention
            <span style={S.colCount(headColor)}>{alerts.length}</span>
          </div>
          {alerts.length === 0 ? (
            <div style={S.colEmpty}>No active alerts right now.</div>
          ) : (
            alerts.map((t) => {
              const meta = triggerMeta(t.trigger_type);
              return (
                <div key={t.id} style={S.colItem(meta.c)} onClick={() => setSelected(t.studentID)}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <button
                      className="student-open"
                      style={S.colSid}
                      onClick={() => setSelected(t.studentID)}
                    >
                      {displayFor(t.studentID)}
                    </button>
                    {(() => {
                      const picked = !!(roster.find((r) => r.studentID === t.studentID) || {})
                        .picked;
                      return (
                        <button
                          style={
                            picked
                              ? {
                                  ...S.tgBtn,
                                  background: "var(--lmd-track)",
                                  color: "var(--lmd-purple)",
                                }
                              : S.tgBtn
                          }
                          title={
                            picked
                              ? "Picked / interviewed - click to unmark"
                              : "Mark as picked / interviewed"
                          }
                          onClick={(e) => {
                            e.stopPropagation();
                            setPicked(t.studentID, !picked, "intervention", t);
                          }}
                        >
                          {picked && <Icon name="check" size={14} />}
                          <span>Picked</span>
                        </button>
                      );
                    })()}
                    <button
                      style={{ ...S.tgBtn, color: "var(--lmd-accent)" }}
                      title="Add a note for this learner"
                      onClick={(e) => {
                        e.stopPropagation();
                        setNoteText("");
                        setNoteOpen(noteOpen === t.id ? null : t.id);
                      }}
                    >
                      Notes
                    </button>
                    <button
                      style={S.ackBtn}
                      title="Dismiss alert (also closes the note box)"
                      onClick={(e) => {
                        e.stopPropagation();
                        ackTrigger(t.id);
                      }}
                    >
                      <Icon name="close" size={15} />
                    </button>
                  </div>
                  {noteOpen === t.id && (
                    <div style={S.noteEditor} onClick={(e) => e.stopPropagation()}>
                      <textarea
                        style={S.noteArea}
                        value={noteText}
                        autoFocus
                        placeholder="Observation during this alert..."
                        onChange={(e) => setNoteText(e.target.value)}
                      />
                      <button
                        style={S.noteSave}
                        onClick={() => {
                          addNote(t.studentID, noteText, t);
                          setNoteOpen(null);
                          setNoteText("");
                        }}
                      >
                        Save note
                      </button>
                    </div>
                  )}
                  <div style={S.colSub(meta.c)}>
                    <Icon name={meta.icon} size={14} />
                    <span>
                      {t.label || meta.label}
                      {t.value ? ` | ${t.value}` : ""}
                    </span>
                    <span
                      style={{
                        marginLeft: "auto",
                        color: T.faint,
                        fontVariantNumeric: "tabular-nums",
                      }}
                    >
                      {t.age_seconds != null ? fmtDur(t.age_seconds) : "-"}
                    </span>
                  </div>
                  {t.prev && (
                    <div style={{ fontSize: 11, color: T.faint, marginTop: 3 }}>
                      last:{" "}
                      <Icon
                        name={triggerMeta(t.prev.trigger_type).icon}
                        size={12}
                        style={{ display: "inline-block", verticalAlign: "-2px" }}
                      />{" "}
                      {t.prev.label}
                      {" | "}
                      {clockTime(t.prev.at)} ({relTime(t.prev.at)} ago)
                    </div>
                  )}
                </div>
              );
            })
          )}

          {unackedSwitches.length > 0 && (
            <>
              <div style={S.switchHead}>
                <Icon name="swap" size={16} style={{ color: "var(--lmd-warning)" }} />
                Identity switches
                <span style={S.colCount("#f59e0b")}>{unackedSwitches.length}</span>
              </div>
              {unackedSwitches.map((s) => (
                <div
                  key={s.id}
                  style={S.colItem("#eab308")}
                  onClick={() => setSelected(s.studentID)}
                >
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <button
                      className="student-open"
                      style={S.colSid}
                      onClick={() => setSelected(s.studentID)}
                    >
                      {displayFor(s.studentID)}
                    </button>
                    <button
                      style={S.ackBtn}
                      title="Dismiss switch"
                      onClick={(e) => {
                        e.stopPropagation();
                        ackSwitch(s.id);
                      }}
                    >
                      <Icon name="close" size={15} />
                    </button>
                  </div>
                  <div style={S.colSub("#eab308")}>
                    {s.kind === "casing"
                      ? `casing | ${s.from} -> ${s.to}`
                      : `new class | ${s.from || "-"} -> ${s.to}`}
                    <span style={{ marginLeft: "auto", color: T.faint }}>{relTime(s.ts)}</span>
                  </div>
                </div>
              ))}
            </>
          )}
        </aside>
      </main>

      {toasts.length > 0 && (
        <div style={S.toastWrap}>
          {toasts.map((t) => (
            // Two flavors share the card: amber switch toasts
            // (auto-dismiss) and red failed-write toasts, which are
            // sticky -- an error that vanishes on its own isn't loud.
            <div
              key={t.id}
              style={t.error ? { ...S.toast, borderColor: "var(--lmd-signal-ef4444)" } : S.toast}
            >
              <div
                style={
                  t.error ? { ...S.toastIcon, color: "var(--lmd-signal-ef4444)" } : S.toastIcon
                }
              >
                <Icon name={t.error ? "alert" : "swap"} size={16} />
              </div>
              <div style={S.toastBody}>
                <span style={t.error ? { ...S.toastTitle, color: "#ef4444" } : S.toastTitle}>
                  {t.title}
                </span>
                <span style={S.toastSub}>
                  {t.error ? (
                    t.sub
                  ) : (
                    <>
                      {t.kind === "casing" ? "casing changed" : "new class"}
                      {"  "}
                      <span style={{ ...S.toastArrow, color: T.faint }}>{t.from}</span>
                      <span style={S.toastArrow}>{" -> "}</span>
                      <span style={{ ...S.toastArrow, color: "#eab308" }}>{t.to}</span>
                    </>
                  )}
                </span>
              </div>
              <button
                style={S.toastClose}
                title="Dismiss"
                onClick={() => setToasts((ts) => ts.filter((x) => x.id !== t.id))}
              >
                <Icon name="close" size={16} />
              </button>
            </div>
          ))}
        </div>
      )}

      {selected && (
        <dialog
          ref={detailDialog}
          className="student-dialog"
          aria-label={`Student details: ${selected}`}
          onCancel={() => setSelected(null)}
          onClick={(e) => {
            if (e.target === e.currentTarget) setSelected(null);
          }}
        >
          <div className="student-detail" style={S.modal}>
            <button
              aria-label="Close student details"
              autoFocus
              style={S.modalX}
              onClick={() => setSelected(null)}
            >
              <Icon name="close" size={18} />
            </button>
            <Detail
              s={detail}
              sid={selected}
              status={statusMeta(statusBy[selected], !!detail)}
              history={history}
            />
            <NotesPanel notes={notes} onAdd={(text) => addNote(selected, text, null)} />
          </div>
        </dialog>
      )}
    </div>
  );
};

export default CohortDashboard;
