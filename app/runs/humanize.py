"""
Turning a VEX Blockly workspace into a readable program listing.

This is a display-only layer: it parses the workspace XML on its own and never
touches app/runs/ast_builder.py or the APTED edit-distance path, so it can't
shift the trigger signal. Feature request #12 (from BL and NS): the alert/detail
views showed block *types* but not their parameters -- most importantly the
numbers, like how far a student drives. Those numbers live in `<value>` shadow
slots that the edit-distance parser drops; here we keep them.

The rendering rule is one idea applied recursively:
  * statement / next children  -> stacked lines, indented (loop and if bodies)
  * value children             -> rendered INLINE into the parent (conditions,
                                  sensor reads, math), a reporter drops into a
                                  socket rather than sitting in the stack.

Block names come from vex_blocks.json (the official VEX mapping, blocks + robots
+ python merged). An unknown/new block falls back to its raw type, so a stale
mapping never breaks -- it just shows a raw name until the file is refreshed.
"""
import json
import os
import xml.etree.ElementTree as ET

_MAP_PATH = os.path.join(os.path.dirname(__file__), "vex_blocks.json")

# type -> display name, merged across the mapping's sections (blocks win, then
# robots, then python) and loaded once at import.
_NAMES = {}
try:
    _raw = json.load(open(_MAP_PATH, encoding="utf-8"))
    for _section in ("python", "robots", "blocks"):     # blocks last so it wins
        for _t, _info in (_raw.get(_section) or {}).items():
            _NAMES[_t] = (_info or {}).get("full_name", _t)
except (OSError, ValueError):
    _NAMES = {}

# Small enum tidy-ups so fields read like words, not tokens. Everything not here
# passes through unchanged -- the goal is name -> params, not full English.
_ENUM = {"fwd": "forward", "rev": "reverse", "pct": "%", "and": "and", "or": "or"}

# Operators that read best infix: type -> (operator field, [operand value slots]).
_INFIX = {
    "pg_operator_comparison": ("COMPARISON", ["NUM1", "NUM2"]),
    "pg_operator_and_or": ("CHECK", ["OPERAND1", "OPERAND2"]),
    "pg_operator_math": ("MATH", ["NUM1", "NUM2"]),
}

# Statement-slot labels. The default body is unlabeled; the second branch of an
# if/else is the only one that needs a word so "then" and "else" don't blur.
_STMT_LABEL = {"SUBSTACK2": "else"}


def _name(t):
    return _NAMES.get(t, t)


def _tidy(v):
    return _ENUM.get(v, v)


def _field(block, name):
    for c in block:
        if c.tag == "field" and c.attrib.get("name") == name:
            return (c.text or "").strip()
    return ""


def _value(block, slot_name):
    """Render one named <value> slot of `block` inline (literal or reporter)."""
    for v in block.findall("value"):
        if v.attrib.get("name") == slot_name:
            return _value_str(v)
    return ""


def _value_str(value_elem):
    """Render a <value> element: a shadow literal, or a nested reporter block."""
    for c in value_elem:
        if c.tag == "block":
            return _expr(c)                       # nested reporter -> recurse
        if c.tag == "shadow":
            f = c.find("field")
            return (f.text or "").strip() if f is not None else ""
    return ""


def _expr(block):
    """Render a reporter block as an inline expression."""
    t = block.attrib.get("type", "")
    if t in _INFIX:                                # A < B , A and B , A + B
        field, slots = _INFIX[t]
        op = _tidy(_field(block, field))
        return "(" + f" {op} ".join(_value(block, s) for s in slots) + ")"
    if t == "pg_operator_not":                     # not X
        return f"(not {_value(block, 'OPERAND')})"
    if t == "pg_operator_range":                   # A < x < B
        return (f"({_value(block, 'NUM1')} {_field(block, 'COMPARISON1')} "
                f"{_value(block, 'NUM2')} {_field(block, 'COMPARISON2')} "
                f"{_value(block, 'NUM3')})")
    # Generic reporter: name + its own fields + its value slots (recursed). This
    # branch is what keeps any operator/sensor from silently dropping its inputs.
    fields = [_tidy(_field(block, c.attrib["name"]))
              for c in block if c.tag == "field" and c.attrib.get("name")]
    vals = [f"{v.attrib.get('name', '').lower()} {_value_str(v)}"
            for v in block.findall("value") if _value_str(v)]
    tail = " ".join(p for p in fields + vals if p)
    return _name(t) + (f" {tail}" if tail else "")


