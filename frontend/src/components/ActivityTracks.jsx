// The two activity strips on a card and in the sheet: one tile per run, coloured
// by how much the code changed, and one tile per episode, coloured by its type.
// `compact` (the card) shows the last COMPACT_TAIL units; the sheet shows all of
// them, scrolled to the newest.
import React from "react";
import {
  COMPACT_TAIL,
  ED_BIG,
  ED_SMALL,
  ED_ZERO,
  EP,
  HATCH_AMBER,
  PAUSE_FILL,
  PAUSE_LEGEND,
  edColor,
} from "../constants";
import { fmtDur } from "../lib/time";

const tail = (all, compact) =>
  compact && all.length > COMPACT_TAIL ? all.slice(-COMPACT_TAIL) : all;

// Runs as tiles, coloured by edit distance: grey no change, blue an edit,
// purple a big change (>= 13). The first run has no predecessor, so it is faint.
function runSegments(data, compact) {
  const all = data.runs || [];
  const runs = tail(all, compact);
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

// Episodes as one equal tile each (count and duration in the tooltip), with
// the real pauses (inactive, post-run) drawn as hatched gaps between them.
function episodeSegments(data, compact) {
  const eps = tail(data.episodes || [], compact);
  const minIdx = eps.length ? eps[0].start_idx : 0;
  const pauseAt = {};
  (data.pauses || []).forEach((p) => {
    pauseAt[p.after_idx] = p;
  });
  const segs = [];
  eps.forEach((ep) => {
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

// A strip of tiles. `flush` (episodes) sets consecutive tiles edge to edge, so a
// code -> run -> code stretch reads as one burst of work. The only breaks are
// the pauses between bursts.
const Track = ({ segments, compact, flush }) => {
  const ref = React.useRef(null);
  React.useLayoutEffect(() => {
    if (!compact && ref.current) ref.current.scrollLeft = ref.current.scrollWidth;
  }, [compact, segments.length]);
  const cls = `track${compact ? " is-compact" : ""}${flush ? " is-flush" : ""}`;
  return (
    <div ref={ref} className={cls}>
      {segments.map((s) => (
        <div
          key={s.key}
          title={s.title}
          className={s.pause ? "track-pause" : s.faint ? "track-tile is-faint" : "track-tile"}
          style={{ background: s.bg }}
        />
      ))}
    </div>
  );
};

const Legend = ({ items }) => (
  <div className="track-legend">
    {items.map(([label, fill]) => (
      <span key={label}>
        <i style={{ background: fill }} />
        {label}
      </span>
    ))}
  </div>
);

const Empty = ({ compact, children }) => (
  <div className={`track-empty${compact ? " is-compact" : ""}`}>{children}</div>
);

const RUN_LEGEND = [
  ["No Change", ED_ZERO],
  ["Edit", ED_SMALL],
  ["Big Change (>=13)", ED_BIG],
];
const EPISODE_LEGEND = [["CODE", EP.CODE], ["RUN", EP.RUN], ["RESET", EP.RESET], ...PAUSE_LEGEND];

export const RunTrack = ({ data, compact }) => {
  if (!data || !data.runs || data.runs.length === 0)
    return <Empty compact={compact}>No runs yet.</Empty>;
  return (
    <>
      <Track segments={runSegments(data, compact)} compact={compact} />
      {!compact && <Legend items={RUN_LEGEND} />}
    </>
  );
};

export const EpisodeTrack = ({ data, compact }) => {
  if (!data || data.event_count === 0) return <Empty compact={compact}>No events yet.</Empty>;
  return (
    <>
      <Track segments={episodeSegments(data, compact)} compact={compact} flush />
      {!compact && <Legend items={EPISODE_LEGEND} />}
    </>
  );
};
