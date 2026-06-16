# Notes / Observations + Single Merged CSV Export — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add per-learner timestamped notes (writable from an active alert or manually), readable in one place per learner, and make Export also write one merged `all_data.csv`.

**Architecture:** Notes are researcher annotations owned by the API and stored in a new `note` table, exactly like the existing roster/picked/polling writes. The daemon is untouched. Export gains a wide-union merged CSV alongside the per-table files.

**Tech Stack:** FastAPI + raw sqlite3 (`app/db.py`), Pydantic, React (Vite, `frontend/src/CohortDashboard.jsx`).

**Note on verification:** this repo has no test framework. Each task verifies with a real command (a `.venv/bin/python -c` snippet, a `curl` against a running API, or `npm run build`) and shows expected output. Commit after each task.

---

## File structure

- `app/db.py` — add `note` table to `_SCHEMA`; add `add_note`, `list_notes`; extend `export_csv` to also write `all_data.csv`. `reset_all` is left as-is (it already does not touch `note`).
- `app/main.py` — add `NoteBody`, `POST /api/notes/`, `GET /api/notes/`.
- `frontend/src/CohortDashboard.jsx` — notes state + handlers; right-column note editor + shared Picked toggle + ack-collapses-editor; detail-modal notes log + manual-note box; styles.
- `scripts/export_csv.py` — no code change expected (it calls `db.export_csv`, which now also writes `all_data.csv`); Task 6 just verifies this.

---

## Task 1: `note` table + db functions

**Files:**
- Modify: `app/db.py` (the `_SCHEMA` string near line 158, and add functions near `tracked_add`)

- [ ] **Step 1: Verify the functions do not exist yet (red)**

Run: `cd /Users/maharsh/Documents/Research/lm-dashboard && .venv/bin/python -c "from app import db; db.add_note"`
Expected: `AttributeError: module 'app.db' has no attribute 'add_note'`

- [ ] **Step 2: Add the `note` table to `_SCHEMA`**

In `app/db.py`, immediately after the `CREATE TABLE IF NOT EXISTS meta (...)` block and before the closing `"""` of `_SCHEMA`, add:

```sql
CREATE TABLE IF NOT EXISTS note (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    studentID VARCHAR(128) NOT NULL,
    ts DATETIME NOT NULL,
    text TEXT NOT NULL,
    trigger_id INTEGER,
    trigger_type VARCHAR(24),
    created_at DATETIME NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_note_student ON note(studentID, ts);
```

- [ ] **Step 3: Add `add_note` and `list_notes`**

In `app/db.py`, add these two functions just above `def tracked_add(sid):`:

```python
def add_note(student_id, text, trigger_id=None, trigger_type=None):
    """Append one note for a student. trigger_id/trigger_type are set when the
    note is written from an active alert; both None for a manual note. Returns
    the created row as a dict."""
    ts = dt_to_db(now())
    with closing(connect()) as con:
        cur = con.execute(
            "INSERT INTO note (studentID, ts, text, trigger_id, trigger_type, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (student_id, ts, text, trigger_id, trigger_type, ts),
        )
        nid = cur.lastrowid
        con.commit()
    return {
        "id": nid, "studentID": student_id, "ts": ts, "text": text,
        "trigger_id": trigger_id, "trigger_type": trigger_type, "created_at": ts,
    }


def list_notes(student_id):
    """All notes for a student, oldest first."""
    rows = _query(
        "SELECT id, studentID, ts, text, trigger_id, trigger_type, created_at "
        "FROM note WHERE studentID = ? ORDER BY ts, id",
        (student_id,),
    )
    return [dict(r) for r in rows]
```

- [ ] **Step 4: Verify add/list works and survives a reset (green)**

