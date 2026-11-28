"""
Goal evidence for the student sheet, shaped from the goal_strategy engine's
per-run profiles (Castle Crashers only).

For each profiled run: every goal with the rung its indicators reached and their
uncertainty flags, the rung-change timeline, the sensor-test battery, the
rolled-up claim per goal and the provisional execution rubric. This is evidence
with explicit abstentions, not a score. Best-effort: a malformed row drops out.
"""

import functools

from app import db

# Castle Crashers is the only playground goal_strategy profiles.
_GOAL_PLAYGROUND = "castle_crashers"
# The ladders of the two rollup goals goal_strategy DERIVES from indicator rungs
# (no battery channel by design), weaker -> stronger, and which indicator each
# basis key was read from. They mirror goal_strategy/rollup_online.py; "unknown"
# is a no-reading, not a rung.
_DERIVED_CLAIM_RUNGS = {
    "engage_plow": ["not_pursued", "approached_not_armed", "armed_not_attached", "attached"],
    "playground_engagement": ["not_engaged", "engaged"],
}
_DERIVED_BASIS_INDICATOR = {
    "magnet": "magnet_activation_intent",
    "approach": "plow_approach_intent",
    "proximity": "plow_proximity_execution",
    "moved": "robot_moved",
}


@functools.cache
def _goal_cards():
    """The static ladders and labels the goal UI draws against, read once from
    goal_strategy's playground cards: the band rungs of each battery-banded
    rollup goal (weaker -> stronger), the top level of each rubric dimension, and
    each battery scenario's family + description. Card-driven, so a re-tuned card
    upstream re-draws here with no dashboard change."""
    from goal_strategy.battery_rollup import load_rollup_card
    from goal_strategy.rubric_combiner import load_claims
    from goal_strategy.testcases import load_scenarios

    rollup = load_rollup_card(_GOAL_PLAYGROUND)
    claims = load_claims(_GOAL_PLAYGROUND)
    return {
        # the card lists rungs strongest-first (a descending min cut)
        "bands": {
            g: [r["band"] for r in reversed(spec.get("rungs") or [])]
            for g, spec in (rollup.get("goals") or {}).items()
        },
        "rubric_max": {
            d: max((int(lv) for lv in (spec.get("levels") or {})), default=0)
            for d, spec in (claims.get("dimensions") or {}).items()
        },
        "scenarios": {
            c["scenario_id"]: {"family": c.get("family"), "description": c.get("description")}
            for c in load_scenarios(_GOAL_PLAYGROUND)
        },
    }


def _shape_rollup(ru):
    """The purpose-1 rolled-up claim per goal, each with the ladder it sits on.
    Battery-banded goals carry their band + certainty + how many tests were valid;
    derived goals carry the claim and the indicator rungs it was read from."""
    if not isinstance(ru, dict):
        return None
    cards = _goal_cards()
    goals = []
    for goal, e in (ru.get("goals") or {}).items():
        if e.get("source") == "battery":
            label = e.get("label") or ""
            goals.append(
                {
                    "goal": goal,
                    "source": "battery",
                    "rung": e.get("band"),
                    "rungs": cards["bands"].get(goal, []),
                    # "U/<reason>": every contributing test abstained, so no band
                    "abstain_reason": label.split("/", 1)[1]
                    if e.get("band") is None and "/" in label
                    else None,
                    "score": e.get("score"),
                    "certainty": e.get("certainty"),
                    "certainty_reasons": e.get("certainty_reasons") or [],
                    "n_valid": e.get("n_valid"),
                    "n_abstained": e.get("n_abstained"),
                    "flags": e.get("flags") or [],
                    "debris": e.get("debris"),
                }
            )
        else:
            claim = e.get("claim")
            goals.append(
                {
                    "goal": goal,
                    "source": e.get("source") or "profile_derived",
                    "rung": None if claim == "unknown" else claim,
                    "rungs": _DERIVED_CLAIM_RUNGS.get(goal, []),
                    "abstain_reason": "no indicator reading" if claim == "unknown" else None,
                    # {indicator name: rung} the claim was read from
                    "basis": {
                        _DERIVED_BASIS_INDICATOR.get(k, k): v
                        for k, v in e.items()
                        if k not in ("claim", "source")
                    },
                }
            )
    return {"provisional": bool(ru.get("provisional")), "goals": goals}


