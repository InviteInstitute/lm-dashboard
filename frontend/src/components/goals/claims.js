// Reading the goal_strategy engine's per-run output: which goals a run made a
// claim about, where each claim sits on its ladder, and what backs it.
import { count, humanize, pct } from "./text";

// A claim's rung as a 0..1 fraction of its ladder, or null for no reading.
export const rungLevel = (g) => {
  const labels = (g && g.rungs) || [];
  const i = labels.indexOf(g && g.rung);
  return i === -1 ? null : labels.length > 1 ? i / (labels.length - 1) : 1;
};

// Goals in first-seen order across the runs' claims, then any goal that only
// shows up in indicators, rung changes or sensor tests.
export const goalOrder = (runs) => {
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

// The claim a run made about one goal, if any.
export const claimOn = (r, goal) =>
  ((r && r.rollup && r.rollup.goals) || []).find((g) => g.goal === goal);

// The facts behind one claim, as [label, value] pairs: the test-world tally and
// debris numbers for a claim from tests, else the indicator rungs it came from.
export const claimFacts = (g) => {
  const d = g.debris || {};
  if (g.source !== "battery")
    return Object.entries(g.basis || {}).map(([k, v]) => [
      humanize(k),
      v == null ? "n/a" : humanize(v),
    ]);
  const noTests = !g.n_valid && !g.n_abstained;
  return [
    [
      "",
      noTests
        ? null
        : `${count(g.n_valid || 0, "test counted", "tests counted")}, ${g.n_abstained || 0} inconclusive`,
    ],
    ["pieces cleared", Number.isFinite(d.proportion_cleared) ? pct(d.proportion_cleared) : null],
    [
      "zone coverage",
      Number.isFinite(d.zone_coverage)
        ? `${pct(d.zone_coverage)}${d.zone_coverage_band ? ` (${humanize(d.zone_coverage_band)})` : ""}`
        : null,
    ],
    [
      "weight cleared",
      Number.isFinite(d.weight_cleared_kg)
        ? `${Math.round(d.weight_cleared_kg)} kg${d.weight_cleared_band ? ` (${humanize(d.weight_cleared_band)})` : ""}`
        : null,
    ],
  ];
};

// The flags that qualify a claim: why its certainty is reduced, then the engine's flags.
export const claimFlags = (g) => {
  if (!g) return [];
  const reduced = g.source === "battery" && g.certainty && g.certainty !== "full";
  const reasons = reduced
    ? (g.certainty_reasons || []).length
      ? g.certainty_reasons
      : [`${g.certainty} certainty`]
    : [];
  return [...reasons, ...(g.flags || [])];
};

// One run's evidence, gathered per goal in `order`, keeping only goals the run
// says something about.
export const evidenceByGoal = (run, order) => {
  const battery = run.battery;
  const scenarios = (battery && battery.eligible && battery.scenarios) || [];
  const events = (run.timeline && run.timeline.events) || [];
  const later = (run.timeline && run.timeline.post_exit_events) || [];
  return order
    .map((goal) => ({
      goal,
      claim: claimOn(run, goal),
      indicators: ((run.goals || []).find((g) => g.goal === goal) || {}).indicators || [],
      changes: events.filter((e) => e.goal === goal),
      laterChanges: later.filter((e) => e.goal === goal),
      scenarios: scenarios.filter((sc) => (sc.goal || null) === goal),
    }))
    .filter(
      (b) =>
        b.claim ||
        b.indicators.length ||
        b.changes.length ||
        b.laterChanges.length ||
        b.scenarios.length,
    );
};
