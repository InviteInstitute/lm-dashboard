from app.pipeline.switches import detect_switches


def test_first_event_is_never_a_switch():
    assert detect_switches(None, None, "cobra3", "FPFVDH") == []


def test_casing_flip():
    assert detect_switches("cobra3", "FPFVDH", "Cobra3", "FPFVDH") == [
        ("casing", "cobra3", "Cobra3")
    ]


def test_class_change():
    assert detect_switches("cobra3", "FPFVDH", "cobra3", "AFURRR") == [
        ("class", "FPFVDH", "AFURRR")
    ]


def test_both_fire_casing_before_class():
    assert detect_switches("cobra3", "FPFVDH", "Cobra3", "AFURRR") == [
        ("casing", "cobra3", "Cobra3"),
        ("class", "FPFVDH", "AFURRR"),
    ]


def test_same_values_no_switch():
    assert detect_switches("cobra3", "FPFVDH", "cobra3", "FPFVDH") == []


def test_different_handle_is_not_a_casing_switch():
    # different handles even ignoring case -> not a casing switch (shouldn't
    # happen inside one worker, but the guard keeps the function honest)
    assert detect_switches("cobra3", "FPFVDH", "bear2", "FPFVDH") == []


def test_empty_prior_class_is_not_a_switch():
    assert detect_switches("cobra3", "", "cobra3", "FPFVDH") == []
