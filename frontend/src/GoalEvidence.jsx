// Goal evidence, the panel inside the student sheet: per-run goal recognition
// from the agent-lm goal_strategy engine, its sensor battery, goal claims and the
// provisional rubric.
import React from "react";
import { Icon } from "./icons";
import { T, MONO, TRIGGERS, toneVars } from "./constants";
import { Section } from "./Section";

// ---------------- goal evidence (inside modal) ----------------
// Per-run goal recognition from the agent-lm goal_strategy engine: for each
// profiled Castle Crashers run, the goals with the rung reached and the
// uncertainty flags. This is EVIDENCE with explicit abstentions, not a score or
// an assessment of the student's ability -- the flags are the whole point.
const _humanize = (s) => (s || "").replace(/_/g, " ");
// "clear_debris_zone" -> "Clear debris zone": sentence case for goal names in prose.
const _sentence = (s) => {
  const h = _humanize(s);
  return h.charAt(0).toUpperCase() + h.slice(1);
};
// "remain_on_island" -> "Remain on Island": title case for goal names used as headers.
const MINOR_WORDS = new Set([
  "a",
  "an",
  "and",
  "at",
  "by",
  "for",
  "in",
  "of",
  "on",
  "or",
  "the",
  "to",
  "vs",
  "with",
]);
const _title = (s) =>
  _humanize(s)
    .split(" ")
    .map((w, i) => (i > 0 && MINOR_WORDS.has(w) ? w : w.charAt(0).toUpperCase() + w.slice(1)))
    .join(" ");

// Goal-evidence styling. Restrained on colour on purpose: this is evidence, not
// a score. Each indicator is drawn as the rung ladder it climbed this run: a
// segmented bar, weaker (left) to stronger (right), filled up to the reached
// rung, with the rung names underneath. A rung reads as a position on a scale,
// never as good/bad. Abstentions and meaningful absences get an honest note
// instead of a fake rung; uncertainty is an amber flag, provenance a quiet one.
const goalChip = {
  display: "inline-flex",
  alignItems: "center",
  fontSize: 12,
  lineHeight: "18px",
  borderRadius: 6,
  padding: "0 7px",
  whiteSpace: "nowrap",
};
const goalFlagChip = {
  ...goalChip,
  color: "var(--lmd-warning)",
  border: "1px solid color-mix(in srgb, var(--lmd-warning) 45%, transparent)",
  background: "color-mix(in srgb, var(--lmd-warning) 8%, transparent)",
};
const goalProvenanceChip = {
  ...goalChip,
  color: T.sub,
  border: `1px solid ${T.border}`,
};
// Uncertainty flags qualify the reading (amber); every other flag is provenance
// (where the reading came from). The engine names its hedges by what they are,
// so classify on those words rather than a list that goes stale.
const UNCERTAIN_FLAG =
  /unverified|assumed|estimated|stale|fallback|marginal|defaulted|disagreement|sparse|invalid|fabricated|capped|override|unknown|certainty/;

// However many flags a row carries, it gets one chip: the most important flag
// (uncertainty before provenance) plus a count. The chip opens the full list
// inline below the row, so nothing is hover-only and nothing wraps into a
// second line of chips. `allUncertain` for lists that are hedges by definition
// (a claim's certainty reasons, run diagnostics).
// Engine flag names in plain words, for readers who don't know the engine. The
// raw name stays in the tooltip; anything not listed is just de-underscored.
const FLAG_TEXT = {
  sparse_evidence: "little evidence",
  sim_unverified: "simulation not confirmed",
  simulated_fallback: "simulated, not seen",
  simulated_attainment: "reached in simulation only",
  gps_invalid: "GPS data unusable",
  invalid_timestamp: "bad timestamps",
  loop_capped: "loop cut short",
  duration_imputed: "timing estimated",
  early_stop_outcome: "run stopped early",
  evidence_post_sim_exit: "after leaving the island",
  band_model_disagreement: "methods disagree",
  attachment_boundary_marginal: "attachment borderline",
  unknown_reporter: "unrecognized block",
  foreign_playground_block: "block from another playground",
  fabricated_motion: "motion filled in",
};
const _flagText = (f) => FLAG_TEXT[f] || _humanize(f);

