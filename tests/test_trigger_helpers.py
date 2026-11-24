"""Trigger helper functions: idle formatting."""

from app.pipeline import triggers


def test_fmt_idle_minutes_hours_days():
    assert triggers._fmt_idle(0) == "idle 0m"
    assert triggers._fmt_idle(120) == "idle 2m"
    assert triggers._fmt_idle(3 * 3600) == "idle 3h"
    assert triggers._fmt_idle(2 * 86400) == "idle 2d"
    assert triggers._fmt_idle(None) == "idle 0m"
