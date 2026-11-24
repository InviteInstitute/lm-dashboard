// The dashboard: one live board of tracked students for a room of researchers.
//
// It reads the API the daemon keeps current and lays it out as a grid of
// student cards (left), a "needs intervention" feed (right), and a sheet with
// one student's full detail and notes. Nothing is computed here that the daemon
// already worked out. Every researcher action writes straight through to the
// API (see useSafeWrite), which never writes back to production.
import React from "react";
import api from "./api";
import { TRIGGERS } from "./constants";
import { AlertFeed } from "./components/AlertFeed";
import { AppHeader } from "./components/AppHeader";
import { ResetModal, UnlockModal } from "./components/Modals";
import { StudentSheet } from "./components/sheet/StudentSheet";
import { StudentBoard } from "./components/StudentBoard";
import { Toasts, useToasts } from "./components/Toasts";
import { useBoardData } from "./hooks/useBoardData";
import { useBoardSource } from "./hooks/useBoardSource";
import { useSafeWrite } from "./hooks/useSafeWrite";
import { useStudentDetail } from "./hooks/useStudentDetail";
import { useTheme } from "./hooks/useTheme";
import { triggerDownload } from "./lib/download";
import { headlineTriggers, statusMeta } from "./lib/status";

const ALL_TRIGGERS_ON = Object.fromEntries(Object.keys(TRIGGERS).map((t) => [t, true]));

const switchText = (s) =>
  `${s.kind === "casing" ? "casing changed" : "new class"}: ${s.from} -> ${s.to}`;