function useFlags(flags, allUncertain = false) {
  const [open, setOpen] = React.useState(false);
  const all = [...new Set(flags || [])];
  if (all.length === 0) return { chip: null, list: null };
  const unc = all.filter((f) => allUncertain || UNCERTAIN_FLAG.test(f));
  const prov = all.filter((f) => !unc.includes(f));
  const ordered = [...unc, ...prov];
  const cls = `flag-chip${unc.length ? " is-uncertain" : ""}`;
  const chip =
    ordered.length === 1 ? (
      <span
        className={cls}
        title={`${unc.length ? "Uncertain" : "Where this came from"} (${ordered[0]})`}
      >
        <span className="flag-name">{_flagText(ordered[0])}</span>
      </span>
    ) : (
      <button
        type="button"
        className={cls}
        aria-expanded={open}
        title={open ? "Hide flags" : `All flags: ${ordered.map(_flagText).join(", ")}`}
        onClick={(e) => {
          e.stopPropagation();
          setOpen((o) => !o);
        }}
      >
        <span className="flag-name">{_flagText(ordered[0])}</span>
        <span className="flag-more">+{ordered.length - 1}</span>
      </button>
    );
  const list = open && ordered.length > 1 && (
    <dl className="flag-list">
      {unc.length > 0 && (
        <div>
          <dt>Uncertain</dt>
          <dd>{unc.map(_flagText).join(", ")}</dd>
        </div>
      )}
      {prov.length > 0 && (
        <div>
          <dt>Source</dt>
          <dd>{prov.map(_flagText).join(", ")}</dd>
        </div>
      )}
    </dl>
  );
  return { chip, list };
}

