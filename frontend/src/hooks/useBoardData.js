// The board's four live data sources (student states, roster, triggers, identity
// switches), kept current by the event stream, or by polling while it is down.
import React from "react";
import api from "../api";
import { CHANNELS, useEventStream, usePageVisible, usePoll } from "./useLiveUpdates";

// A fetch callback that stores `read(response data)` with `set`, and keeps what
// is shown when the request fails: a blip must never blank the board.
function useFetch(url, read, set) {
  return React.useCallback(async () => {
    try {
      set(read((await api.get(url)).data));
    } catch {
      /* keep what is shown */
    }
  }, [url, read, set]);
}

const byId = (data) => Object.fromEntries((data.students || []).map((s) => [s.studentID, s]));
const readRoster = (data) => data.tracked || [];
const readTriggers = (data) => data.triggers || [];
const readSwitches = (data) => data.switches || [];
const NONE = [];

export function useBoardData() {
  const visible = usePageVisible();
  const [states, setStates] = React.useState({}); // studentID -> light state payload
  const [roster, setRoster] = React.useState([]);
  const [triggers, setTriggers] = React.useState([]);
  // null until the first answer, so a caller can tell the backlog from new ones
  const [switches, setSwitches] = React.useState(null);

  const fetchStates = useFetch("/api/student_states/", byId, setStates);
  const fetchRoster = useFetch("/api/tracked/", readRoster, setRoster);
  const fetchTriggers = useFetch("/api/triggers/", readTriggers, setTriggers);
  const fetchSwitches = useFetch("/api/switches/", readSwitches, setSwitches);

  // Refetch only the channels the stream says moved. The stream and the poll
  // loops share the same fetch callbacks, so exactly one of them is live.
  const onStreamChanged = React.useCallback(
    (channels) => {
      if (channels.includes("states")) fetchStates();
      if (channels.includes("roster")) fetchRoster();
      if (channels.includes("triggers")) fetchTriggers();
      if (channels.includes("switches")) fetchSwitches();
    },
    [fetchStates, fetchRoster, fetchTriggers, fetchSwitches],
  );
  const streaming = useEventStream(onStreamChanged, visible);
  usePoll(fetchStates, visible && !streaming);
  usePoll(fetchRoster, visible && !streaming);
  usePoll(fetchTriggers, visible && !streaming);
  usePoll(fetchSwitches, visible && !streaming);

  const refetch = React.useCallback(() => onStreamChanged(CHANNELS), [onStreamChanged]);
  // Drop everything the board shows (after a reset or a source change), so
  // nothing old lingers until the fresh data lands.
  const reload = React.useCallback(() => {
    setStates({});
    setTriggers([]);
    setSwitches(null);
    refetch();
  }, [refetch]);

  return {
    visible,
    streaming,
    states,
    roster,
    setRoster,
    triggers,
    setTriggers,
    switches: switches || NONE,
    switchesLoaded: switches !== null,
    dropSwitch: React.useCallback(
      (id) => setSwitches((ss) => ss && ss.filter((s) => s.id !== id)),
      [],
    ),
    fetchStates,
    fetchRoster,
    fetchTriggers,
    fetchSwitches,
    refetch,
    reload,
  };
}
