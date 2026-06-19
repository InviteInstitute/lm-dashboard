import React from 'react';
import api from './api';

// ===================== dark slate theme =====================
const T = {
    bg: '#0b0e13', panel: '#0f131a', border: '#1f2530', borderSoft: '#171c24',
    ink: '#e6e9ef', sub: '#7d8694', faint: '#5a626e', track: '#0d1117',
};
const STATE = {
    0: { c: '#3b82f6', label: 'Iterator' },
    1: { c: '#a855f7', label: 'Explorer' },
    2: { c: '#ef4444', label: 'Stuck' },
};
const NOSTATE = { c: '#6b7280', label: 'No runs yet' };
const EP = { CODE: '#3b82f6', RUN: '#22c55e', RESET: '#a855f7' };
// All intervention signals, the right column shows everything the backend
// fires (wheel_spin + inactive + big_change), not just wheel-spinning.
const TRIGGERS = {
    wheel_spin: { c: '#ef4444', icon: '⟳', label: 'Wheel-spinning' },
    inactive:   { c: '#f59e0b', icon: '⏸', label: 'Inactive' },
    big_change: { c: '#a855f7', icon: '✎', label: 'Big rewrite' },
};
const TRIGGER_FALLBACK = { c: '#6b7280', icon: '•', label: 'Trigger' };
const FONT = "'Inter','SF Pro Display',system-ui,sans-serif";
const TRIGGER_ROWS = [['wheel_spin', 'Wheel-spinning'], ['inactive', 'Inactive'], ['big_change', 'Big rewrite']];
const MONO = "'SF Mono','JetBrains Mono',ui-monospace,monospace";
const POLL_MS = 1500;
const WHEEL_STATE = 2;   // HMM "stuck" == wheel-spinning
const triggerMeta = (type) => TRIGGERS[type] || TRIGGER_FALLBACK;

function relTime(iso) {
    if (!iso) return '—';
    const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
    if (s < 60) return `${Math.round(s)}s`;
    if (s < 3600) return `${Math.round(s / 60)}m`;
    if (s < 86400) return `${Math.round(s / 3600)}h`;
    return `${Math.round(s / 86400)}d`;
}
function fmtDur(s) {
    if (s == null) return '—';
    if (s < 60) return `${s.toFixed(1)}s`;
    if (s < 3600) return `${(s / 60).toFixed(1)}m`;
    return `${(s / 3600).toFixed(1)}h`;
}
function stateMeta(st) {
    if (!st || st.current_state == null) return NOSTATE;
    return STATE[st.current_state] || NOSTATE;
}

