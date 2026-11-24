// The researcher's notes on one student: the composer first (it is why most
// people open the sheet), then the saved notes, newest first.
import React from "react";
import { Button, ContainedList, ContainedListItem, TextArea } from "@carbon/react";
import { triggerMeta } from "../../lib/status";
import { fullTime, noteTime, parseTs } from "../../lib/time";
import { Section } from "./Section";

export const NotesPanel = ({ notes, onAdd }) => {
  const [draft, setDraft] = React.useState("");
  const save = () => {
    const t = draft.trim();
    if (!t) return;
    onAdd(t);
    setDraft("");
  };
  return (
    <Section
      title="Notes"
      aside={notes.length > 0 && <span className="sd-count">{notes.length}</span>}
    >
      <div className="sd-composer">
        <TextArea
          id="sd-new-note"
          labelText="New note"
          hideLabel
          rows={4}
          value={draft}
          placeholder="What did you see or hear?"
          helperText="Ctrl+Enter to save"
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
              e.preventDefault();
              save();
            }
          }}
        />
        <Button size="sm" onClick={save} disabled={!draft.trim()}>
          Save Note
        </Button>
      </div>
      {notes.length === 0 ? (
        <p className="sd-empty">No notes on this student yet.</p>
      ) : (
        <ContainedList label="Saved, newest first" kind="on-page" size="sm" className="sd-notes">
          {[...notes].reverse().map((n) => (
            <ContainedListItem key={n.id}>
              <div className="sd-note-meta">
                <time dateTime={parseTs(n.ts)?.toISOString()} title={fullTime(n.ts)}>
                  {noteTime(n.ts)}
                </time>
                {n.trigger_type && <span>during {triggerMeta(n.trigger_type).label}</span>}
              </div>
              <p>{n.text}</p>
            </ContainedListItem>
          ))}
        </ContainedList>
      )}
    </Section>
  );
};
