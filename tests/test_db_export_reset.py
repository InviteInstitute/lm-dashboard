"""CSV export (skip-list, single-line bracketing, newline flattening) and the
reset wipe (what it clears vs keeps)."""
import csv
import os

from app import db


def test_export_skips_internal_and_bookkeeping_tables(tmp_path, seed_state):
    seed_state("s1")
    db.tracked_add("s1")
    out, written = db.export_csv(str(tmp_path / "exp"))
    files = {f for f in os.listdir(out) if f.endswith(".csv")}
    # dropped: pipeline bookkeeping + control flags + duplicated raw envelope
    assert "ingest_cursor.csv" not in files
    assert "meta.csv" not in files
    assert "message.csv" not in files
    # kept: the research data
    for keep in ("student_state.csv", "tracked_student.csv", "note.csv",
                 "pick_event.csv", "trigger_event.csv", "vex_log.csv"):
        assert keep in files


def test_tree_to_brackets_nests_children():
    tree = "[Active]\n root\n  child1\n  child2\n[Orphaned]"
    out = db._tree_to_brackets(tree)
    assert "\n" not in out
    # depth>=1 parents that have children get wrapped in braces
    assert "root {" in out and "child1" in out and "child2" in out and out.count("}") >= 1
    # section headers (depth 0) stay as plain inline labels, not wrapped
    assert "[Active]" in out and "[Orphaned]" in out


def test_csv_value_flattens_newlines_in_non_prompt_columns():
    assert db._csv_value("raw_message", "a\nb\r\nc") == "a b c"
    assert db._csv_value("anything", 123) == 123          # non-str passes through


def test_exported_rows_are_single_line(tmp_path, seed_state):
    """The whole point of the bracketing: every cell stays on one physical line."""
    seed_state("s1", playground_prompt="[Active]\n a\n  b\n  c")
    out, _ = db.export_csv(str(tmp_path / "exp"))
    with open(os.path.join(out, "student_state.csv"), newline="") as f:
        rows = list(csv.reader(f))
    # header + exactly one data row, and no embedded newline split a row
    assert len(rows) == 2
    prompt_col = rows[0].index("playground_prompt")
    assert "\n" not in rows[1][prompt_col]


def test_reset_all_wipes_data_but_keeps_roster_cursor_meta(seed_state):
    db.tracked_add("s1")
    seed_state("s1")
    db.add_note("s1", "note")
    db.set_picked("s1", True)                       # picked + a pick_event row
    db.set_presence("s1", False)                    # presence should survive reset
    db.get_or_create_cursor("vex_poll")
    db.set_meta("polling_enabled", "0")
    db.create_trigger("s1", "wheel_spin", db.now(), db.now(), None, {"label": "x"})

    db.reset_all()

    # cleared
    assert db.list_student_states(["s1"]) == []
    assert db.list_notes("s1") == []
    assert db._query("SELECT 1 FROM trigger_event") == []
    # picks cleared: flag reset, timestamp gone, history wiped
    row = db.tracked_list()[0]
    assert row["picked"] is False and row["picked_at"] is None
    assert db._query("SELECT 1 FROM pick_event") == []
    # kept: roster, presence, cursor, meta
    assert [r["studentID"] for r in db.tracked_list()] == ["s1"]
    assert row["present"] is False                  # presence is NOT reset
    assert db.get_meta("polling_enabled") == "0"
    assert db.get_or_create_cursor("vex_poll")["name"] == "vex_poll"