const CohortDashboard = () => {
  const board = useBoardData();
  const { states, roster, setRoster, triggers, setTriggers, switches } = board;
  const [selected, setSelected] = React.useState(null); // the student whose sheet is open
  const [theme, toggleTheme] = useTheme();
  const toast = useToasts();
  const safeWrite = useSafeWrite(toast.notify, board.streaming);
  const sheet = useStudentDetail(selected, board.visible, states, triggers);
  const sources = useBoardSource(toast.notify, () => {
    setSelected(null);
    board.reload();
  });
  const [resetOpen, setResetOpen] = React.useState(false);

  // The most recent casing of a handle (the feeds carry the canonical ID).
  const displayFor = (sid) => (states[sid] && states[sid].display) || sid;

  // Toast each new identity switch. The first answer after the board loads (or
  // reloads, after a reset or a source change) is the backlog: it is marked as
  // seen without a toast, so opening the board doesn't flood it.
  const seenSwitch = React.useRef(new Set());
  const backlogSeen = React.useRef(false);
  React.useEffect(() => {
    if (!board.switchesLoaded) {
      backlogSeen.current = false;
      return;
    }
    const fresh = switches.filter((s) => !s.acknowledged && !seenSwitch.current.has(s.id));
    fresh.forEach((s) => seenSwitch.current.add(s.id));
    if (!backlogSeen.current) {
      backlogSeen.current = true;
      return;
    }
    fresh.forEach((s) =>
      toast.push({ id: s.id, kind: "warning", title: displayFor(s.studentID), sub: switchText(s) }),
    );
  }, [switches, board.switchesLoaded]); // eslint-disable-line react-hooks/exhaustive-deps

  // Polling and the trigger types are set only here (the daemon just reads
  // them), so they are fetched once, not polled: a poll in flight during a
  // click would land a moment later with the old value and flip the control
  // back. The control is the source of truth after the first load.
  const [pollingOn, setPollingOn] = React.useState(true);
  const [triggerCfg, setTriggerCfg] = React.useState(ALL_TRIGGERS_ON);
  const fetchPolling = React.useCallback(async () => {
    try {
      setPollingOn((await api.get("/api/polling/")).data.enabled);
    } catch {
      /* keep */
    }
  }, []);
  const fetchTriggerCfg = React.useCallback(async () => {
    try {
      setTriggerCfg((await api.get("/api/triggers/config/")).data.enabled);
    } catch {
      /* keep */
    }
  }, []);
  React.useEffect(() => {
    fetchPolling();
    fetchTriggerCfg();
  }, [fetchPolling, fetchTriggerCfg]);

  // ---- actions: each updates the board first, then saves, and on failure
  // puts the board back to what the server says ----

  const togglePolling = async () => {
    const next = !pollingOn;
    setPollingOn(next);
    try {
      const r = await safeWrite(`polling ${next ? "on" : "off"}`, { enabled: next }, () =>
        api.post("/api/polling/", { enabled: next }),
      );
      setPollingOn(r.data.enabled);
    } catch {
      fetchPolling();
    }
  };

  const toggleTrigger = async (type) => {
    const next = !triggerCfg[type];
    setTriggerCfg((c) => ({ ...c, [type]: next }));
    const body = { trigger_type: type, enabled: next };
    try {
      const r = await safeWrite(`trigger ${type} ${next ? "on" : "off"}`, body, () =>
        api.post("/api/triggers/config/", body),
      );
      setTriggerCfg(r.data.enabled);
      // The API filters this board's feed by these switches, and a switch change
      // doesn't wake the live stream, so fetch the feed now: a type switched back
      // on brings its current alerts back.
      board.fetchTriggers();
    } catch {
      fetchTriggerCfg();
    }
  };

  const setRosterField = (sid, patch) =>
    setRoster((rs) => rs.map((r) => (r.studentID === sid ? { ...r, ...patch } : r)));

  const setPresence = async (sid, present) => {
    setRosterField(sid, { present });
    const body = { studentID: sid, present };
    try {
      await safeWrite(`${present ? "present" : "absent"}: ${sid}`, body, () =>
        api.post("/api/presence/", body),
      );
    } catch {
      board.fetchRoster();
    }
  };

  // A pick from an alert records which alert prompted it; a card pick has none.
  const setPicked = async (sid, picked, trigger = null) => {
    setRosterField(sid, { picked });
    const body = {
      studentID: sid,
      picked,
      source: trigger ? "intervention" : "roster",
      trigger_id: trigger?.id ?? null,
      trigger_type: trigger?.trigger_type ?? null,
    };
    try {
      await safeWrite(`${picked ? "pick" : "unpick"}: ${sid}`, body, () =>
        api.post("/api/picked/", body),
      );
    } catch {
      board.fetchRoster();
    }
  };

  // A typed note is the most irreplaceable input on the board: it either lands
  // or is parked in the outbox with a red toast, never dropped.
  const addNote = async (sid, text, trigger = null) => {
    const t = (text || "").trim();
    if (!sid || !t) return;
    const body = { studentID: sid, text: t };
    if (trigger) {
      body.trigger_id = trigger.id;
      body.trigger_type = trigger.trigger_type;
    }
    try {
      await safeWrite(`note on ${sid}`, body, () => api.post("/api/notes/", body));
    } catch {
      /* parked in the outbox; the toast already said so */
    }
    if (sid === selected) sheet.refreshNotes();
  };

  const dismissAlert = async (id) => {
    setTriggers((ts) => ts.filter((t) => t.id !== id));
    try {
      await safeWrite(`dismiss alert #${id}`, { id }, () => api.post("/api/triggers/ack/", { id }));
    } catch {
      board.fetchTriggers();
    }
  };

  const dismissSwitch = async (id) => {
    board.dropSwitch(id);
    toast.dismiss(id);
    try {
      await safeWrite(`dismiss switch #${id}`, { id }, () =>
        api.post("/api/switches/ack/", { id }),
      );
    } catch {
      board.fetchSwitches();
    }
  };

  // Each ID is tracked on its own, so one failure doesn't sink the rest.
  const track = async (ids) => {
    await Promise.all(
      ids.map((sid) =>
        safeWrite(`track: ${sid}`, { studentID: sid }, () =>
          api.post("/api/tracked/", { studentID: sid }),
        ).catch(() => {}),
      ),
    );
    board.fetchRoster();
  };

  const trackEveryone = async () => {
    if (!sources.study) return;
    try {
      const { data } = await api.get("/api/zany/participants/", {
        params: { study: sources.study.study },
      });
      await track(data.participants);
    } catch {
      toast.notify("error", "Not tracked", "ZANY's participant list didn't load. Try again.");
    }
  };

  const untrack = async (sid) => {
    const body = { studentID: sid, remove: true };
    try {
      await safeWrite(`untrack: ${sid}`, body, () => api.post("/api/tracked/", body));
    } catch {
      board.fetchRoster();
    }
    setRoster((r) => r.filter((x) => x.studentID !== sid));
    if (selected === sid) setSelected(null);
    board.fetchStates();
  };

  const exportData = async () => {
    try {
      // The zip comes back as a Blob, named by the server's Content-Disposition.
      const res = await api.post("/api/export/", null, { responseType: "blob" });
      const name =
        res.headers["content-disposition"]?.match(/filename="(.+)"/)?.[1] ||
        "lm-dashboard_export.zip";
      triggerDownload(res.data, name);
    } catch {
      toast.notify("error", "Export failed", "Nothing was downloaded. Try again.");
    }
  };

  const reset = async () => {
    try {
      const { data } = await api.post("/api/reset/");
      // The server now hides everything from before the reset; clear what is
      // shown at once so nothing lingers until the refetch lands.
      setSelected(null);
      toast.clear();
      board.reload();
      toast.notify("success", "Board reset", `Backup saved to ${data.backup || "exports/"}`);
    } catch {
      toast.notify("error", "Reset failed", "Nothing was cleared.");
      board.refetch();
    }
  };

  // ---- what the board shows ----

  // One card per tracked student, merged with its state. Present students come
  // first, then by ID, so a card never jumps when its own data refreshes.
  const students = roster
    .map((r) => ({
      studentID: r.studentID,
      display: r.display || r.studentID,
      has_data: r.has_data,
      present: r.present !== false,
      picked: !!r.picked,
      st: states[r.studentID] || null,
    }))
    .sort((a, b) =>
      a.present === b.present ? a.studentID.localeCompare(b.studentID) : a.present ? -1 : 1,
    );

  // Alerts for tracked, present students with the trigger type on. A student
  // who left the room would otherwise send someone to an empty seat. The feed
  // also keeps a resolved alert for seven minutes (the API's
  // TRIGGER_RECENT_SECONDS), so it doesn't vanish the moment a student recovers.
  const tracked = new Set(roster.map((r) => r.studentID));
  const absent = new Set(roster.filter((r) => r.present === false).map((r) => r.studentID));
  const alerts = triggers.filter(
    (t) =>
      tracked.has(t.studentID) && !absent.has(t.studentID) && triggerCfg[t.trigger_type] !== false,
  );
  const headline = headlineTriggers(alerts);
  const pickedIds = new Set(roster.filter((r) => r.picked).map((r) => r.studentID));

  return (
    <div className="dashboard">
      <AppHeader
        pollingOn={pollingOn}
        onTogglePolling={togglePolling}
        triggerCfg={triggerCfg}
        onToggleTrigger={toggleTrigger}
        onExport={exportData}
        onReset={() => setResetOpen(true)}
        theme={theme}
        onToggleTheme={toggleTheme}
      />
      <UnlockModal
        unlock={sources.unlock}
        onChange={sources.editUnlock}
        onSubmit={sources.submitUnlock}
        onClose={sources.closeUnlock}
      />
      <ResetModal open={resetOpen} onClose={() => setResetOpen(false)} onConfirm={reset} />

      <main className="dashboard-main">
        <StudentBoard
          students={students}
          headline={headline}
          alertCount={alerts.length}
          sources={sources}
          zanyStudy={sources.study}
          onTrack={track}
          onTrackEveryone={trackEveryone}
          onOpen={setSelected}
          onPresence={setPresence}
          onPick={(sid, picked) => setPicked(sid, picked)}
          onRemove={untrack}
        />
        <AlertFeed
          alerts={alerts}
          switches={switches.filter((s) => !s.acknowledged)}
          isPicked={(sid) => pickedIds.has(sid)}
          displayFor={displayFor}
          onOpen={setSelected}
          onDismiss={dismissAlert}
          onPick={(t, picked) => setPicked(t.studentID, picked, t)}
          onAddNote={(t, text) => addNote(t.studentID, text, t)}
          onDismissSwitch={dismissSwitch}
        />
      </main>

      <Toasts toasts={toast.toasts} onClose={toast.dismiss} />

      {selected && (
        <StudentSheet
          s={sheet.detail}
          sid={selected}
          status={statusMeta(headline[selected], !!sheet.detail)}
          loading={sheet.loading}
          history={sheet.history}
          notes={sheet.notes}
          onAddNote={(text) => addNote(selected, text)}
          onClose={() => setSelected(null)}
        />
      )}
    </div>
  );
};

export default CohortDashboard;