// ---------------- timelines (per-event boundaries) ----------------
// `compact` renders just the bar (no legend, shorter) for the cohort boxes.
const EpisodeTrack = ({ data, compact }) => {
    if (!data || data.event_count === 0) return <div style={{ color: T.sub, fontSize: compact ? 11.5 : 13 }}>No events yet.</div>;
    const events = data.events || [], episodes = data.episodes || [];
    const evToEp = {}, softSet = new Set();
    episodes.forEach((ep, idx) => { for (let k = ep.start_idx; k < ep.end_idx; k++) evToEp[k] = idx; (ep.soft_indices || []).forEach(si => softSet.add(si)); });
    const pauseAfter = {}; (data.pauses || []).forEach(p => { pauseAfter[p.after_idx] = p; });
    const band = (p, key) => { const i = p.episode_type === 'INACTIVE_PAUSE'; return <div key={key} title={`${p.episode_type} · ${fmtDur(p.duration)}`} style={{ flex: '0 0 10px', background: i ? 'repeating-linear-gradient(45deg,#ef4444 0 4px,#3a1416 4px 8px)' : 'repeating-linear-gradient(45deg,#f59e0b 0 4px,#3a2a10 4px 8px)' }} />; };
    const segs = []; let i = 0;
    while (i < events.length) {
        const epIdx = evToEp[i];
        if (epIdx === undefined) { segs.push(<div key={`o${i}`} title={`${events[i].eventType} (orphan)`} style={{ flex: '0 0 3px', background: '#2a2d3a', borderRight: '1px solid rgba(0,0,0,0.6)' }} />); if (pauseAfter[i]) segs.push(band(pauseAfter[i], `po${i}`)); i++; continue; }
        const ep = episodes[epIdx], c = EP[ep.episode_type] || EP.CODE; const ticks = [];
        for (let k = ep.start_idx; k < ep.end_idx; k++) ticks.push(<div key={`t${k}`} title={`${events[k].eventType} · ${ep.episode_type}`} style={{ flex: '1 1 0', minWidth: 2, background: c, opacity: softSet.has(k) ? 0.4 : 1, borderRight: '1px solid rgba(0,0,0,0.6)' }} />);
        segs.push(<div key={`e${epIdx}`} style={{ flexGrow: Math.max(1, ep.event_count), flexShrink: 1, minWidth: 6, display: 'flex', outline: `1px solid ${c}`, outlineOffset: -1 }}>{ticks}</div>);
        if (pauseAfter[ep.end_idx - 1]) segs.push(band(pauseAfter[ep.end_idx - 1], `p${epIdx}`));
        i = ep.end_idx;
    }
    return (<>
        <div style={compact ? trkSm : trk}>{segs}</div>
        {!compact && <div style={legend}>
            <span><i style={sw(EP.CODE)} />CODE</span><span><i style={sw(EP.RUN)} />RUN</span><span><i style={sw(EP.RESET)} />RESET</span>
            <span><i style={sw('repeating-linear-gradient(45deg,#ef4444 0 3px,#3a1416 3px 6px)')} />inactive pause</span>
        </div>}
    </>);
};
const HmmTrack = ({ data, compact }) => {
    if (!data || !data.runs || data.run_count === 0) return <div style={{ color: T.sub, fontSize: compact ? 11.5 : 13 }}>No runs yet.</div>;
    const blocks = data.runs.map((run, i) => { const st = STATE[run.hmm_state] || NOSTATE; const obs = run.obs_bucket != null ? data.obs_labels[run.obs_bucket] : '—'; const sc = run.change_score != null ? run.change_score.toFixed(3) : 'first'; return <div key={i} title={`Run #${i + 1} · ${st.label} · obs=${obs} · score=${sc}`} style={{ flex: '1 1 0', minWidth: 6, background: st.c, opacity: run.hmm_state == null ? 0.3 : 1, borderRight: '1px solid rgba(0,0,0,0.6)' }} />; });
    return (<>
        <div style={compact ? trkSm : trk}>{blocks}</div>
        {!compact && <div style={legend}>{Object.entries(STATE).map(([k, v]) => <span key={k}><i style={sw(v.c)} />{v.label}</span>)}</div>}
    </>);
};
const trk = { display: 'flex', height: 28, background: T.track, border: `1px solid ${T.border}`, borderRadius: 8, overflow: 'hidden' };
const trkSm = { ...trk, height: 16, borderRadius: 6 };
const legend = { display: 'flex', gap: 14, flexWrap: 'wrap', marginTop: 9, fontSize: 11.5, color: T.sub };
const sw = (bg) => ({ display: 'inline-block', width: 11, height: 11, borderRadius: 3, marginRight: 6, verticalAlign: 'middle', background: bg });

