// The reading column of the goal board, shared by goal rows and rubric rows.
import { Pips } from "./marks";
import { humanize } from "./text";

// Column captions for a board of rows.
export const BoardHead = ({ first, current }) => (
  <div className="goal-cols" aria-hidden="true">
    <span>{first}</span>
    <span>On Run {current}</span>
  </div>
);

// One row's reading: pips, the rung written out, "step n of N", and the rung
// above it (what the next step would be). `reached` -1 replaces all of it with
// the honest `none` line.
export const GoalReading = ({ labels, reached, word, none, chips }) => (
  <div className="goal-reading">
    {reached === -1 ? (
      <p className="goal-now">
        <Pips n={Math.max(labels.length, 3)} reached={-1} />
        <span className="goal-none">{none}</span>
        {chips}
      </p>
    ) : (
      <>
        <p className="goal-now">
          <Pips n={labels.length} reached={reached} />
          <strong>{word}</strong>
          <span className="goal-of">
            step {reached + 1} of {labels.length}
          </span>
          {chips}
        </p>
        <p className="goal-next">
          {reached < labels.length - 1 ? (
            <>
              Next step up <b>{humanize(labels[reached + 1])}</b>
            </>
          ) : (
            "Highest step reached"
          )}
        </p>
      </>
    )}
  </div>
);

// A caption line under a reading: quiet [label, value] facts, empty ones dropped.
export const GoalFacts = ({ facts }) => {
  const shown = facts.filter(([, v]) => v != null && v !== "");
  if (shown.length === 0) return null;
  return (
    <p className="goal-facts">
      {shown.map(([k, v]) => (
        <span key={k || "value"}>
          {k && `${k} `}
          <b>{v}</b>
        </span>
      ))}
    </p>
  );
};
