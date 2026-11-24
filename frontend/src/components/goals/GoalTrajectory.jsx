// Where each goal's claim landed on every profiled run. A real table, so every
// value is readable without hover. One hue, ordinal: a bar's fill height is the
// rung's place on its ladder. The run headers pick the run the board below shows.
import React from "react";
import {
  SelectableTag,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@carbon/react";
import { Icon } from "../../icons";
import { claimOn, rungLevel } from "./claims";
import { humanize, title } from "./text";

const rungText = (g) =>
  g ? (rungLevel(g) == null ? "no reading" : humanize(g.rung)) : "not assessed";

const left = (r) => r.summary && r.summary.boundary_exceeded;
const currentClass = (r, current) => (r.index === current ? "is-current" : undefined);

// The picked run's rung for one goal, written out: the one direct label per row.
const TrajNow = ({ g }) => (
  <TableCell className="traj-now">
    {g ? rungLevel(g) == null ? <i>no reading</i> : humanize(g.rung) : <i>not assessed</i>}
  </TableCell>
);

export const GoalTrajectory = ({ runs, goals, current, onPick }) => {
  const wrap = React.useRef(null);
  React.useLayoutEffect(() => {
    if (wrap.current) wrap.current.scrollLeft = wrap.current.scrollWidth; // latest run in view
  }, [runs.length]);
  const picked = runs.find((r) => r.index === current) || {};
  return (
    <div className="traj" ref={wrap}>
      <Table size="sm" className="traj-table">
        <caption className="visually-hidden">
          Rung each goal's claim reached on every profiled run
        </caption>
        <TableHead>
          <TableRow>
            <TableHeader scope="col" className="traj-corner">
              Run
            </TableHeader>
            {runs.map((r) => (
              <TableHeader key={r.index} scope="col" className={currentClass(r, current)}>
                <button
                  type="button"
                  aria-pressed={r.index === current}
                  title={`Show run ${r.index}`}
                  onClick={() => onPick(r.index)}
                >
                  {r.index}
                </button>
              </TableHeader>
            ))}
            <TableHeader scope="col" className="traj-now">
              On Run {current}
            </TableHeader>
          </TableRow>
        </TableHead>
        <TableBody>
          {goals.map((goal) => (
            <TableRow key={goal}>
              <th scope="row">{title(goal)}</th>
              {runs.map((r) => {
                const g = claimOn(r, goal);
                const lvl = rungLevel(g);
                const text = rungText(g);
                return (
                  <TableCell
                    key={r.index}
                    className={currentClass(r, current)}
                    title={`${title(goal)}, run ${r.index}: ${text}`}
                    onClick={() => onPick(r.index)}
                  >
                    {lvl == null ? (
                      <span className={g ? "traj-none is-abstained" : "traj-none"} />
                    ) : (
                      <span className="traj-bar" style={{ "--lvl": lvl }} />
                    )}
                    <span className="visually-hidden">{text}</span>
                  </TableCell>
                );
              })}
              <TrajNow g={claimOn(picked, goal)} />
            </TableRow>
          ))}
          {runs.some(left) && (
            <TableRow className="traj-exit">
              <th scope="row">Left the Island</th>
              {runs.map((r) => (
                <TableCell
                  key={r.index}
                  className={currentClass(r, current)}
                  title={left(r) ? `Run ${r.index}: left the island` : `Run ${r.index}: stayed on`}
                  onClick={() => onPick(r.index)}
                >
                  {left(r) && <Icon name="alert" size={14} />}
                  <span className="visually-hidden">{left(r) ? "yes" : "no"}</span>
                </TableCell>
              ))}
              <TableCell className="traj-now">{left(picked) ? "yes" : <i>no</i>}</TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>
    </div>
  );
};

// The selectable runs, oldest first, for a run with no claims to tabulate. A run
// that left the island carries a red mark under its number.
export const GoalRunPicker = ({ runs, current, onPick }) => (
  <div className="goal-runs" role="group" aria-label="Profiled run">
    <span>Run</span>
    {runs.map((r) => (
      <SelectableTag
        key={r.index}
        size="sm"
        className={`goal-run${left(r) ? " is-exit" : ""}`}
        text={String(r.index)}
        selected={r.index === current}
        title={`Show run ${r.index}${left(r) ? " (left the island)" : ""}`}
        onClick={() => onPick(r.index)}
      />
    ))}
  </div>
);