def _shape_rubric(rb):
    """The PROVISIONAL purpose-2 rubric: one entry per execution dimension with
    the level reached on a 0..max ladder, or the reason it is undetermined."""
    if not isinstance(rb, dict):
        return None
    top = _goal_cards()["rubric_max"]
    dims = []
    for dim, d in (rb.get("dimensions") or {}).items():
        level = str(d.get("level") or "")
        undetermined = not level.isdigit()
        dims.append(
            {
                "dimension": dim,
                "level": None if undetermined else int(level),
                "max_level": top.get(dim, 0),
                "u_reason": (d.get("u_reason") or level.partition("/")[2] or "undetermined")
                if undetermined
                else None,
                "ceiling": d.get("ceiling"),
                "borderline": bool(d.get("borderline")),
                "evidence": [f.get("evidence") for f in d.get("fired") or [] if f.get("evidence")],
                "negatives": d.get("negatives") or [],
            }
        )
    return {
        "provisional": rb.get("provisional", True),
        "status": rb.get("status"),
        "dimensions": dims,
    }


# The engine's fields the sheet shows as they are, per indicator and per run.
_INDICATOR_KEYS = (
    "name",
    "channel",
    "rung",
    "direction",
    "absent_label",
    "value",
    "abstained",
    "abstain_reason",
)
_SUMMARY_KEYS = (
    "boundary_exceeded",
    "boundary_exit_step",
    "boundary_exit_overridden",
    "outcome_available",
    "fidelity_verdict",
    "sim_final_off_island",
    "gps_final_off_island",
    "off_island_agreement",
    "gps_final_error_mm",
    "gps_final_error_reason",
    "gps_to_trajectory_mm",
    "orphan_block_count",
    "fabricated_motion",
    "edge_zone_traversed",
)


def goal_runs(student_id, since=None):
    """One entry per profiled run of this student since `since` (a board reset),
    oldest first. Each run's index joins it to the edit-distance runs."""
    runs = []
    for p in db.list_goal_profiles(student_id, since=since):
        prof = p.get("profile") or {}
        goals = []
        for g in prof.get("goals", []):
            indicators = [
                {
                    **{k: ind.get(k) for k in _INDICATOR_KEYS},
                    "role": role,
                    "rung_labels": ind.get("rung_labels") or [],
                    "flags": ind.get("flags") or [],
                }
                for role, inds in (
                    ("intent", g.get("intent") or []),
                    ("attainment", g.get("attainment") or []),
                )
                for ind in inds
            ]
            goals.append({"goal": g.get("goal"), "indicators": indicators})
        # Goal-progression timeline (rung transitions) and sensor-test battery are
        # top-level goal_strategy outputs; pass them through when computed (they may
        # be null if their config flag is off, or the battery may be not-eligible).
        tl = p.get("timeline") or None
        timeline = (
            {
                "events": tl.get("events") or [],
                "post_exit_events": tl.get("post_exit_events") or [],
                "boundary_exit_step": tl.get("boundary_exit_step"),
            }
            if isinstance(tl, dict)
            else None
        )
        bat = p.get("battery") or None
        battery = (
            {
                "eligible": bat.get("eligible"),
                "qualifying_blocks": bat.get("qualifying_blocks") or [],
                # each scenario tagged with its card family + description, so the
                # 19-scenario battery can be read family by family
                "scenarios": [
                    {**sc, **(_goal_cards()["scenarios"].get(sc.get("scenario_id")) or {})}
                    for sc in bat.get("scenarios") or []
                ],
                "goal_mapping": bat.get("goal_mapping") or {},
            }
            if isinstance(bat, dict)
            else None
        )
        # Run-level evidence the goals list doesn't carry: whether the robot left
        # the island (a critical failure, not a goal), whether an outcome was
        # associated, the sim-vs-GPS fidelity verdict, and the descriptive flags.
        runs.append(
            {
                "index": p.get("index"),
                "playground": p.get("playground"),
                "status": p.get("status"),
                "reason": p.get("reason"),
                "diagnostics": p.get("diagnostics") or [],
                "goals": goals,
                "timeline": timeline,
                "battery": battery,
                "rollup": _shape_rollup(p.get("rollup")),
                "rubric": _shape_rubric(p.get("rubric")),
                "summary": {k: prof.get(k) for k in _SUMMARY_KEYS},
            }
        )
    return runs
