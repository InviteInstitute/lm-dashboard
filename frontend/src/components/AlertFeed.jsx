// The right of the board: who needs intervention now (the five triggers), then
// identity switches no one has dismissed yet. Each alert can be dismissed,
// picked, or noted on the spot.
import React from "react";
import { Button, IconButton, TextArea } from "@carbon/react";
import { Close } from "@carbon/icons-react";
import { TRIGGERS } from "../constants";
import { Icon } from "../icons";
import { toneVars, triggerMeta } from "../lib/status";
import { clockTime, fmtDur, fullTime, relTime } from "../lib/time";
import { PickTag } from "./StudentCard";

// The shared frame of a feed item: the student, how old, and dismiss.
const FeedItem = ({ tone, name, age, ageTitle, dismissLabel, onOpen, onDismiss, children }) => (
  <li className="feed-item" style={toneVars(tone)} onClick={onOpen}>
    <div className="feed-row">
      <button className="student-open feed-id" onClick={onOpen}>
        {name}
      </button>
      <span className="feed-age" title={ageTitle}>
        {age}
      </span>
      <IconButton
        kind="ghost"
        size="sm"
        align="left"
        label={dismissLabel}
        onClick={(e) => {
          e.stopPropagation();
          onDismiss();
        }}
      >
        <Close />
      </IconButton>
    </div>
    {children}
  </li>
);

const NoteEditor = ({ alert, name, onSave }) => {
  const [text, setText] = React.useState("");
  return (
    <div className="feed-note" onClick={(e) => e.stopPropagation()}>
      <TextArea
        id={`note-${alert.id}`}
        labelText={`Note on ${name}`}
        hideLabel
        rows={2}
        value={text}
        autoFocus
        placeholder="What did you see during this alert?"
        onChange={(e) => setText(e.target.value)}
      />
      <Button size="sm" disabled={!text.trim()} onClick={() => onSave(text)}>
        Save Note
      </Button>
    </div>
  );
};

export const AlertFeed = ({
  alerts,
  switches,
  isPicked,
  displayFor,
  onOpen,
  onDismiss,
  onPick,
  onAddNote,
  onDismissSwitch,
}) => {
  const [noteFor, setNoteFor] = React.useState(null); // the alert whose note editor is open
  return (
    <aside id="interventions" className="intervention-feed" aria-label="Needs Intervention">
      <div className="feed-head">
        <h2>Needs Intervention</h2>
        <span className="feed-count">{alerts.length}</span>
      </div>
      {alerts.length === 0 ? (
        <p className="feed-empty">No active alerts right now.</p>
      ) : (
        <ul className="feed-list">
          {alerts.map((t) => {
            const meta = triggerMeta(t.trigger_type);
            const name = displayFor(t.studentID);
            const picked = isPicked(t.studentID);
            return (
              <FeedItem
                key={t.id}
                tone={meta.c}
                name={name}
                age={t.age_seconds != null ? fmtDur(t.age_seconds) : "-"}
                ageTitle="How long this alert has been active"
                dismissLabel={`Dismiss alert for ${name} (also closes the note box)`}
                onOpen={() => onOpen(t.studentID)}
                onDismiss={() => {
                  if (noteFor === t.id) setNoteFor(null);
                  onDismiss(t.id);
                }}
              >
                <div className="feed-what">
                  <Icon name={meta.icon} size={14} />
                  <strong>{t.label || meta.label}</strong>
                  {t.value && <span>{t.value}</span>}
                </div>
                {t.prev && (
                  <div className="feed-prev">
                    Before this: {t.prev.label} at {clockTime(t.prev.at)} ({relTime(t.prev.at)} ago)
                  </div>
                )}
                <div className="feed-actions">
                  <PickTag picked={picked} onToggle={() => onPick(t, !picked)} />
                  <Button
                    kind="ghost"
                    size="sm"
                    aria-expanded={noteFor === t.id}
                    title="Add a note for this learner"
                    onClick={(e) => {
                      e.stopPropagation();
                      setNoteFor(noteFor === t.id ? null : t.id);
                    }}
                  >
                    Add Note
                  </Button>
                </div>
                {noteFor === t.id && (
                  <NoteEditor
                    alert={t}
                    name={name}
                    onSave={(text) => {
                      onAddNote(t, text);
                      setNoteFor(null);
                    }}
                  />
                )}
              </FeedItem>
            );
          })}
        </ul>
      )}

      {switches.length > 0 && (
        <>
          <div className="feed-head feed-head-sub">
            <h2>Identity Switches</h2>
            <span className="feed-count">{switches.length}</span>
          </div>
          <ul className="feed-list">
            {switches.map((s) => (
              <FeedItem
                key={s.id}
                tone={TRIGGERS.inactive.c}
                name={displayFor(s.studentID)}
                age={`${relTime(s.ts)} ago`}
                ageTitle={fullTime(s.ts)}
                dismissLabel={`Dismiss switch for ${displayFor(s.studentID)}`}
                onOpen={() => onOpen(s.studentID)}
                onDismiss={() => onDismissSwitch(s.id)}
              >
                <div className="feed-what">
                  <Icon name="swap" size={14} />
                  <strong>{s.kind === "casing" ? "casing changed" : "new class"}</strong>
                  <span>
                    {s.kind === "casing" ? s.from : s.from || "-"} -&gt; {s.to}
                  </span>
                </div>
              </FeedItem>
            ))}
          </ul>
        </>
      )}
    </aside>
  );
};
