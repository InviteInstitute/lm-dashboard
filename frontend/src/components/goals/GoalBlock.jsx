// One goal on the picked run: a board row (the goal, where its claim sits on
// its ladder), then the evidence behind it on demand: the indicators, the rung
// changes and the sensor tests.
import { Accordion, AccordionItem } from "@carbon/react";
import { ScenarioList } from "./Battery";
import { claimFacts, claimFlags } from "./claims";
import { ChannelMark, RungLadder, useFlags } from "./marks";
import { GoalFacts, GoalReading } from "./Reading";
import { count, fmtGoalVal, humanize, title } from "./text";

// One indicator: channel mark, name, value and flags, then the rung ladder it
// climbed, or an honest note when there is no rung to place: an abstention
// (dashed, no reading) or a meaningful absence (solid, it never happened).
const IndicatorRow = ({ ind }) => {
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
  const flags = useFlags(ind.flags);
  return (
    <div className="indicator">
      <div className="indicator-head">
        <ChannelMark channel={ind.channel} />
        <span className="indicator-name">{humanize(ind.name)}</span>
        <span className="indicator-side">
          {val != null && showLadder && <span className="indicator-value">{val}</span>}
          {flags.chip}
        </span>
      </div>
      {flags.list}
      {ind.abstained ? (
        <div className="goal-noreading">
          no reading - {humanize(ind.abstain_reason) || "no data"}
        </div>
      ) : absent ? (
        <div className="goal-noreading is-absent">{humanize(ind.rung)} (not attempted)</div>
      ) : showLadder ? (
        <RungLadder labels={labels} reached={reached} />
      ) : (
        <div className="goal-noreading">no reading</div>
      )}
    </div>
  );
};

// One rung change: the step, what moved, from -> to, and its flags.
const TimelineRow = ({ e, faded }) => {
  const flags = useFlags(e.flags);
  return (
    <li className={faded ? "is-faded" : undefined}>
      <span className="tl-step">step {e.step}</span>
      <span className="tl-what">{humanize(e.indicator)}</span>
      <span className="tl-change">
        {humanize(e.from_rung) || "start"} &rarr; {humanize(e.to_rung)}
      </span>
      {flags.chip}
      {flags.list}
    </li>
  );
};

// The moments a block moved one of the goal's indicators to another rung.
// Changes after the robot left the island are listed apart, dimmed.
const Timeline = ({ changes, laterChanges }) => (
  <>
    <ol className="goal-timeline">
      {changes.map((e, i) => (
        <TimelineRow key={`e${i}`} e={e} />
      ))}
    </ol>
    {laterChanges.length > 0 && (
      <>
        <p className="goal-timeline-sub">After Leaving the Island</p>
        <ol className="goal-timeline">
          {laterChanges.map((e, i) => (
            <TimelineRow key={`p${i}`} e={e} faded />
          ))}
        </ol>
      </>
    )}
  </>
);

// A labelled group inside the evidence (achieved, attempting, progress, test worlds).
const Role = ({ label, children }) => (
  <div className="goal-role">
    <span className="goal-role-label">{label}</span>
    {children}
  </div>
);

const Evidence = ({ indicators, changes, laterChanges, scenarios }) => {
  const attained = indicators.filter((i) => i.role === "attainment");
  const intent = indicators.filter((i) => i.role !== "attainment");
  return (
    <div className="goal-evidence-body">
      {[
        ["achieved", attained],
        ["attempting", intent],
      ]
        .filter(([, list]) => list.length > 0)
        .map(([role, list]) => (
          <Role key={role} label={role}>
            <div>
              {list.map((ind, i) => (
                <IndicatorRow key={i} ind={ind} />
              ))}
            </div>
          </Role>
        ))}
      {changes.length + laterChanges.length > 0 && (
        <Role label="progress">
          <div>
            <Timeline changes={changes} laterChanges={laterChanges} />
          </div>
        </Role>
      )}
      {scenarios.length > 0 && (
        <Role label="test worlds">
          <ScenarioList scenarios={scenarios} showFamily />
        </Role>
      )}
    </div>
  );
};

export const GoalBlock = ({ goal, claim, indicators, changes, laterChanges, scenarios }) => {
  const nChanges = changes.length + laterChanges.length;
  const summary = [
    indicators.length && count(indicators.length, "signal", "signals"),
    scenarios.length && count(scenarios.length, "test world", "test worlds"),
    nChanges && count(nChanges, "step change", "step changes"),
  ].filter(Boolean);
  const flags = useFlags(claimFlags(claim));
  const labels = (claim && claim.rungs) || [];
  const fromTests = claim && claim.source === "battery";
  const noTests = fromTests && !claim.n_valid && !claim.n_abstained;
  return (
    <article className="goal">
      <div className="goal-row">
        <div className="goal-name">
          <h4>{title(goal)}</h4>
          {claim && (
            <span
              className="goal-source"
              title={
                fromTests
                  ? "Worked out by running the program in a set of test worlds"
                  : "Worked out from what the code and the run show (this goal has no test worlds)"
              }
            >
              {fromTests ? "From Test Worlds" : "From Code and Runs"}
            </span>
          )}
        </div>
        {claim ? (
          <GoalReading
            labels={labels}
            reached={labels.indexOf(claim.rung)}
            word={humanize(claim.rung)}
            none={`no reading - ${noTests ? "no test worlds ran" : humanize(claim.abstain_reason) || "no evidence"}`}
            chips={flags.chip}
          />
        ) : (
          <div className="goal-reading">
            <p className="goal-noclaim">Not assessed on this run.</p>
          </div>
        )}
      </div>
      {flags.list}
      {claim && <GoalFacts facts={claimFacts(claim)} />}
      {summary.length > 0 && (
        <Accordion size="sm" align="start" className="goal-evidence">
          <AccordionItem
            open={!claim || undefined}
            title={
              <>
                Evidence
                <span className="goal-evidence-count">{summary.join(", ")}</span>
              </>
            }
          >
            <Evidence
              indicators={indicators}
              changes={changes}
              laterChanges={laterChanges}
              scenarios={scenarios}
            />
          </AccordionItem>
        </Accordion>
      )}
    </article>
  );
};