Run:
```bash
cd /Users/maharsh/Documents/Research/lm-dashboard && .venv/bin/python -c "
from app import db
db.init_db()
n = db.add_note('plan_demo', 'first obs', trigger_id=1, trigger_type='wheel_spin')
db.add_note('plan_demo', 'manual obs')
print('added id', n['id'])
print('count before reset', len(db.list_notes('plan_demo')))
db.reset_all()
print('count after reset', len(db.list_notes('plan_demo')))
# cleanup
import sqlite3, app.config as c
con = sqlite3.connect(c.DB_PATH); con.execute(\"DELETE FROM note WHERE studentID='plan_demo'\"); con.commit()
"
```
Expected:
```
added id <n>
count before reset 2
count after reset 2
```
(The "after reset" count staying 2 proves notes survive a reset.)

- [ ] **Step 5: Commit**

```bash
git add app/db.py
git commit -m "feat(db): add note table + add_note/list_notes (kept through reset)"
```

---

## Task 2: Merged `all_data.csv` export

**Files:**
- Modify: `app/db.py` (the `export_csv` function, around line 207)

- [ ] **Step 1: Verify there is no merged file yet (red)**

Run:
```bash
cd /Users/maharsh/Documents/Research/lm-dashboard && .venv/bin/python -c "
from app import db; db.init_db()
out, written = db.export_csv('/tmp/lm_export_test')
print('all_data.csv' in written)
"
```
Expected: `False`

- [ ] **Step 2: Add the merged-CSV pass to `export_csv`**

In `app/db.py`, inside `export_csv`, locate the end of the per-table loop, right before `return out_dir, written`. Insert this block (it re-reads each table and writes one wide-union file):

```python
        # Single merged file: every table's rows, wide union of columns, with a
        # leading source_table column. Sorted by studentID then a best-effort
        # timestamp so it reads as a per-learner chronology.
        _TIME_COLS = ("ts", "started_at", "received_at", "recieved_at",
                      "updated_at", "last_event_time", "created_at")
        merged_cols, seen = [], set()
        merged_rows = []
        for t in tables:
            cur = con.execute(f'SELECT * FROM "{t}"')
            cols = [d[0] for d in cur.description]
            for c in cols:
                if c not in seen:
                    seen.add(c)
                    merged_cols.append(c)
            for row in cur.fetchall():
                d = {cols[i]: row[i] for i in range(len(cols))}
                d["__table__"] = t
                merged_rows.append(d)

        def _sort_key(d):
            sid = d.get("studentID") or "~"   # studentID-less rows sort last
            ts = ""
            for c in _TIME_COLS:
                if d.get(c):
                    ts = str(d[c])
                    break
            return (sid, ts)

        merged_rows.sort(key=_sort_key)
        with open(os.path.join(out_dir, "all_data.csv"), "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["source_table"] + merged_cols)
            for d in merged_rows:
                w.writerow([d["__table__"]] + [d.get(c, "") for c in merged_cols])
        written["all_data.csv"] = len(merged_rows)
```

- [ ] **Step 3: Verify the merged file is written with the right shape (green)**

Run:
```bash
cd /Users/maharsh/Documents/Research/lm-dashboard && .venv/bin/python -c "
from app import db; db.init_db()
db.add_note('plan_demo2', 'note in merged')
out, written = db.export_csv('/tmp/lm_export_test2')
import csv, sqlite3, app.config as c
head = open(out + '/all_data.csv').readline().strip()
print('has all_data.csv:', 'all_data.csv' in written)
print('first col is source_table:', head.split(',')[0] == 'source_table')
print('note row present:', any('plan_demo2' in line and line.startswith('note') for line in open(out + '/all_data.csv')))
print('note.csv also exists:', __import__('os').path.exists(out + '/note.csv'))
con = sqlite3.connect(c.DB_PATH); con.execute(\"DELETE FROM note WHERE studentID='plan_demo2'\"); con.commit()
"
```
Expected:
```
has all_data.csv: True
first col is source_table: True
note row present: True
note.csv also exists: True
```

- [ ] **Step 4: Commit**

```bash
git add app/db.py
git commit -m "feat(db): export a merged all_data.csv (wide union) alongside per-table CSVs"
```

---

## Task 3: API endpoints for notes

**Files:**
- Modify: `app/main.py` (add after the `set_picked` endpoint added previously)

- [ ] **Step 1: Verify the route is absent (red)**