def _line(block):
    """The one-line label for a stackable block: name + fields + value literals.
    Mutator fields (Blockly plumbing like `anddontwait_mutator`) are hidden."""
    fields = [_tidy(_field(block, c.attrib["name"]))
              for c in block
              if c.tag == "field" and c.attrib.get("name")
              and not c.attrib["name"].endswith("_mutator")
              and (c.text or "").strip()]
    vals = []
    for v in block.findall("value"):
        slot = v.attrib.get("name", "")
        txt = _value_str(v)
        if txt:
            # A CONDITION reads as itself; other slots keep their name for context.
            vals.append(txt if slot == "CONDITION" else f"{slot.lower()} {txt}")
    tail = ", ".join(p for p in [", ".join(fields)] + vals if p)
    return f"{_name(block.attrib.get('type', ''))}" + (f" {tail}" if tail else "")


def _strip_ns(elem):
    if "}" in elem.tag:
        elem.tag = elem.tag.split("}", 1)[1]
    for child in elem:
        _strip_ns(child)


def humanize_workspace(xml_string):
    """Parse a Blockly workspace XML string into a list of readable lines, one
    per stackable block, indented to show loop/if nesting. Returns [] for empty
    or unparseable input (never raises), so callers can treat it as best-effort."""
    if not xml_string:
        return []
    try:
        root = ET.fromstring(xml_string)
    except ET.ParseError:
        return []
    _strip_ns(root)

    out = []

    def walk(block, depth):
        out.append("  " * depth + _line(block))
        for child in block:
            if child.tag == "statement":
                label = _STMT_LABEL.get(child.attrib.get("name"))
                if label:
                    out.append("  " * depth + label + ":")
                for nb in child.findall("block"):
                    walk(nb, depth + 1)
            elif child.tag == "next":
                for nb in child.findall("block"):
                    walk(nb, depth)          # next is sequential: same depth

    for block in root:
        if block.tag == "block":
            walk(block, 0)
    return out


def humanize_text(xml_string):
    """Convenience: the readable listing as a single newline-joined string, or ""
    when there's nothing to show."""
    return "\n".join(humanize_workspace(xml_string))


if __name__ == "__main__":
    # ponytail: one runnable self-check so the recursion + infix can't silently
    # rot. Covers a literal number, an if/else, and a deeply nested condition.
    demo = (
        '<xml>'
        '<block type="pg_events_when_started"><next>'
        '  <block type="pg_drivetrain_drive_for">'
        '    <field name="DIRECTION">fwd</field><field name="UNITS">mm</field>'
        '    <field name="anddontwait_mutator">false</field>'
        '    <value name="AMOUNT"><shadow type="math_number"><field name="NUM">200</field></shadow></value>'
        '  <next>'
        '    <block type="pg_control_if_then_else">'
        '      <value name="CONDITION"><block type="pg_operator_not"><value name="OPERAND">'
        '        <block type="pg_operator_and_or"><field name="CHECK">and</field>'
        '          <value name="OPERAND1"><block type="pg_operator_comparison"><field name="COMPARISON">&lt;</field>'
        '            <value name="NUM1"><block type="pg_sensing_distance_distance"><field name="DISTANCE">frontdistance</field></block></value>'
        '            <value name="NUM2"><shadow type="math_number"><field name="NUM">200</field></shadow></value></block></value>'
        '          <value name="OPERAND2"><block type="pg_sensing_optical_near_object"><field name="OPTICAL">fronteye</field></block></value>'
        '        </block></value></block></value>'
        '      <statement name="SUBSTACK"><block type="pg_drivetrain_drive"><field name="DIRECTION">fwd</field></block></statement>'
        '      <statement name="SUBSTACK2"><block type="pg_drivetrain_stop_driving"/></statement>'
        '    </block></next></block>'
        '</next></block></xml>'
    )
    lines = humanize_workspace(demo)
    print("\n".join(lines))
    assert any("200" in ln for ln in lines), "value-slot number was dropped"
    assert any("else:" == ln.strip() for ln in lines), "if/else branch not labeled"
    assert any("not (" in ln and "and" in ln and "< 200" in ln for ln in lines), \
        "nested condition not rendered"
    print("\nself-check OK")
