"""
Turning two block ASTs into an integer edit_distance via tree-edit distance.

This converts an AST dict into an APTED tree and applies a Blockly-specific edit
cost configuration (Hyeongjo's colab costs, see constants.py) whose result is the
raw integer tree-edit distance. 0 means identical; larger means more rewritten.
The five triggers are defined directly on this number.
"""
import hashlib
from collections import defaultdict
from apted import APTED, Config

from app.constants import (
    BLOCK_DELETE_COST, BLOCK_INSERT_COST, EDGE_DELETE_COST, EDGE_INSERT_COST,
    FIELD_CHANGE_COST, TYPE_CHANGE_COST, EDGE_CHANGE_COST,
)


# Distance cache, append-only and never invalidated: edit_distance is a pure
# function of its two XML inputs, so a result is good forever. Keyed by the SHA1
# pair of the two workspace XMLs and kept in memory for the life of the process.
_distance_cache = {}


def clear_cache():
    """Drop the memoized distances. Called on a dashboard reset so the cache doesn't
    carry a wiped session's entries (and grow unbounded) across the daemon's life."""
    _distance_cache.clear()


def _xml_hash(xml_string):
    return hashlib.sha1(xml_string.encode("utf-8")).hexdigest()


def cached_edit_distance(prev_xml, curr_xml, prev_ast, curr_ast):
    """compute_edit_distance with memoization on the XML pair. Identical XML
    short-circuits to 0 without building any tree."""
    if prev_xml == curr_xml:
        return 0
    key = (_xml_hash(prev_xml), _xml_hash(curr_xml))
    cached = _distance_cache.get(key)
    if cached is not None:
        return cached
    dist = compute_edit_distance(prev_ast, curr_ast)
    _distance_cache[key] = dist
    return dist


class AptedNode:
    def __init__(self, name, node_type=None, fields=None):
        self.name = name
        self.node_type = node_type
        self.fields = fields or {}
        self.children = []

    def add_child(self, node):
        self.children.append(node)


def _make_node_label(node_info, include_fields=True, field_keys=None):
    block_type = node_info.get("type", "unknown")
    fields = dict(node_info.get("fields", {}))
    if not include_fields:
        return block_type
    if field_keys is not None:
        fields = {k: v for k, v in fields.items() if k in field_keys}
    if not fields:
        return block_type
    field_str = "|".join(f"{k}={fields[k]}" for k in sorted(fields))
    return f"{block_type}|{field_str}"


def ast_to_apted_tree(ast_dict, include_fields=True, field_keys=None, include_edge_nodes=True):
    """Convert an AST dict ({nodes, edges, roots}) into an APTED tree of
    AptedNodes. Children are ordered deterministically (value, then statement,
    then next, each by their recorded order). With include_edge_nodes set, every
    edge becomes its own intermediate node so the edit distance also accounts for
    how blocks are connected, not just which blocks exist. Multiple roots are
    gathered under a synthetic ROOT node."""
    nodes = ast_dict.get("nodes", {})
    edges = ast_dict.get("edges", [])
    roots = ast_dict.get("roots", [])

    children_map = defaultdict(list)
    for e in edges:
        children_map[e["source"]].append(e)

    edge_priority = {"value": 0, "statement": 1, "next": 2}

    def edge_sort_key(e):
        return (edge_priority.get(e.get("edge_type"), 9), e.get("order", 0))

    for pid in children_map:
        children_map[pid] = sorted(children_map[pid], key=edge_sort_key)

    def build_subtree(node_id):
        info = nodes[node_id]
        label = _make_node_label(info, include_fields=include_fields, field_keys=field_keys)
        root_node = AptedNode(name=label, node_type=info.get("type"), fields=info.get("fields", {}))

        for e in children_map.get(node_id, []):
            child_tree = build_subtree(e["target"])
            if include_edge_nodes:
                edge_label = (
                    e["edge_type"] if e.get("slot") is None
                    else f"{e['edge_type']}:{e['slot']}"
                )
                edge_node = AptedNode(name=edge_label, node_type="__edge__", fields={})
                edge_node.add_child(child_tree)
                root_node.add_child(edge_node)
            else:
                root_node.add_child(child_tree)
        return root_node

    if len(roots) == 0:
        return AptedNode("EMPTY")
    if len(roots) == 1:
        return build_subtree(roots[0])

    super_root = AptedNode("ROOT")
    for r in roots:
        super_root.add_child(build_subtree(r))
    return super_root


class BlocklyConfig(Config):
    """APTED cost model matching Hyeongjo's colab. Block insert/delete cost 1.0;
    edge nodes (the synthetic connectors our AST inserts between parent and child)
    cost 0 to add/remove, so adding one real block scores 1, not 2. A rename is
    free when labels match, field_change_cost when only fields differ within the
    same block type, and type_change_cost when the block type itself changes."""

    def delete(self, node):
        return EDGE_DELETE_COST if node.node_type == "__edge__" else BLOCK_DELETE_COST

    def insert(self, node):
        return EDGE_INSERT_COST if node.node_type == "__edge__" else BLOCK_INSERT_COST

    def rename(self, n1, n2):
        if n1.name == n2.name:
            return 0.0
        if n1.node_type == "__edge__" or n2.node_type == "__edge__":
            return EDGE_CHANGE_COST
        if n1.node_type == n2.node_type:
            return FIELD_CHANGE_COST
        return TYPE_CHANGE_COST


def compute_edit_distance(ast_prev, ast_curr):
    """The raw APTED tree-edit distance between two run ASTs (a whole number under
    the edge-aware cost model). 0 means identical."""
    t1 = ast_to_apted_tree(ast_prev)
    t2 = ast_to_apted_tree(ast_curr)
    return int(round(APTED(t1, t2, BlocklyConfig()).compute_edit_distance()))
