"""The datetime contract is the riskiest part of db.py: stored as UTC-naive
'%Y-%m-%d %H:%M:%S.%f' strings whose lexical order must match chronological
order (so `ORDER BY started_at` and `resolved_at >= cutoff` work as raw SQL)."""
from datetime import datetime, timezone, timedelta

from app import db


def test_aware_roundtrip_preserves_microseconds():
    dt = datetime(2026, 6, 22, 13, 45, 30, 123456, tzinfo=timezone.utc)
    assert db.db_to_dt(db.dt_to_db(dt)) == dt


def test_dt_to_db_converts_other_zones_to_utc():
    eastern = timezone(timedelta(hours=-4))
    dt = datetime(2026, 6, 22, 9, 0, 0, tzinfo=eastern)   # 13:00 UTC
    s = db.dt_to_db(dt)
    assert s.startswith("2026-06-22 13:00:00")


def test_naive_datetime_treated_as_utc_on_read():
    out = db.db_to_dt("2026-06-22 13:45:30.000000")
    assert out.tzinfo is not None and out.hour == 13


def test_none_passes_through_both_ways():
    assert db.dt_to_db(None) is None
    assert db.db_to_dt(None) is None
    assert db.db_to_dt("") is None


def test_db_to_dt_accepts_fractionless_and_iso():
    assert db.db_to_dt("2026-06-22 13:45:30").second == 30          # no microseconds
    assert db.db_to_dt("2026-06-22T13:45:30+00:00").hour == 13      # ISO with offset
    assert db.db_to_dt("2026-06-22T13:45:30Z").hour == 13           # ISO with Z


def test_db_to_dt_returns_none_on_garbage():
    assert db.db_to_dt("not a date") is None


def test_lexical_order_matches_chronological_order():
    """The whole stored-string scheme relies on this invariant."""
    t1 = datetime(2026, 6, 22, 1, 0, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 6, 22, 1, 0, 0, 500000, tzinfo=timezone.utc)
    t3 = datetime(2026, 6, 22, 2, 0, 0, tzinfo=timezone.utc)
    s1, s2, s3 = db.dt_to_db(t1), db.dt_to_db(t2), db.dt_to_db(t3)
    assert s1 < s2 < s3


def test_db_to_dt_idempotent_on_datetime_input():
    dt = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert db.db_to_dt(dt) == dt
