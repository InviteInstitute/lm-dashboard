// The entire dashboard, in one component file.
//
// It polls the read API on a fixed timer and renders three things from what it
// gets back: a grid of per-student cards (strategy + episode sparklines, plus
// present/picked toggles), a "who needs help" alert column on the right, and a
// drill-down modal with the full detail and the notes log. Everything the user
// does writes straight through to the API; nothing is computed here, the daemon
// already did the work.
import React from 'react';
import api from './api';
import {
    T, FONT, MONO, STATE, NOSTATE, WHEEL_STATE, EP,
    HATCH_AMBER, PAUSE_FILL, PAUSE_LEGEND,
    TRIGGERS, TRIGGER_FALLBACK, TRIGGER_ROWS, POLL_MS, COMPACT_TAIL,
} from './constants';

// Re-exported so existing imports/tests that pull these from the component file
// keep working; the source of truth is ./constants.
export { COMPACT_TAIL } from './constants';

const triggerMeta = (type) => TRIGGERS[type] || TRIGGER_FALLBACK;

export function relTime(iso) {
    if (!iso) return '—';
    const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
    if (s < 60) return `${Math.round(s)}s`;
    if (s < 3600) return `${Math.round(s / 60)}m`;
    if (s < 86400) return `${Math.round(s / 3600)}h`;
    return `${Math.round(s / 86400)}d`;
}
export function fmtDur(s) {
    if (s == null) return '—';
    if (s < 60) return `${s.toFixed(1)}s`;
    if (s < 3600) return `${(s / 60).toFixed(1)}m`;
    return `${(s / 3600).toFixed(1)}h`;
}
export function stateMeta(st) {
    if (!st || st.current_state == null) return NOSTATE;
    return STATE[st.current_state] || NOSTATE;
}

// ---------------- timelines ----------------
// A "tile strip" of blocks. Each block is one unit -- an HMM run, or one EPISODE.
//
// Soft-fold (flush=true, episodes only): the hard/soft boundary idea. Soft
// boundaries -- the transitions BETWEEN consecutive work episodes -- are folded
// away: episodes sit flush, so a coding->run->coding stretch reads as ONE
// continuous activity strip (color changes mark the type). The ONLY breaks are
// HARD boundaries: the real pauses (INACTIVE / POST_RUN), drawn as a hatched gap
// with margin. So the bar shows "bursts of work separated by real pauses" rather
// than a gap after every episode. HMM runs keep their normal gapped look.
const leaf = (s, compact, flush) => {
    const r = flush ? 0 : 2;            // flush blocks are square; the strip rounds at its ends
    if (s.pause) return {
        flex: compact ? '0 0 5px' : '0 0 9px', borderRadius: r, background: s.bg,
        ...(flush ? { marginInline: compact ? 3 : 5 } : {}),   // hard boundary == the only break
    };
    return {                            // episode block or HMM run: every block the same width
        flex: compact ? '1 1 0' : '1 0 14px',
        minWidth: compact ? 0 : 3,
        borderRadius: r, background: s.bg, opacity: s.faint ? 0.4 : 1,
    };
};

const Track = ({ segments, compact, flush }) => {
    const ref = React.useRef(null);
    React.useLayoutEffect(() => {
        if (!compact && ref.current) ref.current.scrollLeft = ref.current.scrollWidth;
    }, [compact, segments.length]);
    const base = compact ? trkSm : trk;
    const style = flush ? { ...base, gap: 0, overflowY: 'hidden' } : base;   // flush: fold soft seams
    return (
        <div ref={ref} style={style}>
            {segments.map((s) => <div key={s.key} title={s.title} style={leaf(s, compact, flush)} />)}
        </div>
    );
};

// data -> segment list. Compact slices to the last COMPACT_TAIL units.
function hmmSegments(data, compact) {
    const all = data.runs || [];
    const runs = compact && all.length > COMPACT_TAIL ? all.slice(-COMPACT_TAIL) : all;
    const off = all.length - runs.length;
    return runs.map((run, i) => {
        const st = STATE[run.hmm_state] || NOSTATE;
        const obs = run.obs_bucket != null ? (data.obs_labels || {})[run.obs_bucket] : '—';
        const sc = run.change_score != null ? run.change_score.toFixed(3) : 'first';
        return { key: `r${i + off}`, bg: st.c, faint: run.hmm_state == null,
                 title: `Run #${i + off + 1} · ${st.label} · obs=${obs} · score=${sc}` };
    });
}

