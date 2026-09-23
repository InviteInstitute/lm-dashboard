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
// "clear_debris_zone" -> "Clear debris zone": sentence case for goal names.
const _sentence = (s) => {
  const h = _humanize(s);
  return h.charAt(0).toUpperCase() + h.slice(1);
};

// Goal-evidence styling. Restrained on colour on purpose: this is evidence, not
// a score. Each indicator is drawn as the rung ladder it climbed this run --
// segments weaker (left) to stronger (right), filled up to the reached rung --
// so a rung reads as a position on a scale, never as good/bad. Abstentions and
// meaningful absences get an honest pill instead of a fake rung; uncertainty is
// an amber flag chip, provenance a neutral one.
const goalFlagChip = {
  fontFamily: MONO,
  fontSize: 10.5,
  color: "var(--lmd-warning)",
  border: "1px solid var(--lmd-warning)",
  borderRadius: 999,
  padding: "1px 8px",
  background: "transparent",
  whiteSpace: "nowrap",
};
const goalProvenanceChip = {
  fontFamily: MONO,
  fontSize: 10.5,
  color: T.sub,
  border: `1px solid ${T.border}`,
  borderRadius: 999,
  padding: "1px 8px",
  background: "transparent",
  whiteSpace: "nowrap",
};
// Uncertainty flags qualify the reading (amber); every other flag is provenance.
const UNCERTAINTY_FLAGS = new Set(["sim_unverified", "fabricated_motion", "invalid_timestamp"]);

// One rung on the ladder. reached = filled dark; climbed (rungs below the one
// reached) = light fill; not-yet-reached = outline only.
const goalRungSeg = (state) => ({
  flex: 1,
  minWidth: 0,
  textAlign: "center",
  fontSize: 12,
  fontWeight: state === "reached" ? 600 : 400,
  color: state === "reached" ? T.bg : state === "climbed" ? T.ink : T.sub,
  background: state === "reached" ? T.ink : state === "climbed" ? T.track : "transparent",
  border: `1px solid ${state === "reached" ? T.ink : T.border}`,
  borderRadius: 6,
  padding: "3px 6px",
  whiteSpace: "nowrap",
  overflow: "hidden",
  textOverflow: "ellipsis",
});
// An indicator with no rung to place: an abstention (dashed, no reading) or a
// meaningful absence (solid, the thing never happened). Never a fake rung.
const goalNoReadingPill = (absent) => ({
  fontSize: 12,
  color: absent ? T.sub : T.faint,
  border: absent ? `1px solid ${T.border}` : `1px dashed ${T.border}`,
  borderRadius: 6,
  padding: "4px 10px",
  background: absent ? T.track : "transparent",
});
const goalRunCell = (active) => ({
  fontFamily: MONO,
  fontSize: 12,
  fontWeight: active ? 700 : 400,
  minWidth: 32,
  minHeight: 28,
  padding: "0 8px",
  borderRadius: 6,
  cursor: "pointer",
  color: active ? T.ink : T.sub,
  background: active ? T.panel : T.track,
  border: `1px solid ${active ? T.ink : T.border}`,
});

// Where an indicator's reading came from: observed (outcome, filled dot),
// simulation (open dot), or authored from the code (open square).
const ChannelMark = ({ channel }) => {
  const base = {
    width: 9,
    height: 9,
    flexShrink: 0,
    display: "inline-block",
    boxSizing: "border-box",
  };
  if (channel === "outcome")
    return <span title="observed" style={{ ...base, borderRadius: "50%", background: T.ink }} />;
  if (channel === "simulation")
    return (
      <span
        title="simulation"
        style={{ ...base, borderRadius: "50%", border: `1.5px solid ${T.sub}` }}
      />
    );
  if (channel === "code")
    return <span title="authored" style={{ ...base, border: `1.5px solid ${T.sub}` }} />;
  return (
    <span
      title="channel"
      style={{ ...base, borderRadius: "50%", border: `1.5px solid ${T.faint}` }}
    />
  );
};

