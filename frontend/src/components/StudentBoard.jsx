// The left of the board: which logs it listens to, the counts, the track form,
// and one card per tracked student.
import React from "react";
import { Button, Select, SelectItem, TextInput } from "@carbon/react";
import { StudentCard } from "./StudentCard";

// "a; b ;a;" -> ["a", "b"]: IDs never contain spaces, so any whitespace is noise.
const parseIds = (text) => [
  ...new Set(
    text
      .split(";")
      .map((s) => s.replace(/\s/g, ""))
      .filter(Boolean),
  ),
];

const TrackForm = ({ zanyStudy, onTrack }) => {
  const [query, setQuery] = React.useState("");
  return (
    <form
      className="track-form"
      onSubmit={async (e) => {
        e.preventDefault();
        const ids = parseIds(query);
        if (ids.length === 0) return;
        await onTrack(ids);
        setQuery("");
      }}
    >
      <TextInput
        id="track-ids"
        size="md"
        labelText={zanyStudy ? "Track participant IDs" : "Track student IDs"}
        hideLabel
        placeholder={zanyStudy ? `Track participant IDs in ${zanyStudy.code}` : "Track student IDs"}
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />
      <Button type="submit" size="md" disabled={!query.trim()}>
        Track
      </Button>
    </form>
  );
};

export const StudentBoard = ({
  students,
  headline,
  alertCount,
  sources,
  zanyStudy,
  onTrack,
  onTrackEveryone,
  onOpen,
  onPresence,
  onPick,
  onRemove,
}) => (
  <section className="student-board" aria-label="Students">
    <div className="board-heading">
      <h2>Students</h2>
      {sources.enabled && (
        <Select
          id="board-source"
          className="source-pick"
          inline
          size="md"
          labelText="Listening to"
          value={sources.current}
          onChange={(e) => sources.pick(e.target.value)}
        >
          {sources.items.map((it) => (
            <SelectItem key={it.id} value={it.id} text={it.text} />
          ))}
        </Select>
      )}
      <span>
        {students.length} tracked, {students.filter((b) => b.present).length} present,{" "}
        {students.filter((b) => b.picked).length} picked
      </span>
      <a className="feed-jump cds--link" href="#interventions">
        View Alerts ({alertCount})
      </a>
      <TrackForm zanyStudy={zanyStudy} onTrack={onTrack} />
      {zanyStudy && (
        <Button kind="ghost" size="md" onClick={onTrackEveryone}>
          Track everyone in {zanyStudy.code}
        </Button>
      )}
    </div>
    {students.length === 0 ? (
      <div className="board-empty">
        <h3>Start with Your First Student</h3>
        <p>No students added yet. Enter student IDs above to start.</p>
        <Button kind="tertiary" onClick={() => document.getElementById("track-ids").focus()}>
          Track a Student
        </Button>
      </div>
    ) : (
      <div className="student-grid">
        {students.map((b) => (
          <StudentCard
            key={b.studentID}
            student={b}
            trigger={headline[b.studentID]}
            onOpen={() => onOpen(b.studentID)}
            onPresence={(present) => onPresence(b.studentID, present)}
            onPick={(picked) => onPick(b.studentID, picked)}
            onRemove={() => onRemove(b.studentID)}
          />
        ))}
      </div>
    )}
  </section>
);
