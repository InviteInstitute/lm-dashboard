// The sensor-test battery: each scenario drops the program into a designed test
// world and records per-check evidence. Pass, conditional and fail are verdicts.
// "Measured" checks carry a value instead (the share of pieces cleared, say).
// "Abstained" means the run never reached what the check tests. Scenarios are
// grouped by family (t1 debris field, t2 boundary, ...). Only programs that read
// a sensor are eligible.
import { Accordion, AccordionItem } from "@carbon/react";
import { CheckDot } from "./marks";
import {
  checkState,
  checkWord,
  fmtGoalVal,
  humanize,
  pct,
  scenarioBlurb,
  sensorBlocks,
  sentence,
} from "./text";

const BatteryCheck = ({ c }) => {
  const state = checkState(c);
  const measured = state === "measured" && Number.isFinite(c.value);
  const detail =
    state === "abstained"
      ? `inconclusive: ${humanize(c.abstain_reason) || "not reached"}`
      : `${state}${c.detail ? ` (${c.detail})` : ""}`;
  return (
    <span className={`battery-check is-${state}`} title={`${humanize(c.name)}: ${detail}`}>
      <CheckDot state={state} />
      {humanize(c.name)}
      {measured && (
        <b className="battery-value">
          {c.value >= 0 && c.value <= 1 ? pct(c.value) : fmtGoalVal(c.value)}
        </b>
      )}
      {c.capped && <span className="battery-capped">capped</span>}
    </span>
  );
};

// How a family's checks came out, as dot + count pairs (verdicts, then the rest).
const TALLY_ORDER = ["pass", "conditional", "fail", "measured", "abstained"];
const BatteryTally = ({ scenarios }) => {
  const n = {};
  scenarios.forEach((sc) =>
    (sc.checks || []).forEach((c) => {
      const st = checkState(c);
      n[st] = (n[st] || 0) + 1;
    }),
  );
  return (
    <span className="battery-tally">
      {TALLY_ORDER.filter((st) => n[st]).map((st) => (
        <span key={st} title={`${n[st]} ${checkWord(st)}`}>
          <CheckDot state={st} />
          {n[st]} {checkWord(st)}
        </span>
      ))}
    </span>
  );
};

// Test worlds and their checks. `showFamily` labels each world with its family,
// for lists that are not already grouped under a family header.
export const ScenarioList = ({ scenarios, showFamily = false }) => (
  <ul className="battery-scenarios">
    {scenarios.map((sc, si) => (
      <li key={`${sc.scenario_id}-${sc.construct}-${si}`}>
        <div className="battery-scenario-head">
          {showFamily && (
            <span className="battery-family-tag">{sentence(sc.family || "other")}</span>
          )}
          <span className="battery-scenario-id">{humanize(sc.scenario_id)}</span>
          {scenarioBlurb(sc) && <span title={sc.description}>{scenarioBlurb(sc)}</span>}
        </div>
        <div className="battery-checks">
          {(sc.checks || []).map((c, ci) => (
            <BatteryCheck key={ci} c={c} />
          ))}
        </div>
      </li>
    ))}
  </ul>
);

export const GoalBattery = ({ battery }) => {
  if (!battery) return null;
  if (!battery.eligible)
    return <p className="sd-empty">Not applicable: this program uses no sensors.</p>;
  const families = [];
  (battery.scenarios || []).forEach((sc) => {
    const key = sc.family || "other";
    let fam = families.find((f) => f.key === key);
    if (!fam) families.push((fam = { key, scenarios: [] }));
    fam.scenarios.push(sc);
  });
  const sensors = sensorBlocks(battery);
  return (
    <div className="battery">
      {sensors.length > 0 && <p className="battery-reads">Sensor blocks: {sensors.join(", ")}</p>}
      <Accordion size="sm" align="start" className="battery-families">
        {families.map((fam) => (
          <AccordionItem
            key={fam.key}
            className="battery-family"
            title={
              <span className="battery-family-head">
                <span className="battery-family-name">{sentence(fam.key)}</span>
                <span className="battery-family-count">
                  {fam.scenarios.length} {fam.scenarios.length === 1 ? "test world" : "test worlds"}
                </span>
                <BatteryTally scenarios={fam.scenarios} />
              </span>
            }
          >
            <ScenarioList scenarios={fam.scenarios} />
          </AccordionItem>
        ))}
      </Accordion>
    </div>
  );
};
