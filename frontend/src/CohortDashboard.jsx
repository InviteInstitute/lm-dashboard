// The dashboard: the board, the alert column, and the student sheet. The goal
// evidence panel inside the sheet lives in ./GoalEvidence.
//
// It follows the read API's live stream (with a polling fallback) and renders three things from what it
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
  toneVars,
} from "./constants";
import { GoalEvidence } from "./GoalEvidence";
import { Section } from "./Section";

const THEME_KEY = "lm_theme";

// Re-exported so existing imports/tests that pull these from the component file
// keep working; the source of truth is ./constants.
export { COMPACT_TAIL } from "./constants";

const triggerMeta = (type) => TRIGGERS[type] || TRIGGER_FALLBACK;

// Parse a server timestamp. Most API times are ISO with an offset, but notes and
// identity switches come straight from the DB as UTC with no zone
// ("2026-09-25 01:57:18.055110"), which `new Date` would read as local time.
export function parseTs(ts) {
  if (!ts) return null;
  const bare = /^(\d{4}-\d\d-\d\d)[ T](\d\d:\d\d:\d\d)(\.\d+)?$/.exec(ts);
  const d = bare
    ? new Date(`${bare[1]}T${bare[2]}${bare[3] ? bare[3].slice(0, 4) : ""}Z`)
    : new Date(ts);
  return Number.isNaN(d.getTime()) ? null : d;
}

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
// Wall-clock time for "at what time did that fire" readouts (alert prev-line,
// trigger-history grid). Locale-aware, e.g. "10:24 AM".
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
      title: `Run #${(run.index ?? i + off) + 1} | ${d == null ? "first run" : `edit distance ${d}`}`,
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
            No Change
          </span>
          <span>
            <i style={sw(ED_SMALL)} />
            Edit
          </span>
          <span>
            <i style={sw(ED_BIG)} />
            Big Change (&gt;=13)
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
  marginTop: 8,
  fontSize: 12,
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

// ---------------- detail (side sheet) ----------------
// The drill-down for one student, opened as a sheet over the right of the board
// so the cohort stays in view. Sticky header (id, status, counts, close), then
// two columns: the evidence (activity strips, code, goal evidence) on the left,
// and the researcher's own record (notes, trigger history) in a rail on the right.

const StatusBadge = ({ status }) => (
  <span
    style={{
      display: "inline-flex",
      alignItems: "center",
      gap: 7,
      color: `var(--lmd-signal-${status.c.slice(1)}, ${status.c})`,
      border: "1px solid currentColor",
      borderRadius: 6,
      padding: "3px 10px",
      fontSize: 13,
      fontWeight: 600,
      whiteSpace: "nowrap",
    }}
  >
    <span
      style={{ width: 7, height: 7, borderRadius: "50%", background: status.c, flexShrink: 0 }}
    />
    {status.label}
  </span>
);

// The student's latest program, in two renderings of the same blocks behind a
// switch: a readable listing, and the compact prompt text handed to an LLM
// (context only; the triggers do not use an LLM).
const CODE_VIEWS = [
  {
    key: "readable",
    label: "Readable",
    field: "readable",
    note: "Every block with its parameters spelled out.",
    empty: "No program yet.",
  },
  {
    key: "prompt",
    label: "LLM prompt",
    field: "llm_prompt",
    note: "The same program, flattened into the compact text given to an LLM as context.",
    empty: "No prompt yet: it is built once the student runs their program.",
  },
];
const CodePane = ({ block }) => {
  const [view, setView] = React.useState("readable");
  const cur = CODE_VIEWS.find((v) => v.key === view);
  const text = block && block[cur.field];
  return (
    <Section
      title="Latest Program"
      aside={
        <div className="sd-switch" role="tablist" aria-label="Program view">
          {CODE_VIEWS.map((v) => (
            <button
              key={v.key}
              type="button"
              role="tab"
              aria-selected={view === v.key}
              onClick={() => setView(v.key)}
            >
              {v.label}
            </button>
          ))}
        </div>
      }
    >
      <p className="sd-code-note">{cur.note}</p>
      {text ? (
        // the listing keeps its indentation (scrolls sideways); the prompt is one long line, so wrap it
        <pre className={view === "readable" ? "sd-code" : "sd-code sd-code-wrap"}>{text}</pre>
      ) : (
        <p className="sd-empty">{cur.empty}</p>
      )}
    </Section>
  );
};

