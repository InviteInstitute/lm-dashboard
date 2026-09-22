"""Real-time goal recognition wired into the worker.

Each StudentWorker feeds a goal_strategy GoalProfileStream every event, and
recompute_and_write persists the per-run goal evidence for Castle Crashers runs
into goal_profile, keyed by the same run_index the edit-distance runs use.
"""

import json
from datetime import UTC, datetime, timedelta

from app import db
from app.pipeline.workers import StudentWorker

# Blockly's workspace namespace: real VEXcode workspaces always carry it, and
# goal_strategy parses unnamespaced XML to an empty program.
NS = 'xmlns="https://developers.google.com/blockly/xml"'
# A minimal Castle Crashers program: drive forward. goal_strategy simulates it.
CC_XML = (
    f'<xml {NS}><block type="pg_events_when_started" id="h"><next>'
    '<block type="pg_drivetrain_drive_for" id="d">'
    '<field name="DIRECTION">fwd</field><field name="UNITS">mm</field>'
    '<value name="AMOUNT"><shadow type="math_number"><field name="NUM">300</field></shadow></value>'
    "</block></next></block></xml>"
)
OTHER_XML = '<xml><block type="events_whenStarted" id="a"></block></xml>'
T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _raw_run(sid, xml, playground, i):
    content = {"project": {"workspace": xml}}
    if playground is not None:
        content["playground"] = playground
    return {
        "studentID": sid,
        "classCode": "C1",
        "eventType": "runProject",
        "raw_message": json.dumps(content),
        "project": {"workspace": xml},
        "source_event_id": i + 1,
        "event_time": T0 + timedelta(seconds=i),
    }


# A real playgroundData outcome, shaped exactly like the mirror stores it.
OUTCOME = {
    "weight_cleared": 1600,
    "elapsedtime": 6.5,
    "difficulty_level": 1,
    "project_stopped_by_user": False,
    "gps_x_position": -2085,
    "gps_y_position": 57,
}


def _raw_pgdata(sid, params, i):
    content = {
        "playground": "CasteCrasherPlus",
        "playgroundData": {"playground": "CasteCrasherPlus", "parameters": params},
    }
    return {
        "studentID": sid,
        "classCode": "C1",
        "eventType": "playgroundData",
        "raw_message": json.dumps(content),
        "project": None,
        "source_event_id": i + 1,
        "event_time": T0 + timedelta(seconds=i),
    }


def _outcome_indicators(profile):
    return [
        ind
        for g in profile["goals"]
        for ind in (g["intent"] + g["attainment"])
        if ind["channel"] == "outcome"
    ]


def test_playground_outcome_is_associated_to_its_run():
    w = StudentWorker("cobra13")
    w.ingest(_raw_run("cobra13", CC_XML, "CasteCrasherPlus", 0))
    w.ingest(_raw_pgdata("cobra13", OUTCOME, 1))  # outcome for run 0
    w.recompute_and_write()

    profs = db.list_goal_profiles("cobra13")
    assert len(profs) == 1
    outs = _outcome_indicators(profs[0]["profile"])
    by_name = {o["name"]: o for o in outs}
    assert not by_name["weight_cleared"]["abstained"]
    assert by_name["weight_cleared"]["value"] == 1600.0
    assert not by_name["on_island_observed"][
        "abstained"
    ]  # GPS present -> no longer "gps_unavailable"


def test_outcome_absent_until_playground_data_arrives():
    w = StudentWorker("cobra14")
    w.ingest(_raw_run("cobra14", CC_XML, "CasteCrasherPlus", 0))
    w.recompute_and_write()  # run persisted with no outcome yet
    before = {
        o["name"]: o["abstained"]
        for o in _outcome_indicators(db.list_goal_profiles("cobra14")[0]["profile"])
    }
    assert all(before.values())  # all outcome indicators abstained

    w.ingest(_raw_pgdata("cobra14", OUTCOME, 1))  # late outcome
    w.recompute_and_write()  # must RE-persist run 0 with the outcome
    after = {
        o["name"]: o["abstained"]
        for o in _outcome_indicators(db.list_goal_profiles("cobra14")[0]["profile"])
    }
    assert not after["weight_cleared"] and not after["on_island_observed"]


def test_castle_crashers_runs_are_profiled_and_stored():
    w = StudentWorker("cobra9")
    for i in range(3):
        w.ingest(_raw_run("cobra9", CC_XML, "CasteCrasherPlus", i))
    w.recompute_and_write()

    profs = db.list_goal_profiles("cobra9")
    assert len(profs) == 3
    assert [p["index"] for p in profs] == [0, 1, 2]
    assert all(p["status"] == "profiled" for p in profs)
    # The four Castle Crashers goals are present as evidence.
    goals = {g["goal"] for g in profs[0]["profile"]["goals"]}
    assert {
        "playground_engagement",
        "engage_plow",
        "clear_debris_zone",
        "remain_on_island",
    } <= goals