function episodeSegments(data, compact) {
    const all = data.episodes || [];
    const eps = compact && all.length > COMPACT_TAIL ? all.slice(-COMPACT_TAIL) : all;
    const minIdx = eps.length ? eps[0].start_idx : 0;
    const pauseAt = {}; (data.pauses || []).forEach(p => { pauseAt[p.after_idx] = p; });
    const segs = [];
    eps.forEach((ep) => {
        // One equal-width block per episode. The events themselves are summarized
        // in the tooltip (count + duration), not drawn.
        const dur = (ep.start_ts != null && ep.end_ts != null) ? ep.end_ts - ep.start_ts : null;
        segs.push({ key: `e${ep.start_idx}`, bg: EP[ep.episode_type] || EP.CODE,
                    title: `${ep.episode_type} · ${ep.event_count} events${dur != null ? ` · ${fmtDur(dur)}` : ''}` });
        const p = pauseAt[ep.end_idx - 1];
        if (p && p.after_idx >= minIdx) {
            segs.push({ key: `p${ep.end_idx}`, pause: true,
                        bg: PAUSE_FILL[p.episode_type] || HATCH_AMBER,
                        title: `${p.episode_type} · ${fmtDur(p.duration)}` });
        }
    });
    return segs;
}

const HmmTrack = ({ data, compact }) => {
    if (!data || !data.runs || data.run_count === 0) return <div style={emptyTxt(compact)}>No runs yet.</div>;
    return (<>
        <Track segments={hmmSegments(data, compact)} compact={compact} />
        {!compact && <div style={legend}>{Object.entries(STATE).map(([k, v]) => <span key={k}><i style={sw(v.c)} />{v.label}</span>)}</div>}
    </>);
};

const EpisodeTrack = ({ data, compact }) => {
    if (!data || data.event_count === 0) return <div style={emptyTxt(compact)}>No events yet.</div>;
    return (<>
        <Track segments={episodeSegments(data, compact)} compact={compact} flush />
        {!compact && <div style={legend}>
            <span><i style={sw(EP.CODE)} />CODE</span><span><i style={sw(EP.RUN)} />RUN</span><span><i style={sw(EP.RESET)} />RESET</span>
            {PAUSE_LEGEND.map(([label, fill]) => <span key={label}><i style={sw(fill)} />{label}</span>)}
        </div>}
    </>);
};

// Equal tiles, consistent 2px gap, slight rounding. Full scrolls; compact hides
// overflow (already windowed to the last COMPACT_TAIL).
const trk = { display: 'flex', gap: 2, height: 28, background: T.track, border: `1px solid ${T.border}`, borderRadius: 8, padding: 2, boxSizing: 'border-box', overflowX: 'auto', scrollbarWidth: 'thin' };
const trkSm = { ...trk, height: 18, borderRadius: 6, overflowX: 'hidden' };
const legend = { display: 'flex', gap: 14, flexWrap: 'wrap', marginTop: 9, fontSize: 11.5, color: T.sub };
const sw = (bg) => ({ display: 'inline-block', width: 11, height: 11, borderRadius: 3, marginRight: 6, verticalAlign: 'middle', background: bg });
const emptyTxt = (compact) => ({ color: T.sub, fontSize: compact ? 11.5 : 13 });

// ---------------- detail (inside modal) ----------------
// The body of the drill-down modal for one student: header + state badge, the
// playground prompt, and full-size episode and strategy timelines.
const Detail = ({ s, sid }) => {
    if (!s) return <div style={{ color: T.sub, padding: 30 }}>No activity yet for <b style={{ fontFamily: MONO }}>{sid}</b>.</div>;
    const cur = stateMeta(s);
    return (
        <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 20 }}>
                <span style={{ fontFamily: MONO, fontSize: 20, fontWeight: 700 }}>{s.studentID}</span>
                <span style={{ background: `${cur.c}1f`, color: cur.c, border: `1px solid ${cur.c}55`, borderRadius: 999, padding: '3px 12px', fontSize: 12.5, fontWeight: 700 }}>{s.current_state === WHEEL_STATE ? '⚠ Stuck' : cur.label}</span>
                <span style={{ marginLeft: 'auto', color: T.sub, fontSize: 12.5 }}>runs <b style={{ color: T.ink }}>{s.run_count}</b> · events <b style={{ color: T.ink }}>{s.event_count}</b></span>
            </div>
            <div style={lbl}>Playground</div>
            {s.block && s.block.llm_prompt
                ? <pre style={pre}>{s.block.llm_prompt}</pre>
                : <div style={{ color: T.sub, fontSize: 13, marginBottom: 22 }}>No playground yet due to no runs</div>}
            <div style={{ ...lbl, marginTop: 22 }}>Episode timeline</div>
            <EpisodeTrack data={s.episodes} />
            <div style={{ ...lbl, marginTop: 22 }}>Strategy (HMM) · one block per run</div>
            <HmmTrack data={s.hmm} />
        </div>
    );
};
const lbl = { fontSize: 11, fontWeight: 700, letterSpacing: 1, color: T.sub, textTransform: 'uppercase', marginBottom: 10 };
const pre = { margin: 0, padding: 14, background: T.track, border: `1px solid ${T.border}`, borderRadius: 10, fontFamily: MONO, fontSize: 12.5, lineHeight: 1.5, whiteSpace: 'pre-wrap', color: '#c9d1d9', maxHeight: 280, overflow: 'auto', marginBottom: 4 };

