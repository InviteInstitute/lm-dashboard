"""The smart-delta engine's live block-event path (process_log and friends).
This is the branch the playground entry point doesn't exercise, driven directly
here so it stays covered (and correct) rather than rotting."""
import json

from app.smart_delta_engine import SmartDeltaEngine


def _evt(block_event):
    """A raw log_event whose content carries a blockEventData delta."""
    return {"content": json.dumps({"eventType": "userAction",
                                   "blockEventData": json.dumps(block_event)})}


def test_create_adds_an_orphan_block():
    e = SmartDeltaEngine()
    e.process_log(_evt({"eventType": "create", "blockID": "b1", "blockType": "motor_on"}))
    assert e.get_total_blocks() == 1
    assert e.orphan_status["b1"] is True
    assert e.get_runnable_block_count() == 0      # orphan isn't runnable


def test_shadow_blocks_are_ignored_on_create():
    e = SmartDeltaEngine()
    e.process_log(_evt({"eventType": "create", "blockID": "s", "blockType": "math_shadow"}))
    assert e.get_total_blocks() == 0


def test_move_under_parent_inherits_orphan_status_and_links():
    e = SmartDeltaEngine()
    e.process_log(_evt({"eventType": "create", "blockID": "hat", "blockType": "events_start"}))
    e.process_log(_evt({"eventType": "create", "blockID": "b1", "blockType": "motor_on"}))
    e.orphan_status["hat"] = False                # pretend the hat is runnable
    e.process_log(_evt({"eventType": "move", "blockID": "b1", "newInfo": {"parent": "hat"}}))
    assert "b1" in e.parent_map["hat"]
    assert e.orphan_status["b1"] is False         # cascaded from the parent


def test_move_to_coordinate_orphans_the_block():
    e = SmartDeltaEngine()
    e.process_log(_evt({"eventType": "create", "blockID": "b1", "blockType": "motor_on"}))
    e.process_log(_evt({"eventType": "move", "blockID": "b1",
                        "newInfo": {"coordinate": {"x": 5, "y": 9}}}))
    assert e.orphan_status["b1"] is True
    assert e.blocks["b1"]["x"] == 5


def test_delete_removes_block_and_severs_parent():
    e = SmartDeltaEngine()
    e.process_log(_evt({"eventType": "create", "blockID": "hat", "blockType": "events_start"}))
    e.process_log(_evt({"eventType": "create", "blockID": "b1", "blockType": "motor_on"}))
    e.process_log(_evt({"eventType": "move", "blockID": "b1", "newInfo": {"parent": "hat"}}))
    e.process_log(_evt({"eventType": "delete", "blockID": "b1"}))
    assert "b1" not in e.blocks
    assert "hat" not in e.parent_map               # the now-childless link was severed


def test_change_updates_a_field():
    e = SmartDeltaEngine()
    e.process_log(_evt({"eventType": "create", "blockID": "b1", "blockType": "motor_on"}))
    e.process_log(_evt({"eventType": "change", "blockID": "b1", "name": "PORT", "newValue": "A"}))
    assert e.blocks["b1"]["fields"]["PORT"] == "A"


def test_malformed_events_are_ignored():
    e = SmartDeltaEngine()
    e.process_log({"content": "not json"})                       # bad content
    e.process_log(_evt({"eventType": "create"}))                 # no blockID
    e.process_log({"content": json.dumps({"eventType": "x"})})   # no blockEventData
    # blockEventData present but not valid JSON
    e.process_log({"content": json.dumps({"eventType": "x", "blockEventData": "{bad"})})
    assert e.get_total_blocks() == 0


def test_prompt_with_only_orphan_blocks_shows_empty_active():
    e = SmartDeltaEngine()
    e.process_log(_evt({"eventType": "create", "blockID": "b1", "blockType": "motor_on"}))
    prompt = e.generate_llm_prompt()
    active = prompt.split("[Orphaned]")[0]
    assert "(empty)" in active                # nothing runnable -> Active is empty
    assert "motor_on" in prompt               # the orphan still appears


def test_loadproject_event_bootstraps_from_xml():
    e = SmartDeltaEngine()
    xml = '<xml><block type="events_whenStarted" id="a"></block></xml>'
    e.process_log({"content": json.dumps({"eventType": "loadProject",
                                          "project": json.dumps({"workspace": xml})})})
    assert e.get_total_blocks() == 1
    assert e.get_runnable_block_count() == 1       # the hat block is runnable