// The continuous value behind a rung, shown small beside the name: one decimal
// at scale, a little more precision below 1, integers bare; categorical values
// (e.g. "on_island") are humanized strings.
const fmtGoalVal = (v) => {
  if (v == null || typeof v === "boolean") return null;
  if (typeof v === "string") return _humanize(v);
  if (!Number.isFinite(v)) return null;
  if (Number.isInteger(v)) return String(v);
  if (Math.abs(v) < 0.005) return "0"; // float noise from the simulator, not a reading
  return Math.abs(v) >= 1 ? v.toFixed(1) : v.toPrecision(1);
};

// A rung ladder: the labels weaker -> stronger, filled up to the reached one.
const RungLadder = ({ labels, reached }) => (
  <div style={{ display: "flex", gap: 6 }}>
    {labels.map((label, i) => (
      <div
        key={label}
        title={_humanize(label)}
        style={goalRungSeg(i === reached ? "reached" : i < reached ? "climbed" : "todo")}
      >
        {_humanize(label)}
      </div>
    ))}
  </div>
);

// One indicator: the channel mark + name + value/flags on top, then the rung
// ladder it climbed (or an honest no-reading pill when there is no rung).
const GoalIndicatorRow = ({ ind }) => {
  const val = fmtGoalVal(ind.value);
  // The ladder reads weaker -> stronger, left to right. For lower-is-better
  // indicators the engine lists the strongest rung first, so flip for display.
  const labels =
    ind.direction === "lower_is_better"
      ? [...(ind.rung_labels || [])].reverse()
      : ind.rung_labels || [];
  const reached = labels.indexOf(ind.rung);
  const absent = ind.absent_label != null && ind.rung === ind.absent_label;
  const showLadder = !ind.abstained && !absent && labels.length > 0 && reached !== -1;
  return (
    <div style={{ marginBottom: 10 }}>
      <div
        style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", marginBottom: 5 }}
      >
        <ChannelMark channel={ind.channel} />
        <span style={{ color: T.ink, fontSize: 13 }}>{_humanize(ind.name)}</span>
        <span
          style={{
            marginLeft: "auto",
            display: "flex",
            alignItems: "center",
            gap: 7,
            flexWrap: "wrap",
          }}
        >
          {val != null && showLadder && (
            <span
              style={{
                fontFamily: MONO,
                fontSize: 11,
                color: T.faint,
                fontVariantNumeric: "tabular-nums",
              }}
            >
              {val}
            </span>
          )}
          {(ind.flags || []).map((f) => (
            <span
              key={f}
              style={UNCERTAINTY_FLAGS.has(f) ? goalFlagChip : goalProvenanceChip}
              title={UNCERTAINTY_FLAGS.has(f) ? "uncertainty flag" : "provenance"}
            >
              {_humanize(f)}
            </span>
          ))}
        </span>
      </div>
      {ind.abstained ? (
        <div style={goalNoReadingPill(false)}>
          no reading - {_humanize(ind.abstain_reason) || "no data"}
        </div>
      ) : absent ? (
        <div style={goalNoReadingPill(true)}>{_humanize(ind.rung)} (not attempted)</div>
      ) : showLadder ? (
        <RungLadder labels={labels} reached={reached} />
      ) : (
        <div style={goalNoReadingPill(false)}>no reading</div>
      )}
    </div>
  );
};