// ---------------- layout ----------------
// One big style object for the whole screen. Plain inline-style dicts (some are
// functions of an accent color), no CSS framework.
const S = {
    page: { background: T.bg, height: '100vh', display: 'flex', flexDirection: 'column', fontFamily: FONT, color: T.ink, overflow: 'hidden' },
    bar: { display: 'flex', alignItems: 'center', gap: 14, padding: '16px 28px', borderBottom: `1px solid ${T.border}`, flexWrap: 'wrap', flexShrink: 0 },
    title: { fontSize: 18, fontWeight: 800, display: 'flex', alignItems: 'center', gap: 9 },
    input: { marginLeft: 'auto', background: T.panel, border: `1px solid ${T.border}`, borderRadius: 999, color: T.ink, padding: '9px 16px', fontSize: 14, fontFamily: FONT, outline: 'none', width: 220 },
    export: { background: '#22c55e1a', color: '#22c55e', border: '1px solid #22c55e66', borderRadius: 999, padding: '9px 16px', fontSize: 13, fontWeight: 700, cursor: 'pointer', fontFamily: FONT, whiteSpace: 'nowrap' },
    reset: { background: '#ef44441a', color: '#ef4444', border: '1px solid #ef444466', borderRadius: 999, padding: '9px 16px', fontSize: 13, fontWeight: 700, cursor: 'pointer', fontFamily: FONT, whiteSpace: 'nowrap' },
    pollPause: { background: '#f59e0b1a', color: '#f59e0b', border: '1px solid #f59e0b66', borderRadius: 999, padding: '9px 16px', fontSize: 13, fontWeight: 700, cursor: 'pointer', fontFamily: FONT, whiteSpace: 'nowrap' },
    pollResume: { background: '#22c55e1a', color: '#22c55e', border: '1px solid #22c55e66', borderRadius: 999, padding: '9px 16px', fontSize: 13, fontWeight: 700, cursor: 'pointer', fontFamily: FONT, whiteSpace: 'nowrap' },
    toggleRow: { display: 'flex', gap: 6, marginTop: 10 },
    tgPresent: { flex: 1, background: '#22c55e1a', color: '#22c55e', border: '1px solid #22c55e55', borderRadius: 8, padding: '5px 6px', fontSize: 11, fontWeight: 700, cursor: 'pointer', fontFamily: FONT },
    tgAbsent: { flex: 1, background: '#6b72801a', color: '#9ca3af', border: '1px solid #6b728055', borderRadius: 8, padding: '5px 6px', fontSize: 11, fontWeight: 700, cursor: 'pointer', fontFamily: FONT },
    tgPicked: { flex: 1, background: '#a855f71f', color: '#c084fc', border: '1px solid #a855f766', borderRadius: 8, padding: '5px 6px', fontSize: 11, fontWeight: 700, cursor: 'pointer', fontFamily: FONT },
    tgUnpicked: { flex: 1, background: 'transparent', color: T.sub, border: `1px solid ${T.border}`, borderRadius: 8, padding: '5px 6px', fontSize: 11, fontWeight: 700, cursor: 'pointer', fontFamily: FONT },
    noteBtn: { flex: 1, background: '#4f46e51a', color: '#818cf8', border: '1px solid #4f46e566', borderRadius: 8, padding: '5px 6px', fontSize: 11, fontWeight: 700, cursor: 'pointer', fontFamily: FONT },
    triggersBtn: { background: T.panel, color: T.ink, border: `1px solid ${T.border}`, borderRadius: 999, padding: '9px 16px', fontSize: 13, fontWeight: 700, cursor: 'pointer', fontFamily: FONT, whiteSpace: 'nowrap' },
    popOverlay: { position: 'fixed', inset: 0, background: 'transparent', zIndex: 40 },
    popPanel: { position: 'fixed', top: 64, right: 28, width: 240, background: T.panel, border: `1px solid ${T.border}`, borderRadius: 12, padding: 12, boxShadow: '0 10px 30px #0008', zIndex: 41 },
    popTitle: { fontSize: 12, fontWeight: 800, color: T.sub, textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 8 },
    popRow: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '6px 0', fontSize: 13, color: T.ink },
    tgOn: { background: '#22c55e1a', color: '#22c55e', border: '1px solid #22c55e66', borderRadius: 999, padding: '4px 14px', fontSize: 12, fontWeight: 700, cursor: 'pointer', fontFamily: FONT },
    tgOff: { background: '#6b72801a', color: '#9ca3af', border: '1px solid #6b728055', borderRadius: 999, padding: '4px 14px', fontSize: 12, fontWeight: 700, cursor: 'pointer', fontFamily: FONT },
    noteEditor: { marginTop: 8, display: 'flex', flexDirection: 'column', gap: 6 },
    noteArea: { width: '100%', minHeight: 54, resize: 'vertical', background: T.panel, border: `1px solid ${T.border}`, borderRadius: 8, color: T.ink, padding: '7px 9px', fontSize: 12.5, fontFamily: FONT, outline: 'none', boxSizing: 'border-box' },
    noteSave: { alignSelf: 'flex-end', background: '#4f46e51a', color: '#818cf8', border: '1px solid #4f46e566', borderRadius: 8, padding: '5px 12px', fontSize: 11.5, fontWeight: 700, cursor: 'pointer', fontFamily: FONT },
    notesPanel: { marginTop: 18, borderTop: `1px solid ${T.border}`, paddingTop: 14 },
    notesItem: { padding: '8px 0', borderBottom: `1px solid ${T.border}` },
    notesMeta: { fontSize: 11, color: T.faint, display: 'flex', gap: 8, marginBottom: 3 },
    rosterBar: { display: 'flex', alignItems: 'center', gap: 8, padding: '10px 28px', borderBottom: `1px solid ${T.border}`, flexWrap: 'wrap', background: T.panel, flexShrink: 0 },
    rchip: { display: 'inline-flex', alignItems: 'center', gap: 7, background: T.bg, border: `1px solid ${T.border}`, borderRadius: 999, padding: '5px 6px 5px 11px', fontSize: 12.5, fontFamily: MONO, color: T.ink, cursor: 'pointer' },
    rx: { border: 'none', background: 'transparent', color: T.faint, fontSize: 15, cursor: 'pointer', lineHeight: 1, padding: '0 2px' },

    main: { display: 'flex', flex: 1, minHeight: 0 },                       // two-pane shell
    board: { flex: 1, overflow: 'auto', padding: '22px 28px' },
    grid: { display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 14, alignContent: 'start' },

    box: (accent) => ({ background: T.panel, border: `1px solid ${T.border}`, borderRadius: 12, padding: '13px 15px', cursor: 'pointer', position: 'relative', boxShadow: `inset 4px 0 0 ${accent}`, transition: 'transform .08s, border-color .12s' }),
    boxHead: { display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 },
    sid: { fontFamily: MONO, fontSize: 15, fontWeight: 700, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' },
    stateBadge: (c) => ({ marginLeft: 'auto', background: `${c}1f`, color: c, border: `1px solid ${c}55`, borderRadius: 999, padding: '2px 10px', fontSize: 11.5, fontWeight: 700, whiteSpace: 'nowrap' }),
    miniLbl: { fontSize: 9.5, fontWeight: 700, letterSpacing: 1, color: T.faint, textTransform: 'uppercase', margin: '11px 0 5px' },
    metaRow: { display: 'flex', justifyContent: 'space-between', marginTop: 12, fontSize: 12, color: T.sub },

    col: { width: 320, flexShrink: 0, borderLeft: `1px solid ${T.border}`, background: T.panel, overflow: 'auto', padding: '20px 18px' },
    colHead: { fontSize: 12.5, fontWeight: 800, letterSpacing: 0.5, color: T.ink, textTransform: 'uppercase', display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16 },
    colCount: (c) => ({ marginLeft: 'auto', background: `${c}1f`, color: c, border: `1px solid ${c}55`, borderRadius: 999, padding: '1px 9px', fontSize: 12 }),
    colItem: (c) => ({ background: T.bg, border: `1px solid ${c}40`, borderLeft: `3px solid ${c}`, borderRadius: 10, padding: '11px 13px', marginBottom: 10, cursor: 'pointer', position: 'relative' }),
    colSid: { fontFamily: MONO, fontWeight: 700, fontSize: 14 },
    colSub: (c) => ({ fontSize: 12, color: c, marginTop: 4, display: 'flex', alignItems: 'center', gap: 6 }),
    colEmpty: { color: T.sub, fontSize: 13, lineHeight: 1.5 },
    ackBtn: { marginLeft: 'auto', background: 'transparent', border: `1px solid ${T.border}`, color: T.sub, borderRadius: 999, padding: '2px 9px', fontSize: 11, cursor: 'pointer', fontFamily: FONT },

    empty: { color: T.sub, fontSize: 14, textAlign: 'center', marginTop: 60 },
    overlay: { position: 'fixed', inset: 0, background: 'rgba(3,5,9,0.72)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 20, padding: 24 },
    modal: { background: T.bg, border: `1px solid ${T.border}`, borderRadius: 16, width: 'min(860px, 96vw)', maxHeight: '88vh', overflow: 'auto', padding: 26, position: 'relative', boxShadow: '0 20px 60px rgba(0,0,0,0.5)' },
    modalX: { position: 'absolute', top: 14, right: 16, border: 'none', background: 'transparent', color: T.sub, fontSize: 22, cursor: 'pointer' },
};

// The notes list plus a composer, shown at the bottom of the detail modal.
const NotesPanel = ({ notes, onAdd }) => {
    const [draft, setDraft] = React.useState('');
    const save = () => { const t = draft.trim(); if (!t) return; onAdd(t); setDraft(''); };
    return (
        <div style={S.notesPanel}>
            <div style={S.miniLbl}>Notes &amp; observations ({notes.length})</div>
            {notes.length === 0 && <div style={{ color: T.faint, fontSize: 12.5, padding: '6px 0' }}>No notes yet.</div>}
            {notes.map(n => (
                <div key={n.id} style={S.notesItem}>
                    <div style={S.notesMeta}>
                        <span>{n.ts}</span>
                        {n.trigger_type && <span style={{ color: '#818cf8' }}>· during {n.trigger_type}</span>}
                    </div>
                    <div style={{ fontSize: 13, color: T.ink, whiteSpace: 'pre-wrap' }}>{n.text}</div>
                </div>
            ))}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 10 }}>
                <textarea style={S.noteArea} value={draft} placeholder="Add a manual note…"
                          onChange={e => setDraft(e.target.value)} />
                <button style={S.noteSave} onClick={save}>Add Notes</button>
            </div>
        </div>
    );
};

