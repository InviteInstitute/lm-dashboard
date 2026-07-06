from app.constants import ITERATIVE_THRESHOLDS


def test_thresholds_use_real_telemetry_playground_names():
    # These are the exact strings that appear in the runProject `playground` field.
    assert ITERATIVE_THRESHOLDS == {
        "CastleCrasherPlus": 6,
        "CoralReefRescue": 5,
        "RoverRescue": 3,
    }
