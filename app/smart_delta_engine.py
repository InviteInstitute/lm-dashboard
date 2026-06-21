"""
A pared-down Smart-Delta Engine for reading VEX block-workspace state.

Adapted from Vex-LM-Pipeline/state_engine/smart_delta/engine.py, but kept to
the standard library (json, xml.etree) rather than orjson/lxml so it has no
extra dependencies.

It reconstructs a workspace two ways: by replaying create/move/delete/change
deltas from the event stream, or by bootstrapping straight from a project's XML.
Either way it ends up with flat block / parent / orphan maps, and can render
them as a compact pseudo-code "prompt" that's cheap to feed to an LLM.
"""
import json
import xml.etree.ElementTree as ET


class SmartDeltaEngine:
    # The "hat" block types that can start a program (event handlers and
    # procedure definitions). At the workspace root, only these count as active;
    # any other block sitting loose at the top level is treated as an orphan.
    HAT_BLOCK_PATTERNS = ('events_', 'procedures_definition')

    def __init__(self):
        self.blocks = {}         # block_id -> {type, x, y, fields}
        self.parent_map = {}     # parent_id -> [child_id, ...]
        self.orphan_status = {}  # block_id -> bool (True == not reachable from a hat)

    def process_log(self, log_event):
        """Fold a single VEX log event into the current workspace state. A
        loadProject/newProject event rebuilds from scratch; the block-level
        create/move/delete/change events mutate the maps incrementally. Anything
        unparseable or irrelevant is silently ignored."""
        try:
            content = json.loads(log_event.get('content', '{}'))
        except Exception:
            return

        event_type = content.get('eventType')

        # A load/new event resets everything and re-derives state from the XML.
        if event_type in ('loadProject', 'newProject'):
            self._bootstrap_from_xml(content)
            return

        # Otherwise it's an incremental block delta.
        raw_block_data = content.get('blockEventData')
        if not raw_block_data:
            return

        try:
            block_data = json.loads(raw_block_data)
        except Exception:
            return

        b_type = block_data.get('eventType')
        block_id = block_data.get('blockID')

        if not block_id:
            return

        if b_type == 'create':
            block_type = block_data.get('blockType', '')
            if 'shadow' not in block_type.lower():
                self.blocks[block_id] = {
                    'type': block_type,
                    'x': None,
                    'y': None,
                    'fields': {}
                }
                self.orphan_status[block_id] = True

        elif b_type == 'move':
            self._sever_from_parents(block_id)

            new_info = block_data.get('newInfo', {})

            if 'parent' in new_info:
                new_parent = new_info['parent']
                self.parent_map.setdefault(new_parent, []).append(block_id)

                # Clear floating coordinates since it's now attached
                if block_id in self.blocks:
                    self.blocks[block_id]['x'] = None
                    self.blocks[block_id]['y'] = None

                p_orphan = self.orphan_status.get(new_parent, False)
                self.orphan_status[block_id] = p_orphan
                self._cascade_orphan(block_id, p_orphan, set())

            elif 'coordinate' in new_info:
                coord = new_info['coordinate']
                if block_id in self.blocks:
                    self.blocks[block_id]['x'] = coord.get('x')
                    self.blocks[block_id]['y'] = coord.get('y')

                self.orphan_status[block_id] = True
                self._cascade_orphan(block_id, True, set())

        elif b_type == 'delete':
            self._sever_from_parents(block_id)
            self._delete_recursive(block_id, set())

        elif b_type == 'change':
            field_name = block_data.get('name')
            new_value = block_data.get('newValue')
            if block_id in self.blocks and field_name:
                self.blocks[block_id]['fields'][field_name] = new_value

    def _sever_from_parents(self, block_id):
        keys_to_remove = []
        for p_id, children in self.parent_map.items():
            if block_id in children:
                children.remove(block_id)
                if not children:
                    keys_to_remove.append(p_id)
        for k in keys_to_remove:
            del self.parent_map[k]

    def _bootstrap_from_xml(self, content):
        """Throw away the current maps and rebuild them by walking the project's
        workspace XML. A block at the root is active only if it's a hat block;
        children inherit their parent's orphan status as the walk descends."""
        self.blocks.clear()
        self.parent_map.clear()
        self.orphan_status.clear()

        project_raw = content.get('project', '{}')
        try:
            project = json.loads(project_raw) if isinstance(project_raw, str) else project_raw
        except Exception:
            project = {}

        xml_string = project.get('workspace', '')
        if not xml_string:
            return

        try:
            root = ET.fromstring(xml_string)
        except Exception:
            return

        def traverse(node, current_parent=None):
            tag_name = node.tag.split('}')[-1]

            if tag_name == 'block':
                b_id = node.get('id')
                b_type = node.get('type', 'unknown')
                b_x = node.get('x')
                b_y = node.get('y')

                # Extract field values from immediate <field> children
                fields = {}
                for child in node:
                    child_tag = child.tag.split('}')[-1]
                    if child_tag == 'field':
                        fname = child.get('name')
                        if fname:
                            fields[fname] = child.text or ''

                self.blocks[b_id] = {
                    'type': b_type,
                    'x': float(b_x) if b_x else None,
                    'y': float(b_y) if b_y else None,
                    'fields': fields
                }

                if current_parent is None:
                    # Top-level block: only hat blocks (event handlers,
                    # procedure defs) are active. Everything else is orphaned.
                    is_hat = any(p in b_type for p in self.HAT_BLOCK_PATTERNS)
                    self.orphan_status[b_id] = not is_hat
                else:
                    self.orphan_status[b_id] = self.orphan_status.get(current_parent, False)
                    self.parent_map.setdefault(current_parent, []).append(b_id)

                for t in node:
                    traverse(t, b_id)

            elif tag_name == 'shadow':
                pass
            else:
                for t in node:
                    traverse(t, current_parent)

        traverse(root)

    def _cascade_orphan(self, parent_id, status, visited=None):
        if visited is None:
            visited = set()
        if parent_id in visited:
            return
        visited.add(parent_id)

        children = self.parent_map.get(parent_id, [])
        for c in children:
            self.orphan_status[c] = status
            self._cascade_orphan(c, status, visited)

    def _delete_recursive(self, block_id, visited=None):
        if visited is None:
            visited = set()
        if block_id in visited:
            return
        visited.add(block_id)

        if block_id in self.blocks:
            del self.blocks[block_id]
        if block_id in self.orphan_status:
            del self.orphan_status[block_id]

        children = self.parent_map.pop(block_id, [])
        for c in children:
            self._delete_recursive(c, visited)

    def get_runnable_block_count(self):
        return sum(1 for b in self.blocks if not self.orphan_status.get(b, True))

    def get_total_blocks(self):
        return len(self.blocks)

    def generate_llm_prompt(self):
        """Render the current workspace as compact pseudo-code for an LLM. Roots
        are split into an [Active] section (reachable from a hat block) and an
        [Orphaned] section, each block printed with its fields and indented by
        depth. Common VEX type prefixes are stripped to save tokens."""
        all_children = set()
        for children in self.parent_map.values():
            all_children.update(children)

        roots = [b for b in self.blocks if b not in all_children]
        roots.sort()

        runnable_roots = [b for b in roots if not self.orphan_status.get(b, True)]
        orphan_roots = [b for b in roots if self.orphan_status.get(b, True)]

        def clean_type(raw):
            """Strip common VEX prefixes to save tokens."""
            for prefix in ('pg_', 'aim_', 'mixed_'):
                if raw.startswith(prefix):
                    return raw[len(prefix):]
            return raw

        def build_tree(block_id, depth, visited=None):
            if visited is None:
                visited = set()
            if block_id in visited:
                return ""
            visited.add(block_id)

            block = self.blocks.get(block_id, {})
            name = clean_type(block.get('type', '?'))
            fields = block.get('fields', {})

            parts = [name]
            if fields:
                parts.append("(" + ",".join(f'{k}={v}' for k, v in fields.items()) + ")")

            line = " " * depth + " ".join(parts) + "\n"

            for child in self.parent_map.get(block_id, []):
                line += build_tree(child, depth + 1, visited)
            return line

        lines = []
        lines.append("[Active]")
        if runnable_roots:
            for r in runnable_roots:
                lines.append(build_tree(r, 1).rstrip())
        else:
            lines.append(" (empty)")

        lines.append("[Orphaned]")
        if orphan_roots:
            for o in orphan_roots:
                lines.append(build_tree(o, 1).rstrip())
        else:
            lines.append(" (empty)")

        return "\n".join(lines)


def generate_llm_prompt_from_project(project_json_str):
    """One-shot helper: take a raw project JSON string (the kind stored in a
    VEX log's `project` field), bootstrap a fresh engine from it, and return the
    rendered prompt. Returns None if the input is None or yields no blocks."""
    if project_json_str is None:
        return None

    engine = SmartDeltaEngine()

    # Wrap in a synthetic loadProject event for _bootstrap_from_xml
    engine._bootstrap_from_xml({
        'eventType': 'loadProject',
        'project': project_json_str
    })

    if not engine.blocks:
        return None

    return engine.generate_llm_prompt()