// The top-level component: holds all the polled state and wires up every
// action. Each data source has its own fetch callback on the shared POLL_MS
// timer so the views stay current without a single giant request.
const CohortDashboard = () => {
    const [states, setStates] = React.useState({});   // studentID -> light payload (grid)
    const [detailFull, setDetailFull] = React.useState(null);  // heavy payload for the open student
    const [roster, setRoster] = React.useState([]);
    const [triggers, setTriggers] = React.useState([]);   // backend-fired alerts
    const [selected, setSelected] = React.useState(null);
    const [query, setQuery] = React.useState('');
    const [pollingOn, setPollingOn] = React.useState(true);   // daemon prod polling
    const [notes, setNotes] = React.useState([]);        // notes for `selected`
    const [noteOpen, setNoteOpen] = React.useState(null); // trigger id with an open editor
    const [noteText, setNoteText] = React.useState('');
    const [triggerCfg, setTriggerCfg] = React.useState({ wheel_spin: true, inactive: true, big_change: true });
    const [triggerPanel, setTriggerPanel] = React.useState(false);

    const fetchStates = React.useCallback(async () => {
        try {
            const list = (await api.get('/api/student_states/')).data.students || [];
            const m = {}; list.forEach(s => { m[s.studentID] = s; });
            setStates(m);
        } catch { /* keep */ }
    }, []);
    React.useEffect(() => { fetchStates(); const id = setInterval(fetchStates, POLL_MS); return () => clearInterval(id); }, [fetchStates]);

    const fetchRoster = React.useCallback(async () => {
        try { setRoster((await api.get('/api/tracked/')).data.tracked || []); } catch { /* keep */ }
    }, []);
    React.useEffect(() => { fetchRoster(); const id = setInterval(fetchRoster, POLL_MS); return () => clearInterval(id); }, [fetchRoster]);

    const fetchTriggers = React.useCallback(async () => {
        try { setTriggers((await api.get('/api/triggers/')).data.triggers || []); } catch { /* keep */ }
    }, []);
    React.useEffect(() => { fetchTriggers(); const id = setInterval(fetchTriggers, POLL_MS); return () => clearInterval(id); }, [fetchTriggers]);

    // Pause state and trigger-config are values ONLY the user changes here (the
    // daemon just reads them), so we do NOT poll them on a timer. Polling created
    // a race: a GET already in flight when you click resolves a moment later with
    // the pre-click value and flips the control back. We fetch each once on mount
    // and let the toggle be the source of truth afterward. No competing GET, no
    // flicker. (A second open dashboard won't auto-sync these two controls, which
    // is fine for a single-researcher session.)
    const fetchPolling = React.useCallback(async () => {
        try { setPollingOn((await api.get('/api/polling/')).data.enabled); } catch { /* keep */ }
    }, []);
    React.useEffect(() => { fetchPolling(); }, [fetchPolling]);   // once, no interval
    const togglePolling = async () => {
        const next = !pollingOn;
        setPollingOn(next);   // optimistic; the toggle owns this value
        try { setPollingOn((await api.post('/api/polling/', { enabled: next })).data.enabled); }
        catch { fetchPolling(); }
    };

    const fetchTriggerCfg = React.useCallback(async () => {
        try { setTriggerCfg((await api.get('/api/triggers/config/')).data.enabled); } catch { /* keep */ }
    }, []);
    React.useEffect(() => { fetchTriggerCfg(); }, [fetchTriggerCfg]);   // once, no interval
    const toggleTrigger = async (type) => {
        const next = !triggerCfg[type];
        setTriggerCfg(c => ({ ...c, [type]: next }));   // optimistic
        try { setTriggerCfg((await api.post('/api/triggers/config/', { trigger_type: type, enabled: next })).data.enabled); }
        catch { fetchTriggerCfg(); }
    };
    // Present / picked toggles for the interview workflow. Update the UI first,
    // then persist; because both live on tracked_student they show up in the CSV.
    const setPresence = async (sid, present) => {
        setRoster(rs => rs.map(r => r.studentID === sid ? { ...r, present } : r));
        try { await api.post('/api/presence/', { studentID: sid, present }); } catch { fetchRoster(); }
    };
    const setPicked = async (sid, picked) => {
        setRoster(rs => rs.map(r => r.studentID === sid ? { ...r, picked } : r));
        try { await api.post('/api/picked/', { studentID: sid, picked }); } catch { fetchRoster(); }
    };
    // Notes for whichever learner is currently open; reloaded when the modal
    // opens and after a note is added.
    const fetchNotes = React.useCallback(async (sid) => {
        if (!sid) { setNotes([]); return; }
        try { setNotes((await api.get('/api/notes/', { params: { studentID: sid } })).data.notes || []); }
        catch { setNotes([]); }
    }, []);
    React.useEffect(() => { fetchNotes(selected); }, [selected, fetchNotes]);

    // The heavy payload (playground prompt included) for just the open student,
    // fetched on open and refreshed on the poll timer so the cohort list itself
    // stays light. `alive` discards a late response that arrives after you've
    // already switched to a different student.
    React.useEffect(() => {
        setDetailFull(null);
        if (!selected) return;
        let alive = true;
        const load = async () => {
            try { const d = (await api.get(`/api/student_states/${encodeURIComponent(selected)}/`)).data; if (alive) setDetailFull(d); }
            catch { if (alive) setDetailFull(null); }
        };
        load();
        const id = setInterval(load, POLL_MS);
        return () => { alive = false; clearInterval(id); };
    }, [selected]);
    const addNote = async (sid, text, trigger) => {
        const t = (text || '').trim();
        if (!sid || !t) return;
        const body = { studentID: sid, text: t };
        if (trigger) { body.trigger_id = trigger.id; body.trigger_type = trigger.trigger_type; }
        try { await api.post('/api/notes/', body); } catch { /* ignore */ }
        if (sid === selected) fetchNotes(sid);
    };

    const ackTrigger = async (id) => {
        // Drop the row right away so the click feels instant, then persist.
        setTriggers(ts => ts.filter(t => t.id !== id));
        if (noteOpen === id) { setNoteOpen(null); setNoteText(''); }
        try { await api.post('/api/triggers/ack/', { id }); } catch { fetchTriggers(); }
    };

    // Track one or many: split on ';', strip ALL whitespace from each id (ids
    // never contain spaces, so any whitespace is just noise), drop blanks, and
    // de-dupe. Each is added independently so one failure doesn't sink the rest.
    const addTracked = async () => {
        const ids = [...new Set(
            query.split(';').map(s => s.replace(/\s/g, '')).filter(Boolean)
        )];
        if (ids.length === 0) return;
        await Promise.all(ids.map(sid =>
            api.post('/api/tracked/', { studentID: sid }).catch(() => {})));
        setQuery(''); fetchRoster();
    };
    const removeTracked = async (sid) => {
        try { await api.post('/api/tracked/', { studentID: sid, remove: true }); } catch { /* */ }
        setRoster(r => r.filter(x => x.studentID !== sid));
        if (selected === sid) setSelected(null);
        fetchStates();
    };
    const exportData = async () => {
        try {
            const { data } = await api.post('/api/export/');
            window.alert('Exported a CSV snapshot to:\n' + (data.dir || 'exports/'));
        } catch {
            window.alert('Export failed.');
        }
    };
    const resetAll = async () => {
        if (!window.confirm("Reset the board?\n\nThis clears every student's logs, episodes, strategy state, flags, your notes & observations, AND the picked toggles + pick history. A CSV backup (notes and picks included) is saved to exports/ automatically first, so nothing is lost.\n\nStudents stay tracked and present/absent is kept; the board rebuilds from new activity. Local only, production is untouched.")) return;
        try {
            const { data } = await api.post('/api/reset/');
            // Clear the local views at once so nothing lingers until the next
            // poll: the cards, the open detail, the notes, the open note editor,
            // AND the "Needs intervention" alerts (reset wiped trigger_event).
            setSelected(null); setStates({}); setNotes([]);
            setTriggers([]); setNoteOpen(null); setNoteText('');
            window.alert('Reset done. Backup saved to:\n' + (data.backup || 'exports/'));
        } catch {
            window.alert('Reset failed, data was NOT cleared.');
        }
        fetchStates(); fetchRoster(); fetchTriggers();
    };

    // One card per tracked student, each merged with its materialized state.
    // Present students come first; within each group the order is stable (by
    // studentID) so a card never jumps when its own data refreshes. Deciding who
    // needs attention is the alert column's job, not the grid's.
    const boxes = roster
        .map(r => ({
            studentID: r.studentID,
            has_data: r.has_data,
            present: r.present !== false,   // default present for older roster payloads
            picked: !!r.picked,
            st: states[r.studentID] || null,
        }))
        // present students first, then stable by studentID so a card never jumps
        .sort((a, b) => (a.present === b.present ? a.studentID.localeCompare(b.studentID) : (a.present ? -1 : 1)));

    // Keep the alert feed to currently-tracked, PRESENT students with the type
    // enabled. The backend evaluates every student_state row, so this filters out
    // alerts for someone just untracked (and any muted trigger type). Absent
    // students are suppressed too: a kid who left the room would otherwise spam
    // "inactive" alerts forever, sending a TA to an empty seat.
    //
    // We show active AND recently-resolved triggers: the backend keeps a resolved
    // one in the feed for TRIGGER_RECENT_SECONDS (2 min), so an alert lingers for
    // ~2 minutes after a student recovers rather than vanishing instantly.
    const tracked = new Set(roster.map(r => r.studentID));
    const absent = new Set(roster.filter(r => r.present === false).map(r => r.studentID));
    const alerts = triggers.filter(t =>
        tracked.has(t.studentID) && !absent.has(t.studentID) && triggerCfg[t.trigger_type] !== false);
    const headColor = TRIGGERS.wheel_spin.c;
    const detail = detailFull;   // heavy payload fetched per-open student

    return (
        <div style={S.page}>
            <div style={S.bar}>
                <span style={S.title}>
                    <span style={{ width: 8, height: 8, borderRadius: '50%', background: pollingOn ? '#22c55e' : '#f59e0b', boxShadow: `0 0 0 3px ${pollingOn ? '#22c55e33' : '#f59e0b33'}` }} />
                    Learner Modeling Dashboard
                    {!pollingOn && <span style={{ fontSize: 12, fontWeight: 700, color: '#f59e0b' }}>· Daemon Paused</span>}
                </span>
                <input style={S.input} placeholder="Track student IDs" value={query}
                       onChange={e => setQuery(e.target.value)}
                       onKeyDown={e => { if (e.key === 'Enter') addTracked(); }} />
                <button style={pollingOn ? S.pollPause : S.pollResume} onClick={togglePolling}
                        title={pollingOn
                            ? 'Pause the daemon: stop ALL polling of the production server. The board keeps showing the last data. No new events are fetched until you resume. Use this between sessions to stop loading prod.'
                            : 'Polling is paused. The daemon is making no requests to production. Click to resume fetching new events.'}>
                    {pollingOn ? '⏸ Pause polling' : '▶ Resume polling'}
                </button>
                <button style={S.reset} onClick={resetAll}
                        title="Wipe all student data with NO backup. Export first if you want a copy.">
                    ↺ Reset
                </button>
                <button style={S.export} onClick={exportData}
                        title="Save a CSV snapshot of all data to exports">
                    ⬇ Export
                </button>
                <button style={S.triggersBtn} onClick={() => setTriggerPanel(p => !p)}
                        title="Turn trigger types on or off">
                    ⚙ Triggers
                </button>
            </div>

            {triggerPanel && (
                <div style={S.popOverlay} onClick={() => setTriggerPanel(false)}>
                    <div style={S.popPanel} onClick={e => e.stopPropagation()}>
                        <div style={S.popTitle}>Triggers</div>
                        {TRIGGER_ROWS.map(([type, label]) => {
                            const on = triggerCfg[type] !== false;
                            return (
                                <div key={type} style={S.popRow}>
                                    <span>{label}</span>
                                    <button style={on ? S.tgOn : S.tgOff} onClick={() => toggleTrigger(type)}>
                                        {on ? 'On' : 'Off'}
                                    </button>
                                </div>
                            );
                        })}
                    </div>
                </div>
            )}

            <div style={S.rosterBar}>
                <span style={{ fontSize: 12, color: T.sub, fontWeight: 700 }}>Tracking {roster.length}:</span>
                {roster.length === 0 && <span style={{ fontSize: 12.5, color: T.faint }}>Add Student ID to Start Tracking</span>}
                {roster.map(r => (
                    <span key={r.studentID} style={S.rchip} onClick={() => setSelected(r.studentID)} title="Open">
                        <span style={{ width: 6, height: 6, borderRadius: '50%', background: r.has_data ? '#22c55e' : '#f59e0b' }} />
                        {r.studentID}
                        <button style={S.rx} title="Stop tracking"
                                onClick={e => { e.stopPropagation(); removeTracked(r.studentID); }}>×</button>
                    </span>
                ))}
            </div>

            <div style={S.main}>
                {/* left: a box per tracked student */}
                <div style={S.board}>
                    {boxes.length === 0 ? (
                        <div style={S.empty}>No students added yet. Enter student IDs up top to start.</div>
                    ) : (
                        <div style={S.grid}>
                            {boxes.map(b => {
                                const sm = stateMeta(b.st);
                                const accent = b.st ? sm.c : '#2a2d3a';
                                return (
                                    <div key={b.studentID} style={{ ...S.box(accent), opacity: b.present ? 1 : 0.5 }} onClick={() => setSelected(b.studentID)}
                                         onMouseEnter={e => { e.currentTarget.style.transform = 'translateY(-2px)'; e.currentTarget.style.borderColor = accent + '66'; }}
                                         onMouseLeave={e => { e.currentTarget.style.transform = 'none'; e.currentTarget.style.borderColor = T.border; }}>
                                        <div style={S.boxHead}>
                                            <span style={S.sid} title={b.studentID}>{b.studentID}</span>
                                            <span style={S.stateBadge(accent)}>
                                                {b.st ? (b.st.current_state === WHEEL_STATE ? '⚠ Stuck' : sm.label) : 'No data'}
                                            </span>
                                        </div>
                                        {b.st ? (
                                            <>
                                                <div style={S.miniLbl}>Strategy</div>
                                                <HmmTrack data={b.st.hmm} compact />
                                                <div style={S.miniLbl}>Episodes</div>
                                                <EpisodeTrack data={b.st.episodes} compact />
                                                <div style={S.metaRow}>
                                                    <span>{b.st.run_count} runs · {b.st.event_count} events</span>
                                                    <span>{relTime(b.st.last_seen)}</span>
                                                </div>
                                            </>
                                        ) : (
                                            <div style={{ color: T.faint, fontSize: 12.5, padding: '16px 0 8px' }}>
                                                {b.has_data ? 'Loading…' : 'Waiting for activity…'}
                                            </div>
                                        )}
                                        <div style={S.toggleRow}>
                                            <button style={b.present ? S.tgPresent : S.tgAbsent}
                                                    onClick={e => { e.stopPropagation(); setPresence(b.studentID, !b.present); }}
                                                    title={b.present ? 'Mark absent (drops to the bottom, dimmed)' : 'Mark present'}>
                                                {b.present ? '● Present' : '○ Absent'}
                                            </button>
                                            <button style={b.picked ? S.tgPicked : S.tgUnpicked}
                                                    onClick={e => { e.stopPropagation(); setPicked(b.studentID, !b.picked); }}
                                                    title={b.picked ? 'Picked / interviewed — click to unmark' : 'Mark as picked / interviewed'}>
                                                {b.picked ? '✓ Picked' : 'Mark picked'}
                                            </button>
                                        </div>
                                    </div>
                                );
                            })}
                        </div>
                    )}
                </div>

                {/* right: backend-fired alerts (wheel_spin + inactive + big_change) */}
                <div style={S.col}>
                    <div style={S.colHead}>
                        <span style={{ color: headColor }}>{TRIGGERS.wheel_spin.icon}</span> Needs intervention
                        <span style={S.colCount(headColor)}>{alerts.length}</span>
                    </div>
                    {alerts.length === 0 ? (
                        <div style={S.colEmpty}>No active alerts right now. 🎉</div>
                    ) : (
                        alerts.map(t => {
                            const meta = triggerMeta(t.trigger_type);
                            return (
                                <div key={t.id} style={S.colItem(meta.c)} onClick={() => setSelected(t.studentID)}>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                                        <span style={S.colSid}>{t.studentID}</span>
                                        {(() => {
                                            const picked = !!(roster.find(r => r.studentID === t.studentID) || {}).picked;
                                            return (
                                                <button style={picked ? S.tgPicked : S.tgUnpicked}
                                                        title={picked ? 'Picked / interviewed — click to unmark' : 'Mark as picked / interviewed'}
                                                        onClick={e => { e.stopPropagation(); setPicked(t.studentID, !picked); }}>
                                                    {picked ? '✓ Picked' : 'Picked'}
                                                </button>
                                            );
                                        })()}
                                        <button style={S.noteBtn} title="Add a note for this learner"
                                                onClick={e => { e.stopPropagation(); setNoteText(''); setNoteOpen(noteOpen === t.id ? null : t.id); }}>
                                            Notes
                                        </button>
                                        <button style={S.ackBtn} title="Dismiss alert (also closes the note box)"
                                                onClick={e => { e.stopPropagation(); ackTrigger(t.id); }}>
                                            ✕
                                        </button>
                                    </div>
                                    {noteOpen === t.id && (
                                        <div style={S.noteEditor} onClick={e => e.stopPropagation()}>
                                            <textarea style={S.noteArea} value={noteText} autoFocus
                                                      placeholder="Observation during this alert…"
                                                      onChange={e => setNoteText(e.target.value)} />
                                            <button style={S.noteSave}
                                                    onClick={() => { addNote(t.studentID, noteText, t); setNoteOpen(null); setNoteText(''); }}>
                                                Save note
                                            </button>
                                        </div>
                                    )}
                                    <div style={S.colSub(meta.c)}>
                                        {meta.icon} {t.label || meta.label}
                                        {t.value ? ` · ${t.value}` : ''}
                                        <span style={{ marginLeft: 'auto', color: T.faint }}>
                                            {t.age_seconds != null ? fmtDur(t.age_seconds) : '—'}
                                        </span>
                                    </div>
                                </div>
                            );
                        })
                    )}
                </div>
            </div>

            {selected && (
                <div style={S.overlay} onClick={() => setSelected(null)}>
                    <div style={S.modal} onClick={e => e.stopPropagation()}>
                        <button style={S.modalX} onClick={() => setSelected(null)}>×</button>
                        <Detail s={detail} sid={selected} />
                        <NotesPanel notes={notes} onAdd={text => addNote(selected, text, null)} />
                    </div>
                </div>
            )}
        </div>
    );
};

export default CohortDashboard;
