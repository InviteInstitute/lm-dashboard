// One tracked student on the board: their ID and status, the last few runs and
// episodes, and the present / picked / untrack controls. A card only changes
// colour when the student is in an alert state.
import { IconButton, SelectableTag, SkeletonText, Tag, Tile } from "@carbon/react";
import { Checkmark, Close } from "@carbon/icons-react";
import { statusMeta, toneVars } from "../lib/status";
import { clockTime, relTime } from "../lib/time";
import { EpisodeTrack, RunTrack } from "./ActivityTracks";

// A pick toggle, on a card or an alert: the researcher's mark for a student
// they picked or interviewed.
export const PickTag = ({ picked, onToggle }) => (
  <SelectableTag
    size="md"
    className="is-pick"
    text={picked ? "Picked" : "Mark Picked"}
    renderIcon={picked ? Checkmark : undefined}
    selected={picked}
    title={picked ? "Picked / interviewed - click to unmark" : "Mark as picked / interviewed"}
    onClick={(e) => {
      e.stopPropagation();
      onToggle();
    }}
  />
);

// `student` is a roster row merged with its state (`st`, null before any activity).
export const StudentCard = ({ student: b, trigger, onOpen, onPresence, onPick, onRemove }) => {
  const sm = statusMeta(trigger, !!b.st);
  return (
    <Tile
      className={`student-card${trigger ? " is-alert" : ""}${b.present ? "" : " is-absent"}`}
      style={trigger ? toneVars(sm.c) : undefined}
      onClick={onOpen}
    >
      <div className="card-head">
        <button className="student-open card-id" title={b.display} onClick={onOpen}>
          {b.display}
        </button>
        {trigger ? (
          <Tag size="sm" className="status-tag card-status">
            {sm.label}
          </Tag>
        ) : (
          <span className="card-status">{sm.label}</span>
        )}
      </div>
      {b.st ? (
        <>
          <div className="card-strips">
            <span>Runs</span>
            <RunTrack data={b.st.runs} compact />
            <span>Episodes</span>
            <EpisodeTrack data={b.st.episodes} compact />
          </div>
          <div className="card-meta">
            <span>
              {b.st.run_count} runs, {b.st.event_count} events
            </span>
            {b.st.last_seen && (
              <span title={`Last activity ${clockTime(b.st.last_seen)}`}>
                {relTime(b.st.last_seen)} ago
              </span>
            )}
          </div>
        </>
      ) : (
        <div className="card-wait">
          {b.has_data ? <SkeletonText paragraph lineCount={2} /> : "Waiting for activity..."}
        </div>
      )}
      <div className="card-actions">
        <SelectableTag
          size="md"
          text={b.present ? "Present" : "Absent"}
          selected={b.present}
          title={b.present ? "Mark absent (drops to the bottom, dimmed)" : "Mark present"}
          onClick={(e) => {
            e.stopPropagation();
            onPresence(!b.present);
          }}
        />
        <PickTag picked={b.picked} onToggle={() => onPick(!b.picked)} />
        <IconButton
          kind="ghost"
          size="sm"
          align="top-end"
          className="card-remove"
          label={`Stop tracking ${b.display}`}
          onClick={(e) => {
            e.stopPropagation();
            onRemove();
          }}
        >
          <Close />
        </IconButton>
      </div>
    </Tile>
  );
};
