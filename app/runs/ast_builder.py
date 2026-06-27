"""
Parsing a Blockly workspace XML into an AST-like dict.

This is the XML -> AST step from Hyeongjo's Colab, same logic with a cleanup
pass. The returned shape deliberately matches the Colab's `xml_to_block_ast`, so
the downstream APTED conversion behaves identically to training.
"""
import json
import xml.etree.ElementTree as ET


def _strip_namespace(elem):
    if "}" in elem.tag:
        elem.tag = elem.tag.split("}", 1)[1]
    for child in elem:
        _strip_namespace(child)


def _parse_xml_string(xml_string):
    root = ET.fromstring(xml_string)
    _strip_namespace(root)
    return root


def _get_immediate_fields(block_elem):
    fields = {}
    for child in block_elem:
        if child.tag == "field":
            name = child.attrib.get("name")
            if name:
                fields[name] = (child.text or "").strip()
    return fields


def _get_block_node_info(block_elem):
    return {
        "id": block_elem.attrib.get("id"),
        "type": block_elem.attrib.get("type", "unknown"),
        "fields": _get_immediate_fields(block_elem),
    }


def _find_child_blocks(container_elem, allow_shadow=False):
    out = []
    for child in container_elem:
        if child.tag == "block":
            out.append(child)
        elif allow_shadow and child.tag == "shadow":
            out.append(child)
    return out


def xml_to_block_ast(xml_string, keep_shadow=False):
    """Parse workspace XML into {nodes, edges, roots}, the AST shape the Colab
    used. nodes maps block id to type+fields, edges record parent/child links
    tagged by connection kind (value/statement/next) and slot, and roots lists
    the top-level blocks. Shadow blocks are dropped unless keep_shadow is set,
    and a blank input yields an empty AST."""
    if not xml_string:
        return {"nodes": {}, "edges": [], "roots": []}

    root = _parse_xml_string(xml_string)
    nodes, edges, roots = {}, [], []

    def register(block_elem):
        info = _get_block_node_info(block_elem)
        bid = info["id"] or f"generated_{len(nodes)}"
        info["id"] = bid
        nodes[bid] = {"type": info["type"], "fields": info["fields"]}
        return bid

    def traverse(block_elem, parent_id=None, edge_type=None, slot=None, order=0, is_root=False):
        if block_elem.tag == "shadow" and not keep_shadow:
            return None

        current_id = register(block_elem)
        if is_root:
            roots.append(current_id)
        if parent_id is not None:
            edges.append({
                "source": parent_id, "target": current_id,
                "edge_type": edge_type, "slot": slot, "order": order,
            })

        for child in block_elem:
            if child.tag in ("next", "statement", "value"):
                slot_name = child.attrib.get("name") if child.tag != "next" else None
                nested = _find_child_blocks(child, allow_shadow=keep_shadow)
                for i, nb in enumerate(nested):
                    traverse(nb, parent_id=current_id, edge_type=child.tag,
                             slot=slot_name, order=i, is_root=False)
        return current_id

    for child in root:
        if child.tag == "block":
            traverse(child, is_root=True)
        elif child.tag == "shadow" and keep_shadow:
            traverse(child, is_root=True)

    return {"nodes": nodes, "edges": edges, "roots": roots}


def extract_workspace_xml(log_content):
    """Dig the workspace XML string out of a parsed log content dict, handling
    the project field arriving either as a nested dict or as a JSON string.
    Returns "" when there's nothing usable."""
    project = log_content.get("project", {}) if isinstance(log_content, dict) else {}
    if isinstance(project, str):
        try:
            project = json.loads(project)
        except json.JSONDecodeError:
            return ""
    if not isinstance(project, dict):
        return ""
    return project.get("workspace", "") or ""