// One goal: what it "achieved" (the attainment indicators) first, then what the
// code was "attempting" (the intent indicators), each role named in a gutter.
const GoalCard = ({ g }) => {
  const inds = g.indicators || [];
  const roles = [
    ["achieved", inds.filter((i) => i.role === "attainment")],
    ["attempting", inds.filter((i) => i.role !== "attainment")],
  ].filter(([, list]) => list.length > 0);
  return (
    <div className="goal-block">
      <h5>{_sentence(g.goal)}</h5>
      {roles.map(([role, list]) => (
        <div key={role} className="goal-role">
          <span className="goal-role-label">{role}</span>
          <div>
            {list.map((ind, i) => (
              <GoalIndicatorRow key={i} ind={ind} />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
};

// Run-level outcomes the per-goal rows don't carry: leaving the island is a
// critical failure (not a goal), so it gets a filled chip -- the one place a
// colour reads as a state, like the status badges. Everything else is a quiet note.
const goalCriticalChip = {
  fontFamily: MONO,
  fontSize: 11,
  fontWeight: 700,
  color: T.panel,
  background: "var(--lmd-signal-ef4444)",
  borderRadius: 999,
  padding: "2px 10px",
  whiteSpace: "nowrap",
};

const GoalRunSummary = ({ run }) => {
  const s = run.summary || {};
  const notes = [];
  if (s.outcome_available === false) notes.push("no telemetry associated yet");
  if (s.fidelity_verdict && s.fidelity_verdict !== "not_applicable")
    notes.push(`sim vs GPS ${_humanize(s.fidelity_verdict).toLowerCase()}`);
  if (s.fabricated_motion) notes.push("fabricated motion");
  if (s.orphan_block_count) notes.push(`${s.orphan_block_count} orphan blocks`);
  // inherited_playground is routine bookkeeping, not worth showing here
  const diags = (run.diagnostics || []).filter((d) => d !== "inherited_playground");
  if (!s.boundary_exceeded && notes.length === 0 && diags.length === 0) return null;
  return (
    <div
      style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center", marginBottom: 12 }}
    >
      {s.boundary_exceeded && (
        <span style={goalCriticalChip}>
          left the island
          {s.boundary_exit_step != null ? ` at step ${s.boundary_exit_step}` : ""}
          {s.boundary_exit_overridden ? " (outcome override)" : ""}
        </span>
      )}
      {notes.length > 0 && (
        <span
          style={{
            color: T.sub,
            fontSize: 11.5,
            fontFamily: MONO,
            display: "flex",
            gap: 14,
            flexWrap: "wrap",
          }}
        >
          {notes.map((n) => (
            <span key={n}>{n}</span>
          ))}
        </span>
      )}
      {diags.map((d) => (
        <span key={d} style={goalFlagChip} title="diagnostic">
          {_humanize(d)}
        </span>
      ))}
    </div>
  );
};

const goalSubLabel = { fontSize: 13, fontWeight: 600, color: T.sub, margin: "12px 0 6px" };

// The goal-progression timeline: each row is a moment a block moved a goal's
// indicator from one rung to another (post-exit steps dimmed).
const GoalTimeline = ({ timeline }) => {
  const events = (timeline && timeline.events) || [];
  const post = (timeline && timeline.post_exit_events) || [];
  if (events.length === 0 && post.length === 0)
    return (
      <div style={{ color: T.faint, fontSize: 12 }}>No rung changes recorded on this run.</div>
    );
  const row = (e, i, faded) => (
    <div
      key={`${faded ? "p" : "e"}${i}`}
      style={{
        display: "flex",
        gap: 8,
        alignItems: "baseline",
        flexWrap: "wrap",
        fontFamily: MONO,
        fontSize: 11.5,
        opacity: faded ? 0.55 : 1,
        marginBottom: 3,
      }}
    >
      <span style={{ color: T.faint, minWidth: 30 }}>#{e.step}</span>
      <span style={{ color: T.sub }}>
        {_humanize(e.goal)}.{_humanize(e.indicator)}
      </span>
      <span style={{ color: T.ink }}>
        {_humanize(e.from_rung) || "start"} &rarr; {_humanize(e.to_rung)}
      </span>
      {(e.flags || []).map((f) => (
        <span key={f} style={goalFlagChip}>
          {_humanize(f)}
        </span>
      ))}
    </div>
  );
  return (
    <div>
      {events.map((e, i) => row(e, i, false))}
      {post.length > 0 && <div style={goalSubLabel}>after leaving the island</div>}
      {post.map((e, i) => row(e, i, true))}
    </div>
  );
};

// The sensor-test battery: each scenario drops the program into a designed test
// world and records per-check evidence. Pass/conditional/fail are verdicts;
// "measured" checks carry a value instead (e.g. the share of pieces cleared);
// "abstained" means the run never reached what the check tests. Scenarios are
// grouped by family (t1 debris field, t2 boundary, ...). Only programs that read
// a sensor are eligible.
const GOAL_CHECK_VERDICTS = ["pass", "conditional", "fail"];
const goalCheckColor = (st) =>
  st === "pass"
    ? "var(--lmd-success)"
    : st === "fail"
      ? "var(--lmd-signal-ef4444)"
      : st === "conditional"
        ? "var(--lmd-warning)"
        : T.sub;
const _checkState = (c) => (c.abstained || c.status === "abstained" ? "abstained" : c.status);
const _pct = (v) => `${Math.round(v * 100)}%`;
// "t2_boundary" -> "T2 boundary"
const _familyLabel = _sentence;

// Card descriptions lead with the family and variant ("T2 boundary response --
// direct -- head-on arrival, ..."), which the family header and scenario id
// already show; keep just the part that says what is different about the world.
const _scenarioBlurb = (sc) => {
  const parts = (sc.description || "").split(/\s+\u2014\s+/);
  const variant = _humanize((sc.scenario_id || "").replace(/^t\d+[a-z]?_/, "")).toLowerCase();
  let i = 0;
  while (
    i < parts.length - 1 &&
    !parts[i].includes("(") &&
    (/^T\d/.test(parts[i]) || parts[i].toLowerCase() === variant)
  )
    i += 1;
  let rest = parts.slice(i).join(" - ");
  if (parts.length > 1 && i === parts.length - 1 && /^T\d/.test(parts[0])) {
    // "T4 debris configuration -- dispersed." : nothing beyond the variant name
    if (rest.replace(/\.$/, "").toLowerCase() === variant) rest = "";
    // "near favorable (T4's world, tight clear rule)." : keep the aside
    else if (rest.toLowerCase().startsWith(`${variant} (`))
      rest = rest.slice(variant.length + 2).replace(/\)\.?$/, "");
  }
  return rest;
};

const CheckDot = ({ state }) => (
  <span
    style={{
      width: 7,
      height: 7,
      flexShrink: 0,
      borderRadius: "50%",
      boxSizing: "border-box",
      background:
        state === "abstained" || state === "measured" ? "transparent" : goalCheckColor(state),
      border:
        state === "abstained"
          ? `1px dashed ${T.faint}`
          : state === "measured"
            ? `1.5px solid ${T.sub}`
            : "none",
    }}
  />
);

const BatteryCheck = ({ c }) => {
  const state = _checkState(c);
  const measured = state === "measured" && Number.isFinite(c.value);
  const detail =
    state === "abstained"
      ? `abstained: ${_humanize(c.abstain_reason) || "not reached"}`
      : `${state}${c.detail ? ` (${c.detail})` : ""}`;
  return (
    <span
      title={`${_humanize(c.name)}: ${detail}`}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 5,
        fontFamily: MONO,
        fontSize: 10.5,
        color: state === "abstained" ? T.faint : T.sub,
        border: `1px ${state === "abstained" ? "dashed" : "solid"} ${T.border}`,
        borderRadius: 6,
        padding: "1px 7px",
      }}
    >
      <CheckDot state={state} />
      {_humanize(c.name)}
      {measured && (
        <span style={{ color: T.ink, fontVariantNumeric: "tabular-nums" }}>
          {c.value >= 0 && c.value <= 1 ? _pct(c.value) : fmtGoalVal(c.value)}
        </span>
      )}
      {c.capped && <span style={{ color: "var(--lmd-warning)" }}>capped</span>}
    </span>
  );
};

// How a family's checks came out, as dot + count pairs (verdicts, then the rest).
const BatteryTally = ({ scenarios }) => {
  const n = {};
  scenarios.forEach((sc) =>
    (sc.checks || []).forEach((c) => {
      const st = _checkState(c);
      n[st] = (n[st] || 0) + 1;
    }),
  );
  const order = [...GOAL_CHECK_VERDICTS, "measured", "abstained"].filter((st) => n[st]);
  return (
    <span style={{ display: "inline-flex", gap: 10, marginLeft: "auto", flexWrap: "wrap" }}>
      {order.map((st) => (
        <span
          key={st}
          title={`${n[st]} ${st}`}
          style={{ display: "inline-flex", alignItems: "center", gap: 4, color: T.sub }}
        >
          <CheckDot state={st} />
          {n[st]} {st}
        </span>
      ))}
    </span>
  );
};

const GoalBattery = ({ battery }) => {
  if (!battery) return null;
  if (!battery.eligible)
    return (
      <div style={{ color: T.faint, fontSize: 12 }}>
        Not applicable: this program reads no sensors.
      </div>
    );
  const families = [];
  (battery.scenarios || []).forEach((sc) => {
    const key = sc.family || "other";
    let fam = families.find((f) => f.key === key);
    if (!fam) families.push((fam = { key, scenarios: [] }));
    fam.scenarios.push(sc);
  });
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <div style={{ color: T.sub, fontSize: 11, fontFamily: MONO, marginBottom: 2 }}>
        sensing: {(battery.qualifying_blocks || []).map(_humanize).join(", ")}
      </div>
      {families.map((fam) => (
        <details
          key={fam.key}
          style={{
            border: `1px solid ${T.border}`,
            borderRadius: 8,
            background: T.track,
          }}
        >
          <summary
            style={{
              display: "flex",
              alignItems: "center",
              gap: 10,
              flexWrap: "wrap",
              cursor: "pointer",
              padding: "7px 10px",
              fontFamily: MONO,
              fontSize: 11,
              listStyle: "none",
            }}
          >
            <span style={{ color: T.faint }} aria-hidden="true" className="goal-fam-caret">
              &#9656;
            </span>
            <span style={{ color: T.ink, fontWeight: 600 }}>{_familyLabel(fam.key)}</span>
            <span style={{ color: T.faint }}>
              {fam.scenarios.length} {fam.scenarios.length === 1 ? "scenario" : "scenarios"}
            </span>
            <BatteryTally scenarios={fam.scenarios} />
          </summary>
          <div
            style={{ display: "flex", flexDirection: "column", gap: 9, padding: "2px 10px 10px" }}
          >
            {fam.scenarios.map((sc, si) => (
              <div key={`${sc.scenario_id}-${sc.construct}-${si}`}>
                <div
                  style={{
                    display: "flex",
                    gap: 10,
                    alignItems: "baseline",
                    flexWrap: "wrap",
                    marginBottom: 5,
                  }}
                >
                  <span style={{ fontFamily: MONO, fontSize: 11.5, color: T.ink }}>
                    {_humanize(sc.scenario_id)}
                  </span>
                  {_scenarioBlurb(sc) && (
                    <span style={{ color: T.faint, fontSize: 11.5 }} title={sc.description}>
                      {_scenarioBlurb(sc)}
                    </span>
                  )}
                </div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                  {(sc.checks || []).map((c, ci) => (
                    <BatteryCheck key={ci} c={c} />
                  ))}
                </div>
              </div>
            ))}
          </div>
        </details>
      ))}
    </div>
  );
};

// Where a rollup claim or rubric level was read from, as a short source name.
const _evidenceSource = (e) => {
  const [src, ...rest] = (e || "").split(".");
  const name = _humanize(rest.join(".")) || _humanize(src);
  const where = { production: "code", battery: "tests" }[src] || src;
  return rest.length ? `${where}: ${name}` : name;
};

// A mono caption line under a ladder: quiet key/value facts, space-separated.
const GoalFacts = ({ facts }) => {
  const shown = facts.filter(([, v]) => v != null && v !== "");
  if (shown.length === 0) return null;
  return (
    <div
      style={{
        display: "flex",
        gap: 14,
        flexWrap: "wrap",
        marginTop: 5,
        fontFamily: MONO,
        fontSize: 10.5,
        color: T.faint,
      }}
    >
      {shown.map(([k, v]) => (
        <span key={k}>
          {k} <span style={{ color: T.sub }}>{v}</span>
        </span>
      ))}
    </div>
  );
};

// One rolled-up goal claim (purpose 1): the goal, where the claim comes from,
// the band/claim on its ladder, then the support behind it.
const GoalClaimRow = ({ g }) => {
  const labels = g.rungs || [];
  const reached = labels.indexOf(g.rung);
  const fromTests = g.source === "battery";
  const reduced = fromTests && g.certainty && g.certainty !== "full";
  // No battery test contributed at all: the program reads no sensors, so there
  // was nothing to band. Say that rather than a bare "no evidence".
  const noTests = fromTests && !g.n_valid && !g.n_abstained;
  const d = g.debris || {};
  const facts = fromTests
    ? [
        ["tests", noTests ? null : `${g.n_valid || 0} valid, ${g.n_abstained || 0} abstained`],
        [
          "pieces cleared",
          Number.isFinite(d.proportion_cleared) ? _pct(d.proportion_cleared) : null,
        ],
        [
          "zone coverage",
          Number.isFinite(d.zone_coverage)
            ? `${_pct(d.zone_coverage)}${d.zone_coverage_band ? ` (${_humanize(d.zone_coverage_band)})` : ""}`
            : null,
        ],
        [
          "weight cleared",
          Number.isFinite(d.weight_cleared_kg)
            ? `${Math.round(d.weight_cleared_kg)} kg${d.weight_cleared_band ? ` (${_humanize(d.weight_cleared_band)})` : ""}`
            : null,
        ],
      ]
    : Object.entries(g.basis || {}).map(([k, v]) => [
        _humanize(k),
        v == null ? "n/a" : _humanize(v),
      ]);
  return (
    <div style={{ marginBottom: 12 }}>
      <div
        style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", marginBottom: 5 }}
      >
        <span style={{ fontSize: 14, fontWeight: 600, color: T.ink }}>{_sentence(g.goal)}</span>
        <span style={{ marginLeft: "auto", display: "flex", gap: 7, flexWrap: "wrap" }}>
          {reduced &&
            (g.certainty_reasons.length ? g.certainty_reasons : [`${g.certainty} certainty`]).map(
              (r) => (
                <span key={r} style={goalFlagChip} title={`certainty ${g.certainty}`}>
                  {_humanize(r)}
                </span>
              ),
            )}
          {(g.flags || []).map((f) => (
            <span key={f} style={goalFlagChip} title="flag">
              {_humanize(f)}
            </span>
          ))}
          <span
            style={goalProvenanceChip}
            title={
              fromTests
                ? "banded from the sensor-test battery"
                : "derived from this goal's indicator rungs (no battery channel by design)"
            }
          >
            {fromTests ? "from tests" : "from indicators"}
          </span>
        </span>
      </div>
      {reached !== -1 ? (
        <RungLadder labels={labels} reached={reached} />
      ) : (
        <div style={goalNoReadingPill(false)}>
          no reading -{" "}
          {noTests ? "no sensor tests ran" : _humanize(g.abstain_reason) || "no evidence"}
        </div>
      )}
      <GoalFacts facts={facts} />
    </div>
  );
};

const GoalClaims = ({ rollup }) => (
  <div>
    {(rollup.goals || []).map((g) => (
      <GoalClaimRow key={g.goal} g={g} />
    ))}
  </div>
);

// The purpose-2 execution rubric: six dimensions of HOW the program runs, each
// a level on 0..max. Provisional upstream (still under human validation), so it
// is labelled as such and never reads as a grade.
const GoalRubric = ({ rubric }) => (
  <div>
    {(rubric.dimensions || []).map((d) => {
      const labels = Array.from({ length: (d.max_level || 0) + 1 }, (_, i) => String(i));
      return (
        <div key={d.dimension} style={{ marginBottom: 10 }}>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              flexWrap: "wrap",
              marginBottom: 5,
            }}
          >
            <span style={{ color: T.ink, fontSize: 13 }}>{_humanize(d.dimension)}</span>
            <span style={{ marginLeft: "auto", display: "flex", gap: 7, flexWrap: "wrap" }}>
              {d.borderline && (
                <span style={goalFlagChip} title="within the borderline margin of the next level">
                  borderline
                </span>
              )}
              {d.ceiling != null && d.ceiling < d.max_level && (
                <span
                  style={goalProvenanceChip}
                  title="the highest level this program's code can show"
                >
                  code ceiling {d.ceiling}
                </span>
              )}
            </span>
          </div>
          {d.level == null ? (
            <div style={goalNoReadingPill(false)}>undetermined - {_humanize(d.u_reason)}</div>
          ) : (
            <RungLadder labels={labels} reached={d.level} />
          )}
          <GoalFacts
            facts={[
              ["evidence", (d.evidence || []).map(_evidenceSource).join(", ") || null],
              ["against", (d.negatives || []).map(_evidenceSource).join(", ") || null],
            ]}
          />
        </div>
      );
    })}
  </div>
);

// Legend for the panel: what each channel mark means, and how the ladder fills.
const GoalLegend = () => {
  const item = (mark, label) => (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        color: T.sub,
        fontFamily: MONO,
        fontSize: 10.5,
      }}
    >
      {mark}
      {label}
    </span>
  );
  const swatch = (reached) => (
    <span
      style={{
        width: 16,
        height: 11,
        borderRadius: 3,
        display: "inline-block",
        background: reached ? T.ink : T.track,
        border: `1px solid ${reached ? T.ink : T.border}`,
      }}
    />
  );
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 14,
        flexWrap: "wrap",
        marginBottom: 12,
      }}
    >
      {item(<ChannelMark channel="outcome" />, "observed")}
      {item(<ChannelMark channel="simulation" />, "simulation")}
      {item(<ChannelMark channel="code" />, "authored")}
      {item(swatch(true), "reached rung")}
      {item(swatch(false), "climbed")}
      <span style={{ color: T.faint, fontFamily: MONO, fontSize: 10.5 }}>
        weaker &rsaquo; stronger
      </span>
    </div>
  );
};

