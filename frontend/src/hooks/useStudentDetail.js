// What the sheet shows for the open student: their full state (program and goal
// evidence included), their notes and their trigger history. Switching students
// clears all three at once, so the sheet never shows the previous student's data
// while the new fetches are in flight. A failed refresh keeps what is shown.
import React from "react";
import api from "../api";

// `states` and `triggers` are the board's live data: when either changes, the
// detail and the history refetch on the same beat, so the open sheet stays
// current without a timer of its own.
export function useStudentDetail(sid, visible, states, triggers) {
  const [detail, setDetail] = React.useState(null);
  const [loadedFor, setLoadedFor] = React.useState(null); // the student whose fetch last settled
  const [notes, setNotes] = React.useState([]);
  const [history, setHistory] = React.useState([]);

  React.useEffect(() => {
    setDetail(null);
    setHistory([]);
  }, [sid]);

  React.useEffect(() => {
    if (!sid) return undefined;
    if (!visible) return undefined; // tab hidden: keep the open detail, just stop refreshing it
    let alive = true;
    (async () => {
      try {
        const d = (await api.get(`/api/student_states/${encodeURIComponent(sid)}/`)).data;
        if (alive) setDetail(d);
      } catch {
        /* keep the last good payload */
      }
      if (alive) setLoadedFor(sid);
    })();
    return () => {
      alive = false; // a late answer for a student no longer open is dropped
    };
  }, [sid, visible, states]);

  React.useEffect(() => {
    if (!sid) return undefined;
    let alive = true;
    api
      .get("/api/triggers/history/", { params: { studentID: sid } })
      .then((r) => {
        if (alive) setHistory(r.data.history || []);
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [sid, triggers]);

  const refreshNotes = React.useCallback(async () => {
    if (!sid) return;
    try {
      setNotes((await api.get("/api/notes/", { params: { studentID: sid } })).data.notes || []);
    } catch {
      /* a blip must not look like "no notes" */
    }
  }, [sid]);
  React.useEffect(() => {
    setNotes([]);
    refreshNotes();
  }, [refreshNotes]);

  return { detail, loading: !detail && loadedFor !== sid, notes, history, refreshNotes };
}