// Newest trigger first; the label keeps its trigger colour, everything else is quiet.
const TriggerHistory = ({ history }) => (
  <Section
    title="Trigger History"
    aside={history.length > 0 && <span className="sd-count">{history.length}</span>}
  >
    {history.length === 0 ? (
      <p className="sd-empty">No triggers yet this session.</p>
    ) : (
      <ol className="sd-history">
        {history.map((h) => {
          const m = triggerMeta(h.trigger_type);
          const active = h.status === "active";
          return (
            <li key={h.id}>
              <span
                className="sd-history-label"
                style={{ color: `var(--lmd-signal-${m.c.slice(1)}, ${m.c})` }}
              >
                <Icon name={m.icon} size={14} />
                {h.label}
              </span>
              <time dateTime={h.started_at} title={h.started_at}>
                {clockTime(h.started_at)}
              </time>
              <span className="sd-history-value">{h.value || "-"}</span>
              <span
                className="sd-history-status"
                style={active ? { color: `var(--lmd-signal-${m.c.slice(1)}, ${m.c})` } : null}
              >
                {h.status}
              </span>
            </li>
          );
        })}
      </ol>
    )}
  </Section>
);

const Detail = ({ s, sid, status, loading, history = [], notes = [], onAddNote, onClose }) => {
  const cur = status || STATUS_OK;
  return (
    <>
      <header className="sd-head">
        <div className="sd-who">
          <h2 id="sd-title">{(s && s.display) || sid}</h2>
          {s && <StatusBadge status={cur} />}
        </div>
        {s && (
          <dl className="sd-facts">
            <div>
              <dt>runs</dt>
              <dd>{s.run_count ?? 0}</dd>
            </div>
            <div>
              <dt>events</dt>
              <dd>{s.event_count ?? 0}</dd>
            </div>
            {s.classCode && (
              <div>
                <dt>class</dt>
                <dd>{s.classCode}</dd>
              </div>
            )}
          </dl>
        )}
        <button
          type="button"
          className="sd-close"
          aria-label="Close student details"
          autoFocus
          onClick={onClose}
        >
          <Icon name="close" size={18} />
        </button>
      </header>
      <div className="sd-body">
        <div className="sd-main">
          {!s ? (
            <p className="sd-empty sd-empty-lead">
              {loading ? (
                "Loading activity..."
              ) : (
                <>
                  No activity yet for <b style={{ fontFamily: MONO }}>{sid}</b>. Notes can still be
                  added.
                </>
              )}
            </p>
          ) : (
            <>
              <Section title="Activity">
                <div className="sd-strips">
                  <span className="sd-strip-label">Episodes</span>
                  <div>
                    <EpisodeTrack data={s.episodes} />
                  </div>
                  <span className="sd-strip-label">Runs</span>
                  <div>
                    <RunTrack data={s.runs} />
                  </div>
                </div>
              </Section>
              {/* key by student so the code view and run pick reset when the sheet switches students */}
              <CodePane key={`code-${sid}`} block={s.block} />
              <GoalEvidence key={sid} runs={s.goal_runs} enabled={s.goal_recognition_enabled} />
            </>
          )}
        </div>
        <aside className="sd-rail">
          <NotesPanel key={sid} notes={notes} onAdd={onAddNote} />
          <TriggerHistory history={history} />
        </aside>
      </div>
    </>
  );
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
    boxShadow: "0 12px 32px -8px rgb(3 5 9 / 30%)",
    zIndex: 41,
  },
  popTitle: {
    fontSize: 14,
    fontWeight: 600,
    color: T.ink,
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
  main: { display: "flex", flex: 1, minHeight: 0 }, // two-pane shell
  board: { flex: 1, minWidth: 0 },
  toastWrap: {
    position: "fixed",
    bottom: 24,
    right: 24,
    display: "flex",
    gap: 10,
    zIndex: 60,
    alignItems: "flex-end",
    flexDirection: "column-reverse",
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
  toastTitle: { fontFamily: MONO, fontSize: 14, fontWeight: 600, color: T.ink },
  toastSub: { fontSize: 12, color: T.sub, whiteSpace: "nowrap" },
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
};

// The researcher's notes on this student: the composer first (it is the reason
// most people open the sheet), then the saved notes, newest first.
const NotesPanel = ({ notes, onAdd }) => {
  const [draft, setDraft] = React.useState("");
  const save = () => {
    const t = draft.trim();
    if (!t) return;
    onAdd(t);
    setDraft("");
  };
  return (
    <Section
      title="Notes"
      aside={notes.length > 0 && <span className="sd-count">{notes.length}</span>}
    >
      <div className="sd-composer">
        <textarea
          aria-label="New note"
          value={draft}
          placeholder="What did you see or hear?"
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
              e.preventDefault();
              save();
            }
          }}
        />
        <div className="sd-composer-foot">
          <span>Ctrl+Enter to save</span>
          <button type="button" onClick={save} disabled={!draft.trim()}>
            Save Note
          </button>
        </div>
      </div>
      {notes.length === 0 ? (
        <p className="sd-empty">No notes on this student yet.</p>
      ) : (
        <ol className="sd-notes">
          {[...notes].reverse().map((n) => (
            <li key={n.id}>
              <div className="sd-note-meta">
                <time dateTime={parseTs(n.ts)?.toISOString()} title={fullTime(n.ts)}>
                  {noteTime(n.ts)}
                </time>
                {n.trigger_type && <span>during {triggerMeta(n.trigger_type).label}</span>}
              </div>
              <p>{n.text}</p>
            </li>
          ))}
        </ol>
      )}
    </Section>
  );
};