// ---------------- detail (inside modal) ----------------
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

    // Daemon polling state. Polled on the same timer so the toggle stays in sync
    // across multiple open dashboards.
    const fetchPolling = React.useCallback(async () => {
        try { setPollingOn((await api.get('/api/polling/')).data.enabled); } catch { /* keep */ }
    }, []);
    React.useEffect(() => { fetchPolling(); const id = setInterval(fetchPolling, POLL_MS); return () => clearInterval(id); }, [fetchPolling]);
    const togglePolling = async () => {
        const next = !pollingOn;
        setPollingOn(next);   // optimistic
        try { setPollingOn((await api.post('/api/polling/', { enabled: next })).data.enabled); }
        catch { fetchPolling(); }
    };
    // Which trigger types fire. Toggling off tells the daemon to stop firing that
    // type and clear its open alerts; we also hide it from the column immediately.
    const fetchTriggerCfg = React.useCallback(async () => {
        try { setTriggerCfg((await api.get('/api/triggers/config/')).data.enabled); } catch { /* keep */ }
    }, []);
    React.useEffect(() => { fetchTriggerCfg(); const id = setInterval(fetchTriggerCfg, POLL_MS); return () => clearInterval(id); }, [fetchTriggerCfg]);
    const toggleTrigger = async (type) => {
        const next = !triggerCfg[type];
        setTriggerCfg(c => ({ ...c, [type]: next }));   // optimistic
        try { setTriggerCfg((await api.post('/api/triggers/config/', { trigger_type: type, enabled: next })).data.enabled); }
        catch { fetchTriggerCfg(); }
    };
    // Interview-workflow toggles. Optimistic update, then persist (and the state
    // exports to CSV because it lives on the tracked_student table).
    const setPresence = async (sid, present) => {
        setRoster(rs => rs.map(r => r.studentID === sid ? { ...r, present } : r));
        try { await api.post('/api/presence/', { studentID: sid, present }); } catch { fetchRoster(); }
    };
    const setPicked = async (sid, picked) => {
        setRoster(rs => rs.map(r => r.studentID === sid ? { ...r, picked } : r));
        try { await api.post('/api/picked/', { studentID: sid, picked }); } catch { fetchRoster(); }
    };
    // Notes for the currently-open learner; refetched when the modal opens or
    // after a note is posted.
    const fetchNotes = React.useCallback(async (sid) => {
        if (!sid) { setNotes([]); return; }
        try { setNotes((await api.get('/api/notes/', { params: { studentID: sid } })).data.notes || []); }
        catch { setNotes([]); }
    }, []);
    React.useEffect(() => { fetchNotes(selected); }, [selected, fetchNotes]);

    // Heavy detail (incl. the playground prompt) for the open student only --
    // fetched on open and kept live on the poll timer, so the cohort list stays
    // light. `alive` guards against a stale response landing after you switch.
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
        // Optimistic: drop the row immediately so the click feels instant.
        setTriggers(ts => ts.filter(t => t.id !== id));
        if (noteOpen === id) { setNoteOpen(null); setNoteText(''); }
        try { await api.post('/api/triggers/ack/', { id }); } catch { fetchTriggers(); }
    };

    const addTracked = async () => {
        const sid = query.trim(); if (!sid) return;
        try { await api.post('/api/tracked/', { studentID: sid }); } catch { /* */ }
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
        if (!window.confirm("Reset the board?\n\nThis clears every student's logs, episodes, strategy state, flags, AND your notes & observations. A CSV backup (including the notes) is saved to exports/ automatically first, so nothing is lost.\n\nStudents stay tracked and the board rebuilds from new activity. Local only, production is untouched.")) return;
        try {
            const { data } = await api.post('/api/reset/');
            setSelected(null); setStates({}); setNotes([]);
            window.alert('Reset done. Backup saved to:\n' + (data.backup || 'exports/'));
        } catch {
            window.alert('Reset failed, data was NOT cleared.');
        }
        fetchStates(); fetchRoster();
    };

    // one box per tracked student, merged with their materialized state.
    // STABLE order (by studentID) so a box never jumps when its own data
    // updates on a new event — surfacing who needs help is the right column's job.
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

    // Restrict the alert feed to students the user is currently tracking --
    // the backend evaluator runs over every student_state row, but we don't
    // want to surface alerts for students who were just removed.
    const tracked = new Set(roster.map(r => r.studentID));
    const alerts = triggers.filter(t => tracked.has(t.studentID) && triggerCfg[t.trigger_type] !== false);
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
                <input style={S.input} placeholder="Track a student ID…" value={query}
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