// A sub-part of the goal-evidence section (claims, indicators, rubric, ...).
const GoalPart = ({ title, aside, children }) => (
  <div className="goal-part">
    <h4>
      {title}
      {aside}
    </h4>
    {children}
  </div>
);

export const GoalEvidence = ({ runs, enabled }) => {
  const list = runs || [];
  const [picked, setPicked] = React.useState(null);
  if (enabled === false)
    return (
      <Section title="Goal evidence">
        <p className="sd-empty">Goal recognition is switched off.</p>
      </Section>
    );
  if (list.length === 0)
    return (
      <Section title="Goal evidence">
        <p className="sd-empty">
          No Castle Crashers runs profiled yet (goal evidence is Castle Crashers only).
        </p>
      </Section>
    );
  // Focus one run (latest by default); honour a manual pick while it still exists.
  const run = list.find((r) => r.index === picked) || list[list.length - 1];
  const latest = list[list.length - 1].index;
  const picker =
    list.length > 1 ? (
      <div className="goal-runs" role="group" aria-label="Profiled run">
        <span>Run</span>
        {list.map((r) => (
          <button
            key={r.index}
            type="button"
            onClick={() => setPicked(r.index)}
            aria-pressed={r.index === run.index}
            title={r.index === latest ? `Run ${r.index} (latest)` : `Run ${r.index}`}
            style={goalRunCell(r.index === run.index)}
          >
            {r.index}
          </button>
        ))}
      </div>
    ) : (
      <span className="sd-count">Run {run.index}</span>
    );
  return (
    <Section title="Goal evidence" aside={picker}>
      <p className="goal-intro">
        Each indicator is drawn as the rung ladder it climbed on this run, weaker to stronger.
        Abstentions and uncertainty stay visible. This is evidence, not a score.
      </p>
      <GoalLegend />
      <GoalRunSummary run={run} />
      {run.rollup && (run.rollup.goals || []).length > 0 && (
        <GoalPart title="Goal claims">
          <GoalClaims rollup={run.rollup} />
        </GoalPart>
      )}
      {(run.goals || []).length > 0 && (
        <GoalPart title="Indicators">
          {run.goals.map((g) => (
            <GoalCard key={g.goal} g={g} />
          ))}
        </GoalPart>
      )}
      {run.rubric && (run.rubric.dimensions || []).length > 0 && (
        <GoalPart
          title="Execution rubric"
          aside={
            <span
              style={goalFlagChip}
              title={`still under human validation upstream (${run.rubric.status || "provisional"})`}
            >
              provisional
            </span>
          }
        >
          <GoalRubric rubric={run.rubric} />
        </GoalPart>
      )}
      {run.timeline && (
        <GoalPart title="Goal progression">
          <GoalTimeline timeline={run.timeline} />
        </GoalPart>
      )}
      {run.battery && (
        <GoalPart title="Sensor test battery">
          <GoalBattery battery={run.battery} />
        </GoalPart>
      )}
    </Section>
  );
};

// ---------------- detail (side sheet) ----------------
// The drill-down for one student, opened as a sheet over the right of the board
// so the cohort stays in view. Sticky header (id, status, counts, close), then
// two columns: the evidence (activity strips, code, goal evidence) on the left,
// and the researcher's own record (notes, trigger history) in a rail on the right.

// A titled block of the sheet. `aside` sits at the right end of the heading row
// (a tab switch, a run picker, a count).
const Section = ({ title, aside, children }) => (
  <section className="sd-section">
    <div className="sd-section-head">
      <h3>{title}</h3>
      {aside}
    </div>
    {children}
  </section>
);

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
      title="Latest program"
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
    title="Trigger history"
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
            Save note
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
                <span>{n.ts}</span>
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
        if (alive) setDetailFull(null);
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
