// Run-level outcomes the per-goal rows don't carry. Leaving the island is a
// critical failure (not a goal), so it gets the same red tint an alerted card
// does. Everything else is a quiet line of notes.
import { Icon } from "../../icons";
import { TRIGGERS } from "../../constants";
import { toneVars } from "../../lib/status";
import { useFlags } from "./marks";
import { andList, count, humanize, sensorName } from "./text";

export const RunSummary = ({ run, sensors = [], noSensors = false }) => {
  const s = run.summary || {};
  const notes = [];
  const verdict = humanize(s.fidelity_verdict).toLowerCase();
  if (verdict === "agree" || verdict === "disagree") notes.push(`Simulation and GPS ${verdict}.`);
  else if (verdict && verdict !== "not applicable") notes.push(`Simulation vs GPS: ${verdict}.`);
  if (s.outcome_available === false) notes.push("No robot telemetry for this run yet.");
  if (s.fabricated_motion) notes.push("Some motion was fabricated.");
  if (s.orphan_block_count)
    notes.push(
      `${count(s.orphan_block_count, "block isn't", "blocks aren't")} attached to the program.`,
    );
  if (sensors.length > 0) notes.push(`Uses the ${andList(sensors.map(sensorName))}.`);
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
