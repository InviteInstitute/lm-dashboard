"""APTED similarity: node labels, AST->tree conversion, the integer edit_distance,
and the distance cache."""
from app.runs import apted_similarity as A
from app.runs.ast_builder import xml_to_block_ast


def test_make_node_label_variants():
    info = {"type": "motor_on", "fields": {"PORT": "A", "SPEED": "5"}}
    assert A._make_node_label(info, include_fields=False) == "motor_on"
    assert A._make_node_label({"type": "x", "fields": {}}) == "x"          # no fields
    assert A._make_node_label(info) == "motor_on|PORT=A|SPEED=5"           # sorted
    assert A._make_node_label(info, field_keys={"PORT"}) == "motor_on|PORT=A"


def test_ast_to_tree_empty_single_and_multi_root():
    assert A.ast_to_apted_tree({"nodes": {}, "edges": [], "roots": []}).name == "EMPTY"

    single = {"nodes": {"a": {"type": "hat", "fields": {}}}, "edges": [], "roots": ["a"]}
    assert A.ast_to_apted_tree(single).name == "hat"

    multi = {"nodes": {"a": {"type": "hat", "fields": {}}, "b": {"type": "hat2", "fields": {}}},
             "edges": [], "roots": ["a", "b"]}
    assert A.ast_to_apted_tree(multi).name == "ROOT"


def test_edge_nodes_toggle_changes_child_structure():
    ast = {
        "nodes": {"a": {"type": "hat", "fields": {}}, "b": {"type": "motor", "fields": {}}},
        "edges": [{"source": "a", "target": "b", "edge_type": "next", "slot": None, "order": 0}],
        "roots": ["a"],
    }
    with_edges = A.ast_to_apted_tree(ast, include_edge_nodes=True)
    without = A.ast_to_apted_tree(ast, include_edge_nodes=False)
    # with edge nodes, an intermediate __edge__ node sits between parent and child
    assert with_edges.children[0].node_type == "__edge__"
    assert without.children[0].node_type == "motor"


def test_identical_workspaces_distance_zero():
    ast = xml_to_block_ast('<xml><block type="events_whenStarted" id="a"></block></xml>')
    assert A.compute_edit_distance(ast, ast) == 0


def test_adding_one_block_costs_one():
    # one hat block -> hat block with a child; the edge node is free, so distance == 1
    a = xml_to_block_ast('<xml><block type="events_whenStarted" id="a"></block></xml>')
    b = xml_to_block_ast('<xml><block type="events_whenStarted" id="a">'
                         '<next><block type="motor_on" id="b"></block></next></block></xml>')
    assert A.compute_edit_distance(a, b) == 1


def test_field_only_change_costs_one():
    a = xml_to_block_ast('<xml><block type="motor_on" id="b"><field name="PORT">A</field></block></xml>')
    b = xml_to_block_ast('<xml><block type="motor_on" id="b"><field name="PORT">B</field></block></xml>')
    assert A.compute_edit_distance(a, b) == 1


def test_cached_edit_distance_short_circuits_and_memoizes():
    xa = '<xml><block type="events_whenStarted" id="a"></block></xml>'
    xb = '<xml><block type="motor_on" id="b"></block></xml>'
    a, b = xml_to_block_ast(xa), xml_to_block_ast(xb)
    A.clear_cache()
    assert A.cached_edit_distance(xa, xa, a, a) == 0           # identical XML short-circuits
    d1 = A.cached_edit_distance(xa, xb, a, b)
    d2 = A.cached_edit_distance(xa, xb, a, b)                  # served from cache
    assert d1 == d2 and (A._xml_hash(xa), A._xml_hash(xb)) in A._distance_cache


def test_rename_cost_field_vs_type_change():
    cfg = A.BlocklyConfig()
    same = A.AptedNode("motor|PORT=A", node_type="motor")
    same2 = A.AptedNode("motor|PORT=A", node_type="motor")
    field_diff = A.AptedNode("motor|PORT=B", node_type="motor")
    type_diff = A.AptedNode("sensor", node_type="sensor")
    assert cfg.rename(same, same2) == 0.0                     # identical labels: free
    assert cfg.rename(same, field_diff) == A.FIELD_CHANGE_COST   # same type, diff fields
    assert cfg.rename(same, type_diff) == A.TYPE_CHANGE_COST     # different block type
