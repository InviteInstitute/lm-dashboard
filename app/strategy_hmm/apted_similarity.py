"""
Turning two block ASTs into a change_score via tree-edit distance.

This converts an AST dict into an APTED tree, applies a Blockly-specific edit
cost configuration, and normalizes the resulting edit distance into a score in
[0, 1]. The costs and the normalization are reproduced from Hyeongjo's Colab and
must match training exactly (see constants.py), so don't touch them without
re-aligning the model.
"""
import hashlib
from collections import defaultdict
from apted import APTED, Config

from app.constants import (
    DELETION_COST, INSERTION_COST, FIELD_CHANGE_COST,
    TYPE_CHANGE_COST, EDGE_CHANGE_COST, SIMILARITY_SMOOTHING,
)


# Score cache, append-only and never invalidated: change_score is a pure
# function of its two XML inputs, so a result is good forever. Keyed by the SHA1
# pair of the two workspace XMLs and kept in memory for the life of the process.
_score_cache = {}


def _xml_hash(xml_string):
    return hashlib.sha1(xml_string.encode("utf-8")).hexdigest()


def cached_change_score(prev_xml, curr_xml, prev_ast, curr_ast):
    """compute_change_score with memoization on the XML pair. Identical XML
    short-circuits to 0.0 without building any tree."""
    if prev_xml == curr_xml:
        return 0.0
    key = (_xml_hash(prev_xml), _xml_hash(curr_xml))
    cached = _score_cache.get(key)
    if cached is not None:
        return cached
    score = compute_change_score(prev_ast, curr_ast)
    _score_cache[key] = score
    return score


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
    """APTED cost model for Blockly trees. Insert/delete cost a flat amount; a
    rename is free when labels match, cheap (field_change_cost) when only fields
    differ within the same block type, and full price (type_change_cost) when the
    block type itself changes. Edge nodes use their own edge_change_cost."""

    def __init__(self,
                 deletion_cost=DELETION_COST,
                 insertion_cost=INSERTION_COST,
                 field_change_cost=FIELD_CHANGE_COST,
                 type_change_cost=TYPE_CHANGE_COST,
                 edge_change_cost=EDGE_CHANGE_COST):
        self.deletion_cost_value = deletion_cost
        self.insertion_cost_value = insertion_cost
        self.field_change_cost = field_change_cost
        self.type_change_cost = type_change_cost
        self.edge_change_cost = edge_change_cost

    def delete(self, node):
        return self.deletion_cost_value

    def insert(self, node):
        return self.insertion_cost_value

    def rename(self, n1, n2):
        if n1.name == n2.name:
            return 0.0
        if n1.node_type == "__edge__" or n2.node_type == "__edge__":
            return self.edge_change_cost if n1.name != n2.name else 0.0
        if n1.node_type == n2.node_type:
            return self.field_change_cost
        return self.type_change_cost


def _count_tree_nodes(node):
    total = 1
    for c in node.children:
        total += _count_tree_nodes(c)
    return total


def compute_change_score(ast_prev, ast_curr):
    """Score how much two consecutive runs differ, in [0, 1]: 0 means identical,
    larger means more rewritten. Computes the APTED edit distance between the two
    trees, turns it into a size-normalized similarity (with SIMILARITY_SMOOTHING
    to keep tiny trees from swinging the score), and returns 1 - similarity."""
    t1 = ast_to_apted_tree(ast_prev)
    t2 = ast_to_apted_tree(ast_curr)
    dist = APTED(t1, t2, BlocklyConfig()).compute_edit_distance()
    max_size = max(_count_tree_nodes(t1), _count_tree_nodes(t2))
    if max_size == 0:
        return 0.0
    sim = 1.0 - (dist / (max_size + SIMILARITY_SMOOTHING))
    sim = max(0.0, sim)
    return 1.0 - sim
