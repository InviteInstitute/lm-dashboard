"""APTED similarity: node labels, AST->tree conversion, the integer edit_distance,
and the distance cache."""

from learner_models import distance as A
from learner_models import xml_to_block_ast


def test_tree_always_hangs_off_one_workspace_root():
    # One fixed root whatever the number of stacks, so adding a stack costs only
    # its blocks.
    assert A.ast_to_apted_tree({"nodes": {}, "edges": [], "roots": []}).children == []

    single = {"nodes": {"a": {"type": "hat", "fields": {}}}, "edges": [], "roots": ["a"]}
    assert [c.node_type for c in A.ast_to_apted_tree(single).children] == ["hat"]

    multi = {
        "nodes": {"a": {"type": "hat", "fields": {}}, "b": {"type": "hat2", "fields": {}}},
        "edges": [],
        "roots": ["a", "b"],
    }
    assert [c.node_type for c in A.ast_to_apted_tree(multi).children] == ["hat", "hat2"]


def test_connection_is_part_of_the_child_node():
    ast = {
        "nodes": {"a": {"type": "hat", "fields": {}}, "b": {"type": "motor", "fields": {"P": "A"}}},
        "edges": [
            {"source": "a", "target": "b", "edge_type": "statement", "slot": "DO", "order": 0}
        ],
        "roots": ["a"],
    }
    child = A.ast_to_apted_tree(ast).children[0].children[0]
    assert child.node_type == "motor"
    assert child.name == (("statement", "DO"), ("motor", (("P", "A"),)))


def test_field_only_change_costs_one():
    a = xml_to_block_ast(
        '<xml><block type="motor_on" id="b"><field name="PORT">A</field></block></xml>'
    )
    b = xml_to_block_ast(
        '<xml><block type="motor_on" id="b"><field name="PORT">B</field></block></xml>'
    )
    assert A.compute_edit_distance(a, b) == 1


def test_rename_cost_field_type_and_connection_change():
    cfg = A.VexConfig()
    nxt, body = ("next", None), ("statement", "DO")

    def node(conn, btype, port):
        return A.AptedNode(btype, conn, (btype, (("PORT", port),) if port else ()))

    same = node(nxt, "motor", "A")
    assert cfg.rename(same, node(nxt, "motor", "A")) == 0.0  # identical: free
    assert cfg.rename(same, node(nxt, "motor", "B")) == A.FIELD_CHANGE_COST
    assert cfg.rename(same, node(nxt, "sensor", None)) == A.TYPE_CHANGE_COST
    assert cfg.rename(same, node(body, "motor", "A")) == A.EDGE_CHANGE_COST  # moved
    assert cfg.rename(same, node(body, "motor", "B")) == 1.0  # moved and edited: the largest