Start the API and probe (pick a free port if 8000 is busy):
```bash
cd /Users/maharsh/Documents/Research/lm-dashboard && .venv/bin/uvicorn app.main:app --port 8077 >/tmp/lm_api_p.log 2>&1 &
sleep 3
curl -s -o /dev/null -w "%{http_code}\n" "http://localhost:8077/api/notes/?studentID=x"
```
Expected: `404`

- [ ] **Step 2: Add the `NoteBody` model and the two endpoints**

In `app/main.py`, add after the `set_picked` function:

```python
class NoteBody(BaseModel):
    studentID: str
    text: str
    trigger_id: int | None = None
    trigger_type: str | None = None


@app.post("/api/notes/")
def add_note(body: NoteBody):
    """Append an observation for a learner. trigger_id/trigger_type link it to the
    alert it was written from (omit both for a manual note). Stored on the note
    table, so it exports with the CSV."""
    sid = (body.studentID or "").strip()
    text = (body.text or "").strip()
    if not sid:
        raise HTTPException(status_code=400, detail="studentID required")
    if not text:
        raise HTTPException(status_code=400, detail="text required")
    return db.add_note(sid, text, body.trigger_id, body.trigger_type)


@app.get("/api/notes/")
def list_notes(studentID: str | None = None):
    """All notes for a learner, oldest first."""
    sid = (studentID or "").strip()
    if not sid:
        raise HTTPException(status_code=400, detail="studentID required")
    notes = db.list_notes(sid)
    return {"notes": notes, "count": len(notes)}
```

- [ ] **Step 3: Verify post (linked + manual) and get (green)**

The API is started with `--reload`? It was started plain in Step 1, so restart it:
```bash
pkill -f "uvicorn app.main" ; sleep 1
cd /Users/maharsh/Documents/Research/lm-dashboard && .venv/bin/uvicorn app.main:app --port 8077 >/tmp/lm_api_p.log 2>&1 &
sleep 3
curl -s -X POST localhost:8077/api/notes/ -H 'Content-Type: application/json' -d '{"studentID":"plan_api","text":"during alert","trigger_id":5,"trigger_type":"wheel_spin"}'; echo
curl -s -X POST localhost:8077/api/notes/ -H 'Content-Type: application/json' -d '{"studentID":"plan_api","text":"manual note"}'; echo
curl -s "localhost:8077/api/notes/?studentID=plan_api" | python3 -m json.tool
curl -s -o /dev/null -w "empty text -> %{http_code}\n" -X POST localhost:8077/api/notes/ -H 'Content-Type: application/json' -d '{"studentID":"plan_api","text":"  "}'
pkill -f "uvicorn app.main"
# cleanup the test rows
.venv/bin/python -c "import sqlite3, app.config as c; con=sqlite3.connect(c.DB_PATH); con.execute(\"DELETE FROM note WHERE studentID='plan_api'\"); con.commit()"
```
Expected: first two return note JSON (with `id`, `ts`); the GET shows `"count": 2` with the linked note first carrying `trigger_type: "wheel_spin"`; empty text returns `400`.

- [ ] **Step 4: Commit**

```bash
git add app/main.py
git commit -m "feat(api): POST/GET /api/notes/ for learner observations"
```

---

## Task 4: Right-column note editor + shared Picked + ack collapses editor

**Files:**
- Modify: `frontend/src/CohortDashboard.jsx`

- [ ] **Step 1: Add notes + editor state and handlers**

In the component, next to the other `useState` declarations (near `pollingOn`), add:

```jsx
    const [notes, setNotes] = React.useState([]);        // notes for `selected`
    const [noteOpen, setNoteOpen] = React.useState(null); // trigger id with an open editor
    const [noteText, setNoteText] = React.useState('');
```

Next to the other fetch callbacks, add:

