// Where this board listens: Reflecks (VEXcode VR), or one ZANY study
// ("zany:STUDY-0001"). ZANY's logs need the research login, which the server
// checks with ATLAS. Picking a source changes it for the whole board, so the
// board reloads (`onChanged`) after a switch.
import React from "react";
import api from "../api";

const REFLECKS = "reflecks";
const ZANY = "zany:";
const NO_ZANY = { enabled: false, unlocked: false, studies: [] };
const CLOSED_FORM = { email: "", password: "", error: null, busy: false };

export function useBoardSource(notify, onChanged) {
  const [source, setSource] = React.useState(REFLECKS);
  const [zany, setZany] = React.useState(NO_ZANY);
  const [unlock, setUnlock] = React.useState(null); // the login form's state while open

  React.useEffect(() => {
    api
      .get("/api/zany/")
      .then((r) => setZany({ ...NO_ZANY, ...r.data }))
      .catch(() => {}); // ZANY's store is down: Reflecks keeps working
    api
      .get("/api/source/")
      .then((r) => setSource(r.data.source || REFLECKS))
      .catch(() => {});
    // The server says this browser's ZANY unlock ran out: ask for the login again.
    const locked = () => {
      setZany((z) => ({ ...z, unlocked: false }));
      setUnlock((u) => u || CLOSED_FORM);
    };
    window.addEventListener("zany:locked", locked);
    return () => window.removeEventListener("zany:locked", locked);
  }, []);

  const study = source.startsWith(ZANY)
    ? zany.studies.find((s) => `${ZANY}${s.study}` === source) || {
        study: source.slice(ZANY.length),
        code: source.slice(ZANY.length),
      }
    : null;

  const items = [
    { id: REFLECKS, text: "VEXcode VR" },
    ...(zany.unlocked
      ? zany.studies.map((s) => ({ id: `${ZANY}${s.study}`, text: `ZANY (${s.code})` }))
      : [{ id: "unlock", text: "ZANY (sign in to see studies)" }]),
  ];
  // A ZANY board already set, but this browser locked: keep it in the list so it shows.
  if (study && !items.some((it) => it.id === source))
    items.push({ id: source, text: `ZANY (${study.code}, locked)` });

  const pick = async (id) => {
    if (id === "unlock") {
      setUnlock(CLOSED_FORM);
      return;
    }
    if (id === source) return;
    try {
      setSource((await api.post("/api/source/", { source: id })).data.source || id);
      onChanged();
    } catch (err) {
      if (err.response?.status !== 403) notify("error", "Source not changed", "Try again.");
    }
  };

  const submitUnlock = async () => {
    if (!unlock || unlock.busy || !unlock.email || !unlock.password) return;
    setUnlock((u) => ({ ...u, busy: true, error: null }));
    try {
      const { data } = await api.post("/api/zany/unlock/", {
        email: unlock.email,
        password: unlock.password,
      });
      setZany((z) => ({ ...z, unlocked: true, studies: data.studies || [] }));
      setUnlock(null);
      notify("success", "ZANY unlocked", "Pick a study from the source list.");
      if (source.startsWith(ZANY)) onChanged();
    } catch (err) {
      setUnlock(
        (u) =>
          u && {
            ...u,
            busy: false,
            password: "",
            error: err.response?.data?.detail || "Not checked. Try again.",
          },
      );
    }
  };

  return {
    enabled: zany.enabled,
    current: source,
    items,
    study,
    pick,
    unlock,
    editUnlock: (patch) => setUnlock((u) => ({ ...u, ...patch, error: null })),
    closeUnlock: () => setUnlock(null),
    submitUnlock,
  };
}
