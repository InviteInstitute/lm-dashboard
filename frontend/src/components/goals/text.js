// Engine names in words a researcher reads. The goal_strategy engine speaks in
// snake_case ("clear_debris_zone", "sim_unverified"); everything here turns its
// vocabulary into prose without changing what it says.

export const humanize = (s) => (s || "").replace(/_/g, " ");

// "clear_debris_zone" -> "Clear debris zone": sentence case for goal names in prose.
export const sentence = (s) => {
  const h = humanize(s);
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
export const title = (s) =>
  humanize(s)
    .split(" ")
    .map((w, i) => (i > 0 && MINOR_WORDS.has(w) ? w : w.charAt(0).toUpperCase() + w.slice(1)))
    .join(" ");

export const count = (n, one, many) => `${n} ${n === 1 ? one : many}`;

// ["a", "b", "c"] -> "a, b and c"
export const andList = (xs) =>
  xs.length < 2 ? xs.join("") : `${xs.slice(0, -1).join(", ")} and ${xs[xs.length - 1]}`;

export const pct = (v) => `${Math.round(v * 100)}%`;

// The continuous value behind a rung, shown small beside its name: one decimal
// at scale, a little more precision below 1, integers bare. Categorical values
// ("on_island") are humanized.
export const fmtGoalVal = (v) => {
  if (v == null || typeof v === "boolean") return null;
  if (typeof v === "string") return humanize(v);
  if (!Number.isFinite(v)) return null;
  if (Number.isInteger(v)) return String(v);
  if (Math.abs(v) < 0.005) return "0"; // float noise from the simulator, not a reading
  return Math.abs(v) >= 1 ? v.toFixed(1) : v.toPrecision(1);
};

// The sensor blocks a program reads: "pg_sensing_optical_near_object" -> "optical near object".
export const sensorBlocks = (battery) =>
  ((battery && battery.qualifying_blocks) || []).map((b) =>
    humanize(b.replace(/^pg_(sensing_)?/, "")),
  );

// "optical near object" -> "optical sensor (near object)"
export const sensorName = (b) => {
  const [kind, ...check] = b.split(" ");
  return check.length ? `${kind} sensor (${check.join(" ")})` : `${kind} sensor`;
};

// Where a rollup claim or rubric level was read from, as a short source name.
export const evidenceSource = (e) => {
  const [src, ...rest] = (e || "").split(".");
  const name = humanize(rest.join(".")) || humanize(src);
  const where = { production: "code", battery: "tests" }[src] || src;
  return rest.length ? `${where}: ${name}` : name;
};

// Flags: the engine names its hedges by what they are, so a flag reads as
// uncertainty when its name says so. Every other flag is provenance (where a
// value came from).
export const UNCERTAIN_FLAG =
  /unverified|assumed|estimated|stale|fallback|marginal|defaulted|disagreement|sparse|invalid|fabricated|capped|override|unknown|certainty/;

// Flag names in plain words. The raw name stays in the tooltip; anything not
// listed is just de-underscored.
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
export const flagText = (f) => FLAG_TEXT[f] || humanize(f);

// A sensor-test check's state. "abstained" is engine vocabulary; readers know
// it as inconclusive.
export const checkState = (c) => (c.abstained || c.status === "abstained" ? "abstained" : c.status);
export const checkWord = (st) => (st === "abstained" ? "inconclusive" : st);

// Scenario descriptions lead with the family and variant ("T2 boundary
// response - direct - head-on arrival, ..."), which the family header and
// scenario id already show. Keep just the part that says what is different
// about the world.
export const scenarioBlurb = (sc) => {
  const parts = (sc.description || "").split(/\s+—\s+/);
  const variant = humanize((sc.scenario_id || "").replace(/^t\d+[a-z]?_/, "")).toLowerCase();
  let i = 0;
  while (
    i < parts.length - 1 &&
    !parts[i].includes("(") &&
    (/^T\d/.test(parts[i]) || parts[i].toLowerCase() === variant)
  )
    i += 1;
  let rest = parts.slice(i).join(" - ");
  if (parts.length > 1 && i === parts.length - 1 && /^T\d/.test(parts[0])) {
    // "T4 debris configuration - dispersed." : nothing beyond the variant name
    if (rest.replace(/\.$/, "").toLowerCase() === variant) rest = "";
    // "near favorable (T4's world, tight clear rule)." : keep the aside
    else if (rest.toLowerCase().startsWith(`${variant} (`))
      rest = rest.slice(variant.length + 2).replace(/\)\.?$/, "");
  }
  return rest;
};