```jsx
    const fetchNotes = React.useCallback(async (sid) => {
        if (!sid) { setNotes([]); return; }
        try { setNotes((await api.get('/api/notes/', { params: { studentID: sid } })).data.notes || []); }
        catch { setNotes([]); }
    }, []);
    React.useEffect(() => { fetchNotes(selected); }, [selected, fetchNotes]);

    const addNote = async (sid, text, trigger) => {
        const t = (text || '').trim();
        if (!sid || !t) return;
        const body = { studentID: sid, text: t };
        if (trigger) { body.trigger_id = trigger.id; body.trigger_type = trigger.trigger_type; }
        try { await api.post('/api/notes/', body); } catch { /* ignore */ }
        if (sid === selected) fetchNotes(sid);
    };
```

- [ ] **Step 2: Make ack also close an open editor**

Replace the existing `ackTrigger` with:

```jsx
    const ackTrigger = async (id) => {
        // Optimistic: drop the row immediately so the click feels instant.
        setTriggers(ts => ts.filter(t => t.id !== id));
        if (noteOpen === id) { setNoteOpen(null); setNoteText(''); }
        try { await api.post('/api/triggers/ack/', { id }); } catch { fetchTriggers(); }
    };
```

- [ ] **Step 3: Add note + Picked controls to each right-column alert**

In the right-column alerts map, replace the existing single-button row that contains the `ack` button. Find this block:

```jsx
                                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                                        <span style={S.colSid}>{t.studentID}</span>
                                        <button style={S.ackBtn}
                                                title="Acknowledge / dismiss"
                                                onClick={e => { e.stopPropagation(); ackTrigger(t.id); }}>
                                            ack
                                        </button>
                                    </div>
```

Replace it with (note `picked` is read from the shared roster):

```jsx
                                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                                        <span style={S.colSid}>{t.studentID}</span>
                                        <button style={S.ackBtn} title="Add a note for this learner"
                                                onClick={e => { e.stopPropagation(); setNoteText(''); setNoteOpen(noteOpen === t.id ? null : t.id); }}>
                                            📝 note
                                        </button>
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
```

- [ ] **Step 4: Add the styles used above**

In the `S` styles object, after the `tgUnpicked` entry, add:

```jsx
    noteEditor: { marginTop: 8, display: 'flex', flexDirection: 'column', gap: 6 },
    noteArea: { width: '100%', minHeight: 54, resize: 'vertical', background: T.panel, border: `1px solid ${T.border}`, borderRadius: 8, color: T.ink, padding: '7px 9px', fontSize: 12.5, fontFamily: FONT, outline: 'none', boxSizing: 'border-box' },
    noteSave: { alignSelf: 'flex-end', background: '#4f46e51a', color: '#818cf8', border: '1px solid #4f46e566', borderRadius: 8, padding: '5px 12px', fontSize: 11.5, fontWeight: 700, cursor: 'pointer', fontFamily: FONT },
    notesPanel: { marginTop: 18, borderTop: `1px solid ${T.border}`, paddingTop: 14 },
    notesItem: { padding: '8px 0', borderBottom: `1px solid ${T.border}` },
    notesMeta: { fontSize: 11, color: T.faint, display: 'flex', gap: 8, marginBottom: 3 },
```

- [ ] **Step 5: Verify the build is clean (green)**

Run: `cd /Users/maharsh/Documents/Research/lm-dashboard/frontend && npm run build 2>&1 | tail -4 && rm -rf dist`
Expected: ends with `✓ built in ...` and no error.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/CohortDashboard.jsx
git commit -m "feat(ui): right-column note editor, shared Picked, ack closes editor"
```

---

## Task 5: Detail-modal notes log + manual note box

**Files:**
- Modify: `frontend/src/CohortDashboard.jsx` (the modal block near the end of the component)

- [ ] **Step 1: Render the notes panel inside the modal**

Find the modal block:

```jsx
            {selected && (
                <div style={S.overlay} onClick={() => setSelected(null)}>
                    <div style={S.modal} onClick={e => e.stopPropagation()}>
                        <button style={S.modalX} onClick={() => setSelected(null)}>×</button>
                        <Detail s={detail} sid={selected} />
                    </div>
                </div>
            )}
