// The small visual marks goal evidence is drawn with: flag chips, channel marks,
// check dots, pips and rung ladders. Restrained on colour on purpose: this is
// evidence, not a score, so a rung reads as a position on a scale, never as
// good or bad.
import React from "react";
import { OperationalTag, Tag } from "@carbon/react";
import { WarningAlt } from "@carbon/icons-react";
import { UNCERTAIN_FLAG, flagText, humanize } from "./text";

// However many flags a row carries, it gets one chip: the most important flag
// (uncertainty before provenance) plus a count. The chip opens the full list
// inline below the row, so nothing is hover-only and nothing wraps into a
// second line of chips. Returns the chip and the list separately, since they
// sit in different places in a row. `allUncertain` is for lists that are hedges
// by definition (a claim's certainty reasons, run diagnostics).
export function useFlags(flags, allUncertain = false) {
  const [open, setOpen] = React.useState(false);
  const all = [...new Set(flags || [])];
  if (all.length === 0) return { chip: null, list: null };
  const unc = all.filter((f) => allUncertain || UNCERTAIN_FLAG.test(f));
  const prov = all.filter((f) => !unc.includes(f));
  const ordered = [...unc, ...prov];
  // Carbon's warm grey marks a hedge, cool grey a note on where a value came from.
  const type = unc.length ? "warm-gray" : "cool-gray";
  const icon = unc.length ? WarningAlt : undefined;
  const chip =
    ordered.length === 1 ? (
      <Tag
        as="span"
        size="sm"
        type={type}
        renderIcon={icon}
        className="flag-chip"
        title={`${unc.length ? "Uncertain" : "Where this came from"} (${ordered[0]})`}
      >
        {flagText(ordered[0])}
      </Tag>
    ) : (
      <OperationalTag
        size="sm"
        type={type}
        renderIcon={icon}
        className="flag-chip"
        aria-expanded={open}
        title={open ? "Hide flags" : `All flags: ${ordered.map(flagText).join(", ")}`}
        text={`${flagText(ordered[0])} +${ordered.length - 1}`}
        onClick={(e) => {
          e.stopPropagation();
          setOpen((o) => !o);
        }}
      />
    );
  const list = open && ordered.length > 1 && (
    <dl className="flag-list">
      {unc.length > 0 && (
        <div>
          <dt>Uncertain</dt>
          <dd>{unc.map(flagText).join(", ")}</dd>
        </div>
      )}
      {prov.length > 0 && (
        <div>
          <dt>Source</dt>
          <dd>{prov.map(flagText).join(", ")}</dd>
        </div>
      )}
    </dl>
  );
  return { chip, list };
}

// Where an indicator's reading came from: seen on the robot (filled dot), the
// simulator (open dot), or written in the code (open square).
const CHANNEL_TITLE = { outcome: "observed", simulation: "simulation", code: "authored" };
export const ChannelMark = ({ channel }) => (
  <span
    className={`channel-mark is-${CHANNEL_TITLE[channel] ? channel : "other"}`}
    title={CHANNEL_TITLE[channel] || "channel"}
  />
);

export const GoalLegend = () => (
  <ul className="goal-legend">
    <li>
      <ChannelMark channel="outcome" />
      Seen on the Robot
    </li>
    <li>
      <ChannelMark channel="simulation" />
      From the Simulator
    </li>
    <li>
      <ChannelMark channel="code" />
      Written in the Code
    </li>
  </ul>
);

// A sensor-test check's state as a dot: pass, conditional and fail are filled
// verdicts; measured is an open ring; abstained (inconclusive) is dashed.
export const CheckDot = ({ state }) => <span className={`check-dot is-${state}`} />;

// A ladder as a row of pips, weaker (left) to stronger (right): the reached rung
// solid, the ones below it lighter, the ones above it empty. `reached` -1 is no
// reading (every pip dashed). Decorative: the rung is always written out beside it.
export const Pips = ({ n, reached }) => (
  <span className={`pips${reached === -1 ? " is-none" : ""}`} aria-hidden="true">
    {Array.from({ length: n }, (_, i) => (
      <i
        key={i}
        className={i === reached ? "is-reached" : i < reached ? "is-climbed" : undefined}
      />
    ))}
  </span>
);

// A rung ladder: a segmented bar weaker -> stronger, filled up to the reached
// rung (the reached segment solid, the ones below it lighter), names underneath.
export const RungLadder = ({ labels, reached }) => (
  <ol className="rungs" style={{ gridTemplateColumns: `repeat(${labels.length}, minmax(0, 1fr))` }}>
    {labels.map((label, i) => (
      <li
        key={label}
        className={i === reached ? "is-reached" : i < reached ? "is-climbed" : undefined}
        aria-current={i === reached ? "true" : undefined}
        title={humanize(label)}
      >
        {humanize(label)}
      </li>
    ))}
  </ol>
);
