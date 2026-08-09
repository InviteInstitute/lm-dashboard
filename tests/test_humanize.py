"""The block humanizer: readable name -> params, incl. the value-slot numbers
the edit-distance AST drops, nested reporters, and if/else branch labels."""

import json

from app import db
from app.runs.humanize import humanize_text, humanize_workspace


def _wrap(inner):
    return f"<xml>{inner}</xml>"


def _num(slot, n):
    return f'<value name="{slot}"><shadow type="math_number"><field name="NUM">{n}</field></shadow></value>'


def test_simple_block_is_just_its_name():
    assert humanize_workspace(_wrap('<block type="pg_drivetrain_stop_driving"/>')) == [
        "stop driving"
    ]


def test_keeps_the_value_number_and_hides_mutator_noise():
    xml = _wrap(
        '<block type="pg_drivetrain_drive_for">'
        '<field name="DIRECTION">fwd</field><field name="UNITS">mm</field>'
        '<field name="anddontwait_mutator">false</field>' + _num("AMOUNT", 200) + "</block>"
    )
    line = humanize_workspace(xml)[0]
    assert "drive for" in line and "forward" in line and "200" in line
    assert "mutator" not in line  # Blockly plumbing hidden


def test_unknown_block_falls_back_to_raw_type():
    assert humanize_workspace(_wrap('<block type="pg_brand_new_2099"/>')) == ["pg_brand_new_2099"]


def test_if_else_labels_the_else_branch():
    xml = _wrap(
        '<block type="pg_control_if_then_else">'
        '<value name="CONDITION"><block type="pg_operator_comparison"><field name="COMPARISON">&lt;</field>'
        '<value name="NUM1"><block type="pg_sensing_distance_distance"><field name="DISTANCE">frontdistance</field></block></value>'
        + _num("NUM2", 200)
        + "</block></value>"
        '<statement name="SUBSTACK"><block type="pg_drivetrain_drive"><field name="DIRECTION">fwd</field></block></statement>'
        '<statement name="SUBSTACK2"><block type="pg_drivetrain_stop_driving"/></statement></block>'
    )
    lines = humanize_workspace(xml)
    assert any("object distance" in l and "< 200" in l for l in lines)  # condition rendered
    assert "else:" in [l.strip() for l in lines]  # branch labeled
    assert "  drive forward" in lines and "  stop driving" in lines  # both bodies indented


def test_nested_reporters_recurse_to_any_depth():
    # if ( not ( (object distance < 200) and eye near object ) )
    cond = (
        '<block type="pg_operator_not"><value name="OPERAND">'
        '<block type="pg_operator_and_or"><field name="CHECK">and</field>'
        '<value name="OPERAND1"><block type="pg_operator_comparison"><field name="COMPARISON">&lt;</field>'
        '<value name="NUM1"><block type="pg_sensing_distance_distance"><field name="DISTANCE">frontdistance</field></block></value>'
        + _num("NUM2", 200)
        + "</block></value>"
        '<value name="OPERAND2"><block type="pg_sensing_optical_near_object"><field name="OPTICAL">fronteye</field></block></value>'
        "</block></value></block>"
    )
    xml = _wrap(
        f'<block type="pg_control_if_then"><value name="CONDITION">{cond}</value>'
        '<statement name="SUBSTACK"><block type="pg_drivetrain_stop_driving"/></statement></block>'
    )
    top = humanize_workspace(xml)[0]
    assert "not (" in top and "and" in top and "< 200" in top  # full depth rendered


def test_range_operator_keeps_all_three_numbers():
    xml = _wrap(
        '<block type="pg_control_if_then"><value name="CONDITION">'
        '<block type="pg_operator_range"><field name="COMPARISON1">&lt;</field><field name="COMPARISON2">&lt;</field>'
        + _num("NUM1", 0)
        + _num("NUM2", 50)
        + _num("NUM3", 90)
        + "</block></value>"
        '<statement name="SUBSTACK"><block type="pg_drivetrain_stop_driving"/></statement></block>'
    )
    top = humanize_workspace(xml)[0]
    assert "0" in top and "50" in top and "90" in top  # none dropped


def test_bad_input_never_raises():
    assert humanize_workspace("") == []
    assert humanize_workspace("<xml><not closed") == []
    assert humanize_text(None) == ""


def test_detail_endpoint_exposes_readable_program(client, seed_state):
    sid = seed_state("cobra3")  # materialize state
    xml = (
        '<xml><block type="pg_drivetrain_drive_for"><field name="DIRECTION">fwd</field>'
        '<field name="UNITS">mm</field>' + _num("AMOUNT", 200) + "</block></xml>"
    )
    db.insert_message_and_log(
        {
            "studentID": "cobra3",
            "classCode": "C1",
            "eventType": "blockMoved",
            "project": json.dumps({"workspace": xml}),
            "raw_message": "{}",
            "source_event_id": 1,
            "event_time": db.now(),
        }
    )
    readable = client.get(f"/api/student_states/{sid}/").json()["block"]["readable"]
    assert "drive for" in readable and "200" in readable