// The top-level component: holds all the polled state and wires up every
// action. Each data source has its own fetch callback on the shared POLL_MS
// timer so the views stay current without a single giant request.
const CohortDashboard = () => {
  const detailDialog = React.useRef(null);
  const [states, setStates] = React.useState({}); // studentID -> light payload (grid)
  const [detailFull, setDetailFull] = React.useState(null); // heavy payload for the open student
  const [detailFor, setDetailFor] = React.useState(null); // student whose detail fetch last settled
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
      /* keep what's shown: a blip must not look like "no notes" */
    }
  }, []);
  React.useEffect(() => {
    setNotes([]); // a different student: never show the previous one's notes
    fetchNotes(selected);
  }, [selected, fetchNotes]);

  // Trigger history for the open student's grid. Depending on `triggers` too
  // keeps the grid current while the modal is open: whenever the live feed
  // refetches (a new alert, an ack), the history follows on the same beat.
  const [history, setHistory] = React.useState([]);
  React.useEffect(() => {
    setHistory([]); // a different student: never show the previous one's history
  }, [selected]);
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
        /* keep what's shown: a blip must not empty the grid */
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
  // Clear the previous student's heavy payload the instant the selection
  // changes, so switching students never shows the old detail (program, prompt,
  // goal evidence) until the new fetch lands. Keyed on `selected` only, so a
  // routine poll (states change) refreshes in place without blanking.
  React.useEffect(() => {
    setDetailFull(null);
  }, [selected]);
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
        /* keep the last good payload; the selection effect above already
           cleared it if this is a different student */
      }
      if (alive) setDetailFor(selected);
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
        "Reset the board?\n\nEvery student starts fresh on this board: runs, episodes, goal evidence, alerts, trigger history and switches from before now are hidden, and your notes, picks and pick history are cleared. A CSV backup (notes and picks included) is saved to exports/ first, so nothing is lost.\n\nStudents stay tracked and present/absent is kept. Other boards are not affected, and production is untouched.",
      )
    )
      return;
    try {
      const { data } = await api.post("/api/reset/");
      // Clear the local views at once so nothing lingers until the refetch
      // below: the cards, the open detail, the notes, the open note editor,
      // the alerts and the switches. The server now hides everything from
      // before the reset, so the refetch comes back fresh too.
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
    fetchSwitches();
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
  const unackedSwitches = switches.filter((s) => !s.acknowledged);
  const detail = detailFull; // heavy payload fetched per-open student

  return (
    <div className="dashboard" style={S.page}>
      <header className="dashboard-header">
        <div className="brand">
          <h1>Learner Modeling Dashboard</h1>
          <span
            className={pollingOn ? "live-state" : "live-state is-paused"}
            title={
              pollingOn
                ? "Fetching new activity from production"
                : "The daemon is making no requests to production"
            }
          >
            {pollingOn ? "Live" : "Polling paused"}
          </span>
        </div>
        <form
          className="track-form"
          onSubmit={(e) => {
            e.preventDefault();
            addTracked();
          }}
        >
          <input
            aria-label="Track student IDs"
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
            className="hdr-btn"
            onClick={togglePolling}
            title={
              pollingOn
                ? "Pause the daemon: stop ALL polling of the production server. The board keeps showing the last data. No new events are fetched until you resume. Use this between sessions to stop loading prod."
                : "Polling is paused. The daemon is making no requests to production. Click to resume fetching new events."
            }
          >
            <Icon name={pollingOn ? "pause" : "play"} />
            <span>{pollingOn ? "Pause Polling" : "Resume Polling"}</span>
          </button>
          <button
            className="hdr-btn"
            aria-expanded={triggerPanel}
            onClick={() => setTriggerPanel((p) => !p)}
            title="Turn trigger types on or off"
          >
            <Icon name="sliders" />
            <span>Triggers</span>
          </button>
          <button
            className="hdr-btn"
            onClick={exportData}
            title="Download a zip of CSV snapshots of all data"
          >
            <Icon name="download" />
            <span>Export</span>
          </button>
          <button
            className="hdr-btn hdr-danger"
            onClick={resetAll}
            title="Clear this board's session data. A CSV backup is saved first."
          >
            <Icon name="reset" />
            <span>Reset</span>
          </button>
          <span className="hdr-sep" aria-hidden="true" />
          <button
            className="hdr-btn hdr-icon"
            onClick={() => setTheme((t) => (t === "dark" ? "light" : "dark"))}
            title={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
            aria-label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
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

      <main className="dashboard-main" style={S.main}>
        {/* left: a box per tracked student */}
        <section className="student-board" aria-label="Students" style={S.board}>
          <div className="board-heading">
            <h2>Students</h2>
            <a className="feed-jump" href="#interventions">
              View Alerts ({alerts.length})
            </a>
            <span>
              {boxes.length} tracked, {boxes.filter((b) => b.present).length} present,{" "}
              {boxes.filter((b) => b.picked).length} picked
            </span>
          </div>
          {boxes.length === 0 ? (
            <div className="board-empty" style={S.empty}>
              <h3>Start with Your First Student</h3>
              <p>No students added yet. Enter student IDs up top to start.</p>
              <button
                className="empty-action"
                onClick={() => document.querySelector(".track-form input").focus()}
              >
                Track a Student
              </button>
            </div>
          ) : (
            <div className="student-grid">
              {boxes.map((b) => {
                const trig = statusBy[b.studentID];
                const sm = statusMeta(trig, !!b.st);
                return (
                  <article
                    key={b.studentID}
                    className={`student-card${trig ? " is-alert" : ""}${b.present ? "" : " is-absent"}`}
                    style={trig ? toneVars(sm.c) : undefined}
                    onClick={() => setSelected(b.studentID)}
                  >
                    <div className="card-head">
                      <button
                        className="student-open card-id"
                        title={b.display}
                        onClick={() => setSelected(b.studentID)}
                      >
                        {b.display}
                      </button>
                      <span className="card-status">
                        {trig && <Icon name={triggerMeta(trig).icon} size={14} />}
                        {sm.label}
                      </span>
                    </div>
                    {b.st ? (
                      <>
                        <div className="card-strips">
                          <span>Runs</span>
                          <RunTrack data={b.st.runs} compact />
                          <span>Episodes</span>
                          <EpisodeTrack data={b.st.episodes} compact />
                        </div>
                        <div className="card-meta">
                          <span>
                            {b.st.run_count} runs, {b.st.event_count} events
                          </span>
                          {b.st.last_seen && (
                            <span title={`Last activity ${clockTime(b.st.last_seen)}`}>
                              {relTime(b.st.last_seen)} ago
                            </span>
                          )}
                        </div>
                      </>
                    ) : (
                      <p className="card-wait">
                        {b.has_data ? "Loading..." : "Waiting for activity..."}
                      </p>
                    )}
                    <div className="card-actions">
                      <button
                        className="chip-btn"
                        aria-pressed={b.present}
                        onClick={(e) => {
                          e.stopPropagation();
                          setPresence(b.studentID, !b.present);
                        }}
                        title={
                          b.present ? "Mark absent (drops to the bottom, dimmed)" : "Mark present"
                        }
                      >
                        {b.present ? "Present" : "Absent"}
                      </button>
                      <button
                        className="chip-btn is-pick"
                        aria-pressed={b.picked}
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
                        <span>{b.picked ? "Picked" : "Mark Picked"}</span>
                      </button>
                      <button
                        className="icon-btn"
                        title="Stop tracking"
                        aria-label={`Stop tracking ${b.display}`}
                        onClick={(e) => {
                          e.stopPropagation();
                          removeTracked(b.studentID);
                        }}
                      >
                        <Icon name="close" size={15} />
                      </button>
                    </div>
                  </article>
                );
              })}
            </div>
          )}
        </section>

        {/* right: backend-fired alerts (the five edit-distance / idle triggers) */}
        <aside id="interventions" className="intervention-feed" aria-label="Needs Intervention">
          <div className="feed-head">
            <h2>Needs Intervention</h2>
            <span className="feed-count">{alerts.length}</span>
          </div>
          {alerts.length === 0 ? (
            <p className="feed-empty">No active alerts right now.</p>
          ) : (
            <ul className="feed-list">
              {alerts.map((t) => {
                const meta = triggerMeta(t.trigger_type);
                const picked = !!(roster.find((r) => r.studentID === t.studentID) || {}).picked;
                return (
                  <li
                    key={t.id}
                    className="feed-item"
                    style={toneVars(meta.c)}
                    onClick={() => setSelected(t.studentID)}
                  >
                    <div className="feed-row">
                      <button
                        className="student-open feed-id"
                        onClick={() => setSelected(t.studentID)}
                      >
                        {displayFor(t.studentID)}
                      </button>
                      <span className="feed-age" title="How long this alert has been active">
                        {t.age_seconds != null ? fmtDur(t.age_seconds) : "-"}
                      </span>
                    </div>
                    <div className="feed-what">
                      <Icon name={meta.icon} size={14} />
                      <strong>{t.label || meta.label}</strong>
                      {t.value && <span>{t.value}</span>}
                    </div>
                    {t.prev && (
                      <div className="feed-prev">
                        Before this: {t.prev.label} at {clockTime(t.prev.at)} ({relTime(t.prev.at)}{" "}
                        ago)
                      </div>
                    )}
                    <div className="feed-actions">
                      <button
                        className="chip-btn is-pick"
                        aria-pressed={picked}
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
                        <span>{picked ? "Picked" : "Mark Picked"}</span>
                      </button>
                      <button
                        className="chip-btn"
                        aria-expanded={noteOpen === t.id}
                        title="Add a note for this learner"
                        onClick={(e) => {
                          e.stopPropagation();
                          setNoteText("");
                          setNoteOpen(noteOpen === t.id ? null : t.id);
                        }}
                      >
                        Add Note
                      </button>
                      <button
                        className="icon-btn"
                        title="Dismiss alert (also closes the note box)"
                        aria-label={`Dismiss alert for ${displayFor(t.studentID)}`}
                        onClick={(e) => {
                          e.stopPropagation();
                          ackTrigger(t.id);
                        }}
                      >
                        <Icon name="close" size={15} />
                      </button>
                    </div>
                    {noteOpen === t.id && (
                      <div className="feed-note" onClick={(e) => e.stopPropagation()}>
                        <textarea
                          aria-label={`Note on ${displayFor(t.studentID)}`}
                          value={noteText}
                          autoFocus
                          placeholder="What did you see during this alert?"
                          onChange={(e) => setNoteText(e.target.value)}
                        />
                        <button
                          type="button"
                          disabled={!noteText.trim()}
                          onClick={() => {
                            addNote(t.studentID, noteText, t);
                            setNoteOpen(null);
                            setNoteText("");
                          }}
                        >
                          Save Note
                        </button>
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>
          )}

          {unackedSwitches.length > 0 && (
            <>
              <div className="feed-head feed-head-sub">
                <h2>Identity Switches</h2>
                <span className="feed-count">{unackedSwitches.length}</span>
              </div>
              <ul className="feed-list">
                {unackedSwitches.map((s) => (
                  <li
                    key={s.id}
                    className="feed-item"
                    style={toneVars(TRIGGERS.inactive.c)}
                    onClick={() => setSelected(s.studentID)}
                  >
                    <div className="feed-row">
                      <button
                        className="student-open feed-id"
                        onClick={() => setSelected(s.studentID)}
                      >
                        {displayFor(s.studentID)}
                      </button>
                      <span className="feed-age" title={fullTime(s.ts)}>
                        {relTime(s.ts)} ago
                      </span>
                      <button
                        className="icon-btn"
                        title="Dismiss switch"
                        aria-label={`Dismiss switch for ${displayFor(s.studentID)}`}
                        onClick={(e) => {
                          e.stopPropagation();
                          ackSwitch(s.id);
                        }}
                      >
                        <Icon name="close" size={15} />
                      </button>
                    </div>
                    <div className="feed-what">
                      <Icon name="swap" size={14} />
                      <strong>{s.kind === "casing" ? "casing changed" : "new class"}</strong>
                      <span>
                        {s.kind === "casing" ? s.from : s.from || "-"} -&gt; {s.to}
                      </span>
                    </div>
                  </li>
                ))}
              </ul>
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
              style={t.error ? { ...S.toast, borderColor: "var(--lmd-signal-d0433c)" } : S.toast}
            >
              <div
                style={
                  t.error ? { ...S.toastIcon, color: "var(--lmd-signal-d0433c)" } : S.toastIcon
                }
              >
                <Icon name={t.error ? "alert" : "swap"} size={16} />
              </div>
              <div style={S.toastBody}>
                <span style={t.error ? { ...S.toastTitle, color: "#d0433c" } : S.toastTitle}>
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
                      <span style={{ ...S.toastArrow, color: "#d38b12" }}>{t.to}</span>
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
          aria-labelledby="sd-title"
          onCancel={() => setSelected(null)}
          onClick={(e) => {
            if (e.target === e.currentTarget) setSelected(null);
          }}
        >
          <div className="student-detail">
            <Detail
              s={detail}
              sid={selected}
              status={statusMeta(statusBy[selected], !!detail)}
              loading={!detail && detailFor !== selected}
              history={history}
              notes={notes}
              onAddNote={(text) => addNote(selected, text, null)}
              onClose={() => setSelected(null)}
            />
          </div>
        </dialog>
      )}
    </div>
  );
};

export default CohortDashboard;
