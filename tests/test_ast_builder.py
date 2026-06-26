"""XML -> block AST parsing: fields, shadow handling, nesting, and the
workspace-XML extraction helper."""
from app.strategy_hmm.ast_builder import xml_to_block_ast, extract_workspace_xml


def test_empty_input_yields_empty_ast():
    out = xml_to_block_ast("")
    assert out == {"nodes": {}, "edges": [], "roots": []}


def test_single_block_with_field():
    xml = '<xml><block type="motor_on" id="b1"><field name="PORT">A</field></block></xml>'
    out = xml_to_block_ast(xml)
    assert out["roots"] == ["b1"]
    assert out["nodes"]["b1"]["type"] == "motor_on"
    assert out["nodes"]["b1"]["fields"]["PORT"] == "A"


def test_nested_block_creates_edge():
    xml = ('<xml><block type="events_whenStarted" id="a">'
           '<next><block type="motor_on" id="b"></block></next></block></xml>')
    out = xml_to_block_ast(xml)
    assert out["roots"] == ["a"]
    assert {"source": "a", "target": "b", "edge_type": "next", "slot": None, "order": 0} in out["edges"]


def test_shadow_dropped_by_default_kept_when_requested():
    xml = '<xml><shadow type="math_number" id="s"></shadow></xml>'
    assert xml_to_block_ast(xml)["roots"] == []                       # shadow dropped
    assert xml_to_block_ast(xml, keep_shadow=True)["roots"] == ["s"]  # kept


def test_shadow_inside_a_value_kept_when_requested():
    xml = ('<xml><block type="math_arithmetic" id="a">'
           '<value name="A"><shadow type="math_number" id="s"></shadow></value></block></xml>')
    # default: the shadow child is dropped; with keep_shadow it becomes a real edge
    assert xml_to_block_ast(xml)["edges"] == []
    kept = xml_to_block_ast(xml, keep_shadow=True)
    assert any(e["target"] == "s" for e in kept["edges"])


def test_block_without_id_gets_generated_id():
    xml = '<xml><block type="motor_on"></block></xml>'
    out = xml_to_block_ast(xml)
    assert len(out["roots"]) == 1 and out["roots"][0].startswith("generated_")


def test_extract_workspace_xml_from_dict_and_json_string():
    assert extract_workspace_xml({"project": {"workspace": "<xml/>"}}) == "<xml/>"
    assert extract_workspace_xml({"project": '{"workspace": "<xml/>"}'}) == "<xml/>"


def test_extract_workspace_xml_handles_bad_and_missing():
    assert extract_workspace_xml({"project": "not json"}) == ""
    assert extract_workspace_xml({}) == ""
    assert extract_workspace_xml("not a dict") == ""
    assert extract_workspace_xml({"project": {}}) == ""


def test_extract_workspace_xml_rejects_parsed_non_dict():
    # A project string that parses to valid JSON but isn't an object (a list here)
    # must yield "" rather than crashing on .get().
    assert extract_workspace_xml({"project": "[1, 2, 3]"}) == ""


def test_namespaced_xml_is_stripped_and_parsed():
    # Blockly sometimes emits a default xmlns; ElementTree tags become "{uri}block".
    # _strip_namespace must peel that off so block types resolve normally.
    xml = ('<xml xmlns="https://developers.google.com/blockly/xml">'
           '<block type="motor_on" id="b1"></block></xml>')
    out = xml_to_block_ast(xml)
    assert out["roots"] == ["b1"]
    assert out["nodes"]["b1"]["type"] == "motor_on"
