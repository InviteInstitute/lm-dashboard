// The drill-down for one student, a modal sheet over the right of the board so
// the cohort stays in view. A sticky header (ID, status, counts, close), then two
// columns: the evidence (activity strips, program, goal evidence) on the left,
// and the researcher's own record (notes, trigger history) in a rail on the right.
import React from "react";
import { IconButton, SkeletonText, Tag } from "@carbon/react";
import { Close } from "@carbon/icons-react";
import { STATUS_OK } from "../../constants";
import { signal } from "../../lib/status";
import { EpisodeTrack, RunTrack } from "../ActivityTracks";
import { GoalEvidence } from "../goals/GoalEvidence";
import { CodePane } from "./CodePane";
import { NotesPanel } from "./NotesPanel";
import { Section } from "./Section";
import { TriggerHistory } from "./TriggerHistory";

const StatusBadge = ({ status }) => (
  <Tag size="md" className="status-tag" style={{ "--tone": signal(status.c) }}>
    {status.label}
  </Tag>
);

const Header = ({ s, sid, status, onClose }) => (
  <header className="sd-head">
    <div className="sd-who">
      <h2 id="sd-title" tabIndex={-1}>
        {(s && s.display) || sid}
      </h2>
      {s && <StatusBadge status={status || STATUS_OK} />}
    </div>
    {s && (
      <dl className="sd-facts">
        <div>
          <dt>runs</dt>
          <dd>{s.run_count ?? 0}</dd>
        </div>
        <div>
          <dt>events</dt>
          <dd>{s.event_count ?? 0}</dd>
        </div>
        {s.classCode && (
          <div>
            <dt>class</dt>
            <dd>{s.classCode}</dd>
          </div>
        )}
      </dl>
    )}
    <IconButton
      kind="ghost"
      size="lg"
      align="left"
      className="sd-close"
      label="Close student details"
      onClick={onClose}
    >
      <Close size={20} />
    </IconButton>
  </header>
);

const NoActivity = ({ sid, loading }) => (
  <div className="sd-empty sd-empty-lead">
    {loading ? (
      <>
        <span className="visually-hidden">Loading activity...</span>
        <SkeletonText heading width="30%" />
        <SkeletonText paragraph lineCount={4} />
      </>
    ) : (
      <>
        No activity yet for <b className="sd-id">{sid}</b>. Notes can still be added.
      </>
    )}
  </div>
);

// `s` is the student's full state (null until it loads, or when they have no
// activity yet); `sid` is their ID, which is always known.
export const StudentSheet = ({ s, sid, status, loading, history, notes, onAddNote, onClose }) => {
  const dialog = React.useRef(null);
  // Open as a modal, start on the student's name so a screen reader announces it
  // first, and give focus back to whatever opened the sheet when it closes.
  React.useEffect(() => {
    if (!dialog.current || dialog.current.open) return undefined;
    const opener = document.activeElement;
    dialog.current.showModal();
    dialog.current.querySelector("#sd-title")?.focus();
    return () => {
      if (opener instanceof HTMLElement && opener.isConnected) opener.focus();
    };
  }, []);
  return (
    <dialog
      ref={dialog}
      className="student-dialog"
      aria-labelledby="sd-title"
      onCancel={onClose}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="student-detail">
        <Header s={s} sid={sid} status={status} onClose={onClose} />
        <div className="sd-body">
          <div className="sd-main">
            {!s ? (
              <NoActivity sid={sid} loading={loading} />
            ) : (
              <>
                <Section title="Activity">
                  <div className="sd-strips">
                    <span className="sd-strip-label">Episodes</span>
                    <div>
                      <EpisodeTrack data={s.episodes} />
                    </div>
                    <span className="sd-strip-label">Runs</span>
                    <div>
                      <RunTrack data={s.runs} />
                    </div>
                  </div>
                </Section>
                {/* keyed by student, so the code view and run pick reset when the sheet switches students */}
                <CodePane key={`code-${sid}`} block={s.block} />
                <GoalEvidence key={sid} runs={s.goal_runs} enabled={s.goal_recognition_enabled} />
              </>
            )}
          </div>
          <aside className="sd-rail">
            <NotesPanel key={sid} notes={notes} onAdd={onAddNote} />
            <TriggerHistory history={history} />
          </aside>
        </div>
      </div>
    </dialog>
  );
};