// An indicator with no rung to place: an abstention (dashed, no reading) or a
// meaningful absence (solid, the thing never happened). Never a fake rung.
const goalNoReadingPill = (absent) => ({
  fontSize: 13,
  color: absent ? T.sub : T.faint,
  border: absent ? `1px solid ${T.border}` : `1px dashed ${T.border}`,
  borderRadius: 6,
  padding: "3px 10px",
  background: absent ? T.track : "transparent",
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

// A rung ladder: a segmented bar weaker -> stronger, filled up to the reached
// rung (the reached segment solid, the ones below it lighter), names underneath.
const RungLadder = ({ labels, reached }) => (
  <ol className="rungs" style={{ gridTemplateColumns: `repeat(${labels.length}, minmax(0, 1fr))` }}>
    {labels.map((label, i) => (
      <li
        key={label}
        className={i === reached ? "is-reached" : i < reached ? "is-climbed" : undefined}
        aria-current={i === reached ? "true" : undefined}
        title={_humanize(label)}
      >
        {_humanize(label)}
      </li>
    ))}
  </ol>
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
  const flags = useFlags(ind.flags);
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
            gap: 8,
            minWidth: 0,
          }}
        >
          {val != null && showLadder && (
            <span
              style={{
                fontFamily: MONO,
                fontSize: 12,
                color: T.faint,
                fontVariantNumeric: "tabular-nums",
              }}
            >
              {val}
            </span>
          )}
          {flags.chip}
        </span>
      </div>
      {flags.list}
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

const _count = (n, one, many) => `${n} ${n === 1 ? one : many}`;

// "optical near object" -> "optical sensor (near object)"
const _sensorName = (b) => {
  const [kind, ...check] = b.split(" ");
  return check.length ? `${kind} sensor (${check.join(" ")})` : `${kind} sensor`;
};
// ["a", "b", "c"] -> "a, b and c"
const _andList = (xs) =>
  xs.length < 2 ? xs.join("") : `${xs.slice(0, -1).join(", ")} and ${xs[xs.length - 1]}`;

// Run-level outcomes the per-goal rows don't carry. Leaving the island is a
// critical failure (not a goal), so it gets the same red tint an alerted card
// does; everything else is a quiet line of notes.
const GoalRunSummary = ({ run, sensors = [], noSensors = false }) => {
  const s = run.summary || {};
  const notes = [];
  const verdict = _humanize(s.fidelity_verdict).toLowerCase();
  if (verdict === "agree" || verdict === "disagree") notes.push(`Simulation and GPS ${verdict}.`);
  else if (verdict && verdict !== "not applicable") notes.push(`Simulation vs GPS: ${verdict}.`);
  if (s.outcome_available === false) notes.push("No robot telemetry for this run yet.");
  if (s.fabricated_motion) notes.push("Some motion was fabricated.");
  if (s.orphan_block_count)
    notes.push(
      `${_count(s.orphan_block_count, "block isn't", "blocks aren't")} attached to the program.`,
    );
  if (sensors.length > 0) notes.push(`Uses the ${_andList(sensors.map(_sensorName))}.`);
  if (noSensors) notes.push("Uses no sensors, so there are no test worlds to run.");
  // inherited_playground is routine bookkeeping, not worth showing here
  const diags = (run.diagnostics || []).filter((d) => d !== "inherited_playground");
  const diagFlags = useFlags(diags, true);
  if (!s.boundary_exceeded && notes.length === 0 && diags.length === 0) return null;
  return (
    <div className="goal-summary">
      {s.boundary_exceeded && (
        <p className="goal-critical" style={toneVars(TRIGGERS.wheel_spin.c)}>
          <Icon name="alert" size={15} />
          <span>
            Left the island
            {s.boundary_exit_step != null ? ` at step ${s.boundary_exit_step}` : ""}
            {s.boundary_exit_overridden ? " (outcome override)" : ""}
          </span>
        </p>
      )}
      {(notes.length > 0 || diags.length > 0) && (
        <p className="goal-notes">
          {notes.join(" ")}
          {diagFlags.chip}
        </p>
      )}
      {diagFlags.list}
    </div>
  );
};

// The goal-progression timeline: each row is a moment a block moved a goal's
// indicator from one rung to another (steps after leaving the island dimmed).
// One rung change: step, what moved, from -> to, and its flags.
const TimelineRow = ({ e, faded, showGoal }) => {
  const flags = useFlags(e.flags);
  return (
    <li className={faded ? "is-faded" : undefined}>
      <span className="tl-step">step {e.step}</span>
      <span className="tl-what">
        {showGoal ? `${_sentence(e.goal)}, ${_humanize(e.indicator)}` : _humanize(e.indicator)}
      </span>
      <span className="tl-change">
        {_humanize(e.from_rung) || "start"} &rarr; {_humanize(e.to_rung)}
      </span>
      {flags.chip}
      {flags.list}
    </li>
  );
};

const GoalTimeline = ({ timeline, showGoal = true }) => {
  const events = (timeline && timeline.events) || [];
  const post = (timeline && timeline.post_exit_events) || [];
  if (events.length === 0 && post.length === 0)
    return <p className="sd-empty">No step changes on this run.</p>;
  return (
    <>
      <ol className="goal-timeline">
        {events.map((e, i) => (
          <TimelineRow key={`e${i}`} e={e} showGoal={showGoal} />
        ))}
      </ol>
      {post.length > 0 && (
        <>
          <p className="goal-timeline-sub">After Leaving the Island</p>
          <ol className="goal-timeline">
            {post.map((e, i) => (
              <TimelineRow key={`p${i}`} e={e} faded showGoal={showGoal} />
            ))}
          </ol>
        </>
      )}
    </>
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
      ? "var(--lmd-signal-d0433c)"
      : st === "conditional"
        ? "var(--lmd-warning)"
        : T.sub;
const _checkState = (c) => (c.abstained || c.status === "abstained" ? "abstained" : c.status);
// "abstained" is engine vocabulary; readers know it as inconclusive.
const _checkWord = (st) => (st === "abstained" ? "inconclusive" : st);
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
      ? `inconclusive: ${_humanize(c.abstain_reason) || "not reached"}`
      : `${state}${c.detail ? ` (${c.detail})` : ""}`;
  return (
    <span className={`battery-check is-${state}`} title={`${_humanize(c.name)}: ${detail}`}>
      <CheckDot state={state} />
      {_humanize(c.name)}
      {measured && (
        <b className="battery-value">
          {c.value >= 0 && c.value <= 1 ? _pct(c.value) : fmtGoalVal(c.value)}
        </b>
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
    <span className="battery-tally">
      {order.map((st) => (
        <span key={st} title={`${n[st]} ${_checkWord(st)}`}>
          <CheckDot state={st} />
          {n[st]} {_checkWord(st)}
        </span>
      ))}
    </span>
  );
};

const GoalBattery = ({ battery }) => {
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
  const sensors = (battery.qualifying_blocks || []).map((b) =>
    _humanize(b.replace(/^pg_(sensing_)?/, "")),
  );
  return (
    <div className="battery">
      {sensors.length > 0 && <p className="battery-reads">Sensor blocks: {sensors.join(", ")}</p>}
      {families.map((fam) => (
        <details key={fam.key} className="battery-family">
          <summary>
            <span aria-hidden="true" className="goal-fam-caret">
              <Icon name="chevron" size={14} />
            </span>
            <span className="battery-family-name">{_familyLabel(fam.key)}</span>
            <span className="battery-family-count">
              {fam.scenarios.length} {fam.scenarios.length === 1 ? "test world" : "test worlds"}
            </span>
            <BatteryTally scenarios={fam.scenarios} />
          </summary>
          <ul className="battery-scenarios">
            {fam.scenarios.map((sc, si) => (
              <li key={`${sc.scenario_id}-${sc.construct}-${si}`}>
                <div className="battery-scenario-head">
                  <span className="battery-scenario-id">{_humanize(sc.scenario_id)}</span>
                  {_scenarioBlurb(sc) && <span title={sc.description}>{_scenarioBlurb(sc)}</span>}
                </div>
                <div className="battery-checks">
                  {(sc.checks || []).map((c, ci) => (
                    <BatteryCheck key={ci} c={c} />
                  ))}
                </div>
              </li>
            ))}
          </ul>
        </details>
      ))}
    </div>
  );
};

// ---- goal evidence: a board of goals ----
// A history table on top shows where every goal's claim landed on each run (its
// run headers pick the run). Below it, one row per goal on the picked run: the
// goal, and where its claim sits on its ladder (a pip meter plus the rung written
// out, "2 of 4", and the next rung up). The indicators, rung changes and sensor
// tests behind a claim sit under the row, on demand. The execution rubric reuses
// the same row, so the whole section reads as one board.

// Rung position as a 0..1 fraction of its ladder, or null for no reading.
const _rungLevel = (g) => {
  const labels = (g && g.rungs) || [];
  const i = labels.indexOf(g && g.rung);
  return i === -1 ? null : labels.length > 1 ? i / (labels.length - 1) : 1;
};

// Goals in first-seen order across the runs' claims, then any goal that only
// shows up in indicators, rung changes or sensor tests.
const _goalOrder = (runs) => {
  const seen = [];
  const add = (goal) => goal && !seen.includes(goal) && seen.push(goal);
  runs.forEach((r) => ((r.rollup && r.rollup.goals) || []).forEach((g) => add(g.goal)));
  runs.forEach((r) => {
    (r.goals || []).forEach((g) => add(g.goal));
    ((r.timeline && r.timeline.events) || []).forEach((e) => add(e.goal));
    ((r.battery && r.battery.scenarios) || []).forEach((sc) => add(sc.goal));
  });
  return seen;
};

const _claimOn = (r, goal) =>
  ((r && r.rollup && r.rollup.goals) || []).find((g) => g.goal === goal);

// A ladder as a row of pips, weaker (left) to stronger (right): the reached rung
// solid, the ones below it lighter, the ones above it empty. `reached` -1 is no
// reading (every pip dashed). Decorative: the rung is always written out beside it.
const Pips = ({ n, reached }) => (
  <span className={`pips${reached === -1 ? " is-none" : ""}`} aria-hidden="true">
    {Array.from({ length: n }, (_, i) => (
      <i
        key={i}
        className={i === reached ? "is-reached" : i < reached ? "is-climbed" : undefined}
      />
    ))}
  </span>
);

// The selectable runs, oldest first. A run that left the island carries a red
// mark under its number, so the critical failure is findable from any run.
const GoalRunPicker = ({ runs, current, onPick }) => (
  <div className="goal-runs" role="group" aria-label="Profiled run">
    <span>Run</span>
    {runs.map((r) => {
      const out = r.summary && r.summary.boundary_exceeded;
      return (
        <button
          key={r.index}
          type="button"
          onClick={() => onPick(r.index)}
          className={`chip-btn goal-run${out ? " is-exit" : ""}`}
          aria-pressed={r.index === current}
          title={`Show run ${r.index}${out ? " (left the island)" : ""}`}
        >
          {r.index}
        </button>
      );
    })}
  </div>
);

// Where each goal's claim landed on every profiled run. A real table, so every
// value is readable without hover; the column headers pick the run.
// The picked run's rung for one goal, written out: the one-line state per row.
const TrajNow = ({ g }) => {
  const lvl = _rungLevel(g);
  return (
    <td className="traj-now">
      {g ? lvl == null ? <i>no reading</i> : _humanize(g.rung) : <i>not assessed</i>}
    </td>
  );
};

const GoalTrajectory = ({ runs, goals, current, onPick }) => {
  const wrap = React.useRef(null);
  React.useLayoutEffect(() => {
    if (wrap.current) wrap.current.scrollLeft = wrap.current.scrollWidth; // latest run in view
  }, [runs.length]);
  const anyExit = runs.some((r) => r.summary && r.summary.boundary_exceeded);
  return (
    <div className="traj" ref={wrap}>
      <table>
        <caption className="visually-hidden">
          Rung each goal's claim reached on every profiled run
        </caption>
        <thead>
          <tr>
            <th scope="col" className="traj-corner">
              Run
            </th>
            {runs.map((r) => (
              <th
                key={r.index}
                scope="col"
                className={r.index === current ? "is-current" : undefined}
              >
                <button
                  type="button"
                  aria-pressed={r.index === current}
                  title={`Show run ${r.index}`}
                  onClick={() => onPick(r.index)}
                >
                  {r.index}
                </button>
              </th>
            ))}
            <th scope="col" className="traj-now">
              On Run {current}
            </th>
          </tr>
        </thead>
        <tbody>
          {goals.map((goal) => (
            <tr key={goal}>
              <th scope="row">{_title(goal)}</th>
              {runs.map((r) => {
                const g = _claimOn(r, goal);
                const lvl = _rungLevel(g);
                const text = g ? (lvl == null ? "no reading" : _humanize(g.rung)) : "not assessed";
                return (
                  <td
                    key={r.index}
                    className={r.index === current ? "is-current" : undefined}
                    title={`${_title(goal)}, run ${r.index}: ${text}`}
                    onClick={() => onPick(r.index)}
                  >
                    {lvl == null ? (
                      <span className={g ? "traj-none is-abstained" : "traj-none"} />
                    ) : (
                      <span className="traj-bar" style={{ "--lvl": lvl }} />
                    )}
                    <span className="visually-hidden">{text}</span>
                  </td>
                );
              })}
              <TrajNow g={_claimOn(runs.find((r) => r.index === current) || {}, goal)} />
            </tr>
          ))}
          {anyExit && (
            <tr className="traj-exit">
              <th scope="row">Left the Island</th>
              {runs.map((r) => {
                const out = r.summary && r.summary.boundary_exceeded;
                return (
                  <td
                    key={r.index}
                    className={r.index === current ? "is-current" : undefined}
                    title={out ? `Run ${r.index}: left the island` : `Run ${r.index}: stayed on`}
                    onClick={() => onPick(r.index)}
                  >
                    {out && <Icon name="alert" size={14} />}
                    <span className="visually-hidden">{out ? "yes" : "no"}</span>
                  </td>
                );
              })}
              <td className="traj-now">
                {(runs.find((r) => r.index === current) || {}).summary?.boundary_exceeded ? (
                  "yes"
                ) : (
                  <i>no</i>
                )}
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
};

// The reading for one row: pips, the rung written out, "n of N", and the rung
// above it (what the next step would be). `none` replaces all of it with an
// honest no-reading line.
const GoalReading = ({ labels, reached, word, none, chips }) => (
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
              Next step up <b>{_humanize(labels[reached + 1])}</b>
            </>
          ) : (
            "Highest step reached"
          )}
        </p>
      </>
    )}
  </div>
);

// Where a rollup claim or rubric level was read from, as a short source name.
const _evidenceSource = (e) => {
  const [src, ...rest] = (e || "").split(".");
  const name = _humanize(rest.join(".")) || _humanize(src);
  const where = { production: "code", battery: "tests" }[src] || src;
  return rest.length ? `${where}: ${name}` : name;
};

// A caption line under a reading: quiet key/value facts. `lead` (where the claim
// comes from) opens the line.
const GoalFacts = ({ facts, lead }) => {
  const shown = facts.filter(([, v]) => v != null && v !== "");
  if (shown.length === 0 && !lead) return null;
  return (
    <p className="goal-facts">
      {lead}
      {shown.map(([k, v]) => (
        <span key={k || "value"}>
          {k && `${k} `}
          <b>{v}</b>
        </span>
      ))}
    </p>
  );
};

// The facts behind one goal's claim: tests (valid/abstained plus the debris
// numbers) or the indicator rungs it was derived from.
const claimFacts = (g) => {
  const fromTests = g.source === "battery";
  const d = g.debris || {};
  if (!fromTests)
    return Object.entries(g.basis || {}).map(([k, v]) => [
      _humanize(k),
      v == null ? "n/a" : _humanize(v),
    ]);
  const noTests = !g.n_valid && !g.n_abstained;
  return [
    [
      "",
      noTests
        ? null
        : `${_count(g.n_valid || 0, "test counted", "tests counted")}, ${g.n_abstained || 0} inconclusive`,
    ],
    ["pieces cleared", Number.isFinite(d.proportion_cleared) ? _pct(d.proportion_cleared) : null],
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
  ];
};

// The flags that qualify a claim: reduced certainty and engine flags (amber).
const claimFlags = (g) => {
  if (!g) return [];
  const reduced = g.source === "battery" && g.certainty && g.certainty !== "full";
  const reasons = reduced
    ? (g.certainty_reasons || []).length
      ? g.certainty_reasons
      : [`${g.certainty} certainty`]
    : [];
  return [...reasons, ...(g.flags || [])];
};

// The indicators, rung changes and sensor tests behind one goal, grouped by role.
const GoalEvidenceBody = ({ indicators, changes, laterChanges, scenarios }) => {
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
          <div key={role} className="goal-role">
            <span className="goal-role-label">{role}</span>
            <div>
              {list.map((ind, i) => (
                <GoalIndicatorRow key={i} ind={ind} />
              ))}
            </div>
          </div>
        ))}
      {changes.length + laterChanges.length > 0 && (
        <div className="goal-role">
          <span className="goal-role-label">progress</span>
          <div>
            <GoalTimeline
              timeline={{ events: changes, post_exit_events: laterChanges }}
              showGoal={false}
            />
          </div>
        </div>
      )}
      {scenarios.length > 0 && (
        <div className="goal-role">
          <span className="goal-role-label">test worlds</span>
          <ul className="battery-scenarios">
            {scenarios.map((sc, si) => (
              <li key={`${sc.scenario_id}-${sc.construct}-${si}`}>
                <div className="battery-scenario-head">
                  <span className="battery-family-tag">{_familyLabel(sc.family || "other")}</span>
                  <span className="battery-scenario-id">{_humanize(sc.scenario_id)}</span>
                  {_scenarioBlurb(sc) && <span title={sc.description}>{_scenarioBlurb(sc)}</span>}
                </div>
                <div className="battery-checks">
                  {(sc.checks || []).map((c, ci) => (
                    <BatteryCheck key={ci} c={c} />
                  ))}
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
};

// One goal on the selected run: a board row (name and source, reading),
// then its evidence on demand.
const GoalBlock = ({ goal, claim, indicators, changes, laterChanges, scenarios }) => {
  const summary = [
    indicators.length && _count(indicators.length, "signal", "signals"),
    scenarios.length && _count(scenarios.length, "test world", "test worlds"),
    changes.length + laterChanges.length &&
      _count(changes.length + laterChanges.length, "step change", "step changes"),
  ].filter(Boolean);
  const flags = useFlags(claimFlags(claim));
  const labels = (claim && claim.rungs) || [];
  const reached = claim ? labels.indexOf(claim.rung) : -1;
  const fromTests = claim && claim.source === "battery";
  const noTests = fromTests && !claim.n_valid && !claim.n_abstained;
  return (
    <article className="goal">
      <div className="goal-row">
        <div className="goal-name">
          <h4>{_title(goal)}</h4>
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
            reached={reached}
            word={_humanize(claim.rung)}
            none={`no reading - ${noTests ? "no test worlds ran" : _humanize(claim.abstain_reason) || "no evidence"}`}
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
        <details className="goal-evidence" open={!claim || undefined}>
          <summary>
            <span aria-hidden="true" className="goal-fam-caret">
              <Icon name="chevron" size={14} />
            </span>
            Evidence
            <span className="goal-evidence-count">{summary.join(", ")}</span>
          </summary>
          <GoalEvidenceBody
            indicators={indicators}
            changes={changes}
            laterChanges={laterChanges}
            scenarios={scenarios}
          />
        </details>
      )}
    </article>
  );
};

// The purpose-2 execution rubric: dimensions of HOW the program runs, each a
// level on 0..max, drawn as the same board row as a goal. Provisional upstream
// (still under human validation), so it is labelled as such and never reads as
// a grade.
const RubricRow = ({ d }) => {
  const labels = Array.from({ length: (d.max_level || 0) + 1 }, (_, i) => String(i));
  const chips = (
    <>
      {d.borderline && (
        <span style={goalFlagChip} title="within the borderline margin of the next level">
          borderline
        </span>
      )}
      {d.ceiling != null && d.ceiling < d.max_level && (
        <span style={goalProvenanceChip} title="the highest level this program's code can show">
          code allows up to {d.ceiling}
        </span>
      )}
    </>
  );
  return (
    <article className="goal">
      <div className="goal-row">
        <div className="goal-name">
          <h4>{_title(d.dimension)}</h4>
        </div>
        {d.level == null ? (
          <GoalReading
            labels={labels}
            reached={-1}
            none={`can't tell - ${_humanize(d.u_reason)}`}
            chips={chips}
          />
        ) : (
          <div className="goal-reading">
            <p className="goal-now">
              <Pips n={labels.length} reached={d.level} />
              <strong>level {d.level}</strong>
              <span className="goal-of">of {d.max_level}</span>
              {chips}
            </p>
          </div>
        )}
      </div>
      <GoalFacts
        facts={[
          ["based on", (d.evidence || []).map(_evidenceSource).join(", ") || null],
          ["counts against", (d.negatives || []).map(_evidenceSource).join(", ") || null],
        ]}
      />
    </article>
  );
};

// Column captions for a board of rows.
const BoardHead = ({ first, current }) => (
  <div className="goal-cols" aria-hidden="true">
    <span>{first}</span>
    <span>On Run {current}</span>
  </div>
);

// Legend for the channel marks the evidence uses.
const GoalLegend = () => (
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

// A sub-part of the goal-evidence section (the rubric, leftover sensor tests).
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
  // Focus one run (latest by default); honour a manual pick while it still exists.
  const run = list.find((r) => r.index === picked) || list[list.length - 1];
  const latest = list[list.length - 1].index;
  const order = _goalOrder(list);
  const claimed = order.filter((goal) => list.some((r) => _claimOn(r, goal)));
  const battery = run.battery;
  // This run's evidence, gathered per goal.
  const onRun = order
    .map((goal) => ({
      goal,
      claim: _claimOn(run, goal),
      indicators: ((run.goals || []).find((g) => g.goal === goal) || {}).indicators || [],
      changes: ((run.timeline && run.timeline.events) || []).filter((e) => e.goal === goal),
      laterChanges: ((run.timeline && run.timeline.post_exit_events) || []).filter(
        (e) => e.goal === goal,
      ),
      scenarios: ((battery && battery.eligible && battery.scenarios) || []).filter(
        (sc) => (sc.goal || null) === goal,
      ),
    }))
    .filter(
      (b) =>
        b.claim ||
        b.indicators.length ||
        b.changes.length ||
        b.laterChanges.length ||
        b.scenarios.length,
    );
  const unmapped = ((battery && battery.eligible && battery.scenarios) || []).filter(
    (sc) => !sc.goal || !order.includes(sc.goal),
  );
  const sensors = ((battery && battery.qualifying_blocks) || []).map((b) =>
    _humanize(b.replace(/^pg_(sensing_)?/, "")),
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
      <GoalRunSummary
        run={run}
        sensors={sensors}
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
            <span
              style={goalFlagChip}
              title={`Still being checked by people, so treat it as a draft (${run.rubric.status || "provisional"})`}
            >
              provisional
            </span>
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
