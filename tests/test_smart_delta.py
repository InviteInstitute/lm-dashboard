"""The smart-delta engine's live path: workspace XML -> token-efficient
[Active]/[Orphaned] prompt for the playground panel."""
from app.smart_delta_engine import generate_llm_prompt_from_project


def _project(workspace_xml):
    import json
    return json.dumps({"workspace": workspace_xml})


def test_none_and_empty_return_none():
    assert generate_llm_prompt_from_project(None) is None
    assert generate_llm_prompt_from_project(_project("")) is None


def test_hat_block_is_active():
    xml = '<xml><block type="events_whenStarted" id="a"></block></xml>'
    out = generate_llm_prompt_from_project(_project(xml))
    assert "[Active]" in out and "[Orphaned]" in out
    # the hat block (event handler) is runnable -> appears under Active
    active = out.split("[Orphaned]")[0]
    assert "whenStarted" in active


def test_non_hat_top_level_block_is_orphaned():
    xml = '<xml><block type="motor_spin" id="x"></block></xml>'
    out = generate_llm_prompt_from_project(_project(xml))
    orphaned = out.split("[Orphaned]")[1]
    assert "motor_spin" in orphaned or "spin" in orphaned


def test_nested_child_renders_indented_under_parent():
    xml = ('<xml><block type="events_whenStarted" id="a">'
           '<next><block type="motor_spin" id="b"></block></next></block></xml>')
    out = generate_llm_prompt_from_project(_project(xml))
    # child appears at a deeper indent than its parent
    lines = [ln for ln in out.split("\n") if ln.strip()]
    parent = next(ln for ln in lines if "whenStarted" in ln)
    child = next(ln for ln in lines if "spin" in ln)
    indent = lambda s: len(s) - len(s.lstrip(" "))
    assert indent(child) > indent(parent)
