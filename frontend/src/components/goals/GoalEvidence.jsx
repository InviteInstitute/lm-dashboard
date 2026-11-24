// Goal evidence in the student sheet: per-run goal recognition from the
// agent-lm goal_strategy engine, for Castle Crashers runs only. For each run,
// where every goal's claim landed, with its uncertainty flags. This is evidence
// with explicit abstentions, not a score or an assessment of the student's
// ability: the flags are the whole point.
//
// A history table on top shows every goal on every run (its headers pick the
// run). Below it, one board row per goal on the picked run, then the leftover
// sensor tests and the execution rubric.
import React from "react";
import { Tag } from "@carbon/react";
import { WarningAlt } from "@carbon/icons-react";
import { Section } from "../sheet/Section";
import { GoalBattery } from "./Battery";
import { GoalBlock } from "./GoalBlock";
import { GoalRunPicker, GoalTrajectory } from "./GoalTrajectory";
import { claimOn, evidenceByGoal, goalOrder } from "./claims";
import { GoalLegend } from "./marks";
import { BoardHead } from "./Reading";
import { RubricRow } from "./RubricRow";
import { RunSummary } from "./RunSummary";
import { sensorBlocks } from "./text";

// A sub-part of the section (the rubric, leftover sensor tests).
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
      <Section title="Goal Evidence">
        <p className="sd-empty">Goal recognition is switched off.</p>
      </Section>
    );
  if (list.length === 0)
    return (
      <Section title="Goal Evidence">
        <p className="sd-empty">
          No Castle Crashers runs profiled yet (goal evidence is Castle Crashers only).
        </p>
      </Section>
    );
  // Show one run: the latest, or the one picked while it still exists.
  const run = list.find((r) => r.index === picked) || list[list.length - 1];
  const latest = list[list.length - 1].index;
  const order = goalOrder(list);
  const claimed = order.filter((goal) => list.some((r) => claimOn(r, goal)));
  const battery = run.battery;
  const onRun = evidenceByGoal(run, order);
  const unmapped = ((battery && battery.eligible && battery.scenarios) || []).filter(
    (sc) => !sc.goal || !order.includes(sc.goal),
  );
  const dims = (run.rubric && run.rubric.dimensions) || [];
  return (
    <Section
      title="Goal Evidence"
      aside={
        <span className="sd-count">
          <span>Run {run.index}</span>
          {run.index === latest && list.length > 1 && <span> (latest)</span>}
        </span>
      }
    >
      <p className="goal-intro">Each goal, run by run. Pick a run to see what backs it up.</p>
      {claimed.length > 0 ? (
        <GoalTrajectory runs={list} goals={claimed} current={run.index} onPick={setPicked} />
      ) : (
        list.length > 1 && <GoalRunPicker runs={list} current={run.index} onPick={setPicked} />
      )}
      <RunSummary
        run={run}
        sensors={sensorBlocks(battery)}
        noSensors={Boolean(battery && !battery.eligible)}
      />
      {onRun.length > 0 && (
        <div className="goals">
          <BoardHead first="Goal" current={run.index} />
          {onRun.map((b) => (
            <GoalBlock key={b.goal} {...b} />
          ))}
        </div>
      )}
      {unmapped.length > 0 && (
        <GoalPart title="Other Test Worlds">
          <GoalBattery battery={{ ...battery, scenarios: unmapped, qualifying_blocks: [] }} />
        </GoalPart>
      )}
      {dims.length > 0 && (
        <GoalPart
          title="Execution Rubric"
          aside={
            <Tag
              size="sm"
              type="warm-gray"
              renderIcon={WarningAlt}
              title={`Still being checked by people, so treat it as a draft (${run.rubric.status || "provisional"})`}
            >
              provisional
            </Tag>
          }
        >
          <p className="goal-intro">
            How well the code is put together, separate from which goals the robot reaches.
          </p>
          <div className="goals">
            <BoardHead first="Dimension" current={run.index} />
            {dims.map((d) => (
              <RubricRow key={d.dimension} d={d} />
            ))}
          </div>
        </GoalPart>
      )}
      <GoalLegend />
    </Section>
  );
};