```

Replace the `<Detail .../>` line with `<Detail>` followed by the notes panel:

```jsx
                        <Detail s={detail} sid={selected} />
                        <NotesPanel notes={notes} onAdd={text => addNote(selected, text, null)} />
```

- [ ] **Step 2: Define the `NotesPanel` component**

Near the other small components at the top of the file (for example just above `const CohortDashboard = () => {`), add:

```jsx
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
                <button style={S.noteSave} onClick={save}>Add note</button>
            </div>
        </div>
    );
};
```

(`S`, `T`, and `S.miniLbl` already exist in this file and are in module scope, so `NotesPanel` can use them.)

- [ ] **Step 2b: Verify `S` and `T` are module-scoped**

Run: `cd /Users/maharsh/Documents/Research/lm-dashboard && grep -nE "^const (S|T) =|^const FONT" frontend/src/CohortDashboard.jsx | head`
Expected: shows `const T = ...`, `const FONT = ...`, and `const S = ...` at module top level (not inside the component). If `S`/`T` are not module-scoped, move the `NotesPanel` definition to just after the `S` definition instead.

- [ ] **Step 3: Verify the build is clean (green)**

Run: `cd /Users/maharsh/Documents/Research/lm-dashboard/frontend && npm run build 2>&1 | tail -4 && rm -rf dist`
Expected: ends with `✓ built in ...` and no error.

- [ ] **Step 4: Manual click-through (with the stack running)**

Start API + frontend, add a student, open it, add a manual note, then (after Resume polling, if a wheel-spin fires) add a note from the right-column alert and confirm both appear in the learner's modal, oldest first, the alert-linked one tagged "during wheel_spin".

- [ ] **Step 5: Commit**

```bash
git add frontend/src/CohortDashboard.jsx
git commit -m "feat(ui): learner detail modal shows full notes log + manual add"
```

---

## Task 6: Confirm `scripts/export_csv.py` emits the merged file

**Files:**
- Read/verify: `scripts/export_csv.py`

- [ ] **Step 1: Check whether the script calls the shared db function**

Run: `cd /Users/maharsh/Documents/Research/lm-dashboard && grep -nE "export_csv|all_data|db\." scripts/export_csv.py`
Expected: it calls `db.export_csv(...)`. If so, `all_data.csv` is produced automatically and no code change is needed.

- [ ] **Step 2: Run the script and confirm the merged file appears**

Run: `cd /Users/maharsh/Documents/Research/lm-dashboard && .venv/bin/python scripts/export_csv.py --out /tmp/lm_script_export && ls /tmp/lm_script_export | grep -E "all_data.csv|note.csv"`
Expected: both `all_data.csv` and `note.csv` are listed.

- [ ] **Step 3 (only if Step 1 showed the script does NOT use `db.export_csv`):** update the script to call `db.export_csv(out_dir)` so the merged file is written. Otherwise skip.

- [ ] **Step 4: Commit (only if the script changed)**

```bash
git add scripts/export_csv.py
git commit -m "chore(export): ensure CLI export emits all_data.csv"
```

---

## Self-review (completed during planning)

- **Spec coverage:** note table + reset-keeps-notes (Task 1), merged CSV wide-union (Task 2), API notes endpoints (Task 3), right-column editor + shared Picked + ack-collapses (Task 4), detail-modal log + manual note (Task 5), single-CSV via CLI too (Task 6). All spec sections map to a task.
- **Type/name consistency:** `db.add_note(student_id, text, trigger_id, trigger_type)` / `db.list_notes(student_id)` are used identically in Tasks 1 and 3. Frontend `addNote(sid, text, trigger)`, `fetchNotes(sid)`, `noteOpen`, `noteText`, `notes`, `NotesPanel` props (`notes`, `onAdd`) are consistent across Tasks 4 and 5. Styles `noteEditor/noteArea/noteSave/notesPanel/notesItem/notesMeta` are defined in Task 4 and used in Tasks 4 and 5. `S.tgPicked`/`S.tgUnpicked` already exist from the earlier toggles work.
- **Placeholders:** none; every code step shows complete code.