def test_goal_run_index_aligns_with_edit_distance_runs():
    w = StudentWorker("cobra10")
    for i in range(2):
        w.ingest(_raw_run("cobra10", CC_XML, "CasteCrasherPlus", i))
    w.recompute_and_write()

    state = db.list_student_states(["cobra10"])[0]
    learner_idx = [r["index"] for r in state["runs"]["runs"]]
    goal_idx = [p["index"] for p in db.list_goal_profiles("cobra10")]
    assert goal_idx == learner_idx  # same run indexing basis


def test_non_castle_crashers_runs_are_not_stored():
    w = StudentWorker("viper9")
    w.ingest(_raw_run("viper9", OTHER_XML, "RoverRescue", 0))
    w.recompute_and_write()
    assert db.list_goal_profiles("viper9") == []


def test_only_castle_crashers_runs_stored_in_mixed_session():
    w = StudentWorker("mixed1")
    w.ingest(_raw_run("mixed1", OTHER_XML, "RoverRescue", 0))  # run 0: unsupported
    w.ingest(_raw_run("mixed1", CC_XML, "CasteCrasherPlus", 1))  # run 1: profiled
    w.recompute_and_write()
    profs = db.list_goal_profiles("mixed1")
    assert [p["index"] for p in profs] == [1]  # only the CC run, at its true index


def test_disabled_flag_skips_goal_profiling(monkeypatch):
    import app.pipeline.workers as workers

    monkeypatch.setattr(workers, "GOAL_RECOGNITION_ENABLED", False)
    w = StudentWorker("off1")
    assert w.gstream is None
    w.ingest(_raw_run("off1", CC_XML, "CasteCrasherPlus", 0))
    w.recompute_and_write()
    assert db.list_goal_profiles("off1") == []


def test_reprofiling_is_idempotent_across_recomputes():
    w = StudentWorker("cobra11")
    w.ingest(_raw_run("cobra11", CC_XML, "CasteCrasherPlus", 0))
    w.recompute_and_write()
    w.ingest(_raw_run("cobra11", CC_XML, "CasteCrasherPlus", 1))
    w.recompute_and_write()
    w.recompute_and_write()  # extra recompute must not duplicate rows
    profs = db.list_goal_profiles("cobra11")
    assert [p["index"] for p in profs] == [0, 1]


def test_detail_endpoint_returns_goal_runs(client):
    w = StudentWorker("cobra12")
    for i in range(2):
        w.ingest(_raw_run("cobra12", CC_XML, "CasteCrasherPlus", i))
    w.recompute_and_write()
    db.tracked_add("cobra12")  # roster membership so the detail endpoint returns it

    r = client.get("/api/student_states/cobra12/")
    assert r.status_code == 200
    body = r.json()
    assert body["goal_recognition_enabled"] is True
    assert len(body["goal_runs"]) == 2

    gr0 = body["goal_runs"][0]
    assert gr0["index"] == 0 and gr0["status"] == "profiled"
    assert "clear_debris_zone" in {g["goal"] for g in gr0["goals"]}
    # every indicator carries a rung + uncertainty flags (evidence, not a score)
    inds = [i for g in gr0["goals"] for i in g["indicators"]]
    assert inds and all({"rung", "flags", "abstained"} <= set(i) for i in inds)
    # ...and the ordinal ladder the UI draws the climb from (labels + direction)
    assert all({"rung_labels", "direction", "absent_label"} <= set(i) for i in inds)
    weight = next(i for g in gr0["goals"] for i in g["indicators"] if i["name"] == "weight_cleared")
    assert weight["rung_labels"] == [
        "none",
        "initial_goal",
        "med_goal",
        "high_goal",
        "advanced_goal",
    ]
    assert weight["direction"] == "higher_is_better"
    # run-level outputs are surfaced too (boundary, fidelity, telemetry, diagnostics)
    assert isinstance(gr0["diagnostics"], list)
    summ = gr0["summary"]
    assert {"boundary_exceeded", "fidelity_verdict", "outcome_available"} <= set(summ)
    assert summ["outcome_available"] is False  # no playgroundData in this run
    # timeline + battery outputs are wired in
    assert gr0["timeline"] is not None and isinstance(gr0["timeline"]["events"], list)
    assert gr0["battery"] is not None
    assert gr0["battery"]["eligible"] is False  # a plain drive program reads no sensors
    # the purpose-1 rollup: every goal gets a claim on its ladder
    ru = gr0["rollup"]
    assert ru is not None and ru["provisional"] is False
    by_goal = {g["goal"]: g for g in ru["goals"]}
    assert set(by_goal) == {
        "clear_debris_zone",
        "remain_on_island",
        "engage_plow",
        "playground_engagement",
    }
    # no sensor -> no battery tests -> the banded goals abstain rather than guess
    cdz = by_goal["clear_debris_zone"]
    assert cdz["source"] == "battery" and cdz["rung"] is None and cdz["abstain_reason"]
    assert cdz["rungs"][0] == "little_no_capability"  # ladder reads weaker -> stronger
    plow = by_goal["engage_plow"]
    assert plow["source"] == "profile_derived" and plow["rung"] in plow["rungs"]
    # the provisional purpose-2 rubric: six dimensions on 0..max ladders
    rb = gr0["rubric"]
    assert rb["provisional"] is True
    dims = {d["dimension"]: d for d in rb["dimensions"]}
    assert len(dims) == 6
    assert dims["control_structure"]["max_level"] == 3
    assert all(d["level"] is None or 0 <= d["level"] <= d["max_level"] for d in dims.values())


