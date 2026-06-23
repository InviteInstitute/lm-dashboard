"""APTED similarity: node labels, AST->tree conversion, the change-score
normalization, and the score cache."""
from app.strategy_hmm import apted_similarity as A
from app.strategy_hmm.ast_builder import xml_to_block_ast


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


def test_change_score_identical_is_zero_and_differs_is_positive():
    a = xml_to_block_ast('<xml><block type="events_whenStarted" id="a"></block></xml>')
    b = xml_to_block_ast('<xml><block type="events_whenStarted" id="a">'
                         '<next><block type="motor_on" id="b"></block></next></block></xml>')
    assert A.compute_change_score(a, a) == 0.0
    score = A.compute_change_score(a, b)
    assert 0.0 < score <= 1.0


def test_cached_change_score_short_circuits_and_memoizes():
    xa = '<xml><block type="events_whenStarted" id="a"></block></xml>'
    xb = '<xml><block type="motor_on" id="b"></block></xml>'
    a, b = xml_to_block_ast(xa), xml_to_block_ast(xb)
    assert A.cached_change_score(xa, xa, a, a) == 0.0          # identical XML short-circuits
    s1 = A.cached_change_score(xa, xb, a, b)
    s2 = A.cached_change_score(xa, xb, a, b)                   # served from cache
    assert s1 == s2 and (A._xml_hash(xa), A._xml_hash(xb)) in A._score_cache


def test_rename_cost_field_vs_type_change():
    cfg = A.BlocklyConfig()
    same = A.AptedNode("motor|PORT=A", node_type="motor")
    same2 = A.AptedNode("motor|PORT=A", node_type="motor")
    field_diff = A.AptedNode("motor|PORT=B", node_type="motor")
    type_diff = A.AptedNode("sensor", node_type="sensor")
    assert cfg.rename(same, same2) == 0.0                     # identical labels: free
    assert cfg.rename(same, field_diff) == A.FIELD_CHANGE_COST   # same type, diff fields
    assert cfg.rename(same, type_diff) == A.TYPE_CHANGE_COST     # different block type