# A sensing conditional gating motion inside a forever loop: reads the distance
# sensor, so the 19-scenario battery is eligible.
SENSING_XML = (
    f'<xml {NS}><block type="pg_events_when_started" id="A"><next>'
    '<block type="pg_control_forever" id="f"><statement name="SUBSTACK">'
    '<block type="pg_control_if_then_else" id="if">'
    '<value name="CONDITION"><block type="pg_sensing_distance_object_distance" id="s"/></value>'
    '<statement name="SUBSTACK"><block type="pg_drivetrain_turn_for" id="t">'
    '<field name="TURNDIRECTION">right</field><field name="UNITS">deg</field>'
    '<value name="AMOUNT"><shadow type="math_number"><field name="NUM">90</field></shadow></value>'
    "</block></statement>"
    '<statement name="SUBSTACK2"><block type="pg_drivetrain_drive_for" id="d">'
    '<field name="DIRECTION">fwd</field><field name="UNITS">mm</field>'
    '<value name="AMOUNT"><shadow type="math_number"><field name="NUM">200</field></shadow></value>'
    "</block></statement></block></statement></block></next></block></xml>"
)


def test_detail_endpoint_battery_rollup_and_rubric_for_a_sensing_program(client):
    w = StudentWorker("cobra14")
    w.ingest(_raw_run("cobra14", SENSING_XML, "CasteCrasherPlus", 0))
    w.recompute_and_write()
    db.tracked_add("cobra14")

    gr = client.get("/api/student_states/cobra14/").json()["goal_runs"][0]
    bat = gr["battery"]
    assert bat["eligible"] is True
    # every scenario is tagged with its card family + description
    assert len(bat["scenarios"]) == 19
    assert len({s["family"] for s in bat["scenarios"]}) == 7
    assert all(s["description"] for s in bat["scenarios"])
    assert "artifacts" not in bat  # internal sim data never reaches the client
    # the banded goals now have battery evidence behind them
    cdz = next(g for g in gr["rollup"]["goals"] if g["goal"] == "clear_debris_zone")
    assert cdz["rung"] in cdz["rungs"] and cdz["n_valid"] > 0
    # a sensing conditional in an exercised loop is a coordination relation (CS-2)
    dims = {d["dimension"]: d for d in gr["rubric"]["dimensions"]}
    assert dims["control_structure"]["level"] == 2
    assert dims["control_structure"]["evidence"] == ["production.coordination_relations"]


def test_an_engine_error_run_does_not_shift_later_runs():
    # A drive of round(Infinity) mm makes the simulator overflow. That run must
    # still take its run index (and just not be stored), or every later run's
    # goal evidence would be joined to the wrong edit-distance run.
    overflow = CC_XML.replace(
        '<shadow type="math_number"><field name="NUM">300</field></shadow>',
        '<block type="pg_operator_round"><value name="NUM"><shadow type="math_number">'
        '<field name="NUM">Infinity</field></shadow></value></block>',
    )
    assert overflow != CC_XML
    w = StudentWorker("cobra15")
    for i, xml in enumerate([CC_XML, overflow, SENSING_XML]):
        w.ingest(_raw_run("cobra15", xml, "CasteCrasherPlus", i))
    w.recompute_and_write()
    assert [r["status"] for r in w.gstream.runs] == ["profiled", "engine_error", "profiled"]
    profs = db.list_goal_profiles("cobra15")
    assert [p["index"] for p in profs] == [0, 2]
    # run 2 is the sensing program: its evidence sits on run 2, not run 1
    assert profs[1]["battery"]["eligible"] is True
