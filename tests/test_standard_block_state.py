"""Standard-block traces use explicit calls and ordinary mutable output storage."""

from types import MappingProxyType

import pytest

from tc_emulator.standard_blocks import (
    STANDARD_BLOCK_NAMES,
    StandardBlockState,
    standard_block_definitions,
)


def state(kind):
    return StandardBlockState(kind)


def counter_values(kind, **changes):
    values = {
        "CTU": {"CU": False, "RESET": False, "PV": 3, "Q": False, "CV": 0},
        "CTD": {"CD": False, "LOAD": False, "PV": 3, "Q": False, "CV": 0},
        "CTUD": {
            "CU": False,
            "CD": False,
            "RESET": False,
            "LOAD": False,
            "PV": 3,
            "QU": False,
            "QD": False,
            "CV": 0,
        },
    }[kind]
    values.update(changes)
    return values


@pytest.mark.parametrize(
    ("kind", "samples", "expected"),
    [
        (
            "R_TRIG",
            [False, False, True, True, False, True],
            [False, False, True, False, False, True],
        ),
        ("R_TRIG", [True, True, False], [True, False, False]),
        (
            "F_TRIG",
            [False, False, True, True, False, False],
            [False, False, False, False, True, False],
        ),
        ("F_TRIG", [True, False, True, False], [False, True, False, True]),
    ],
)
def test_trigger_startup_and_one_call_pulses(kind, samples, expected):
    block = state(kind)
    assert [block.update({"CLK": clk, "Q": False})["Q"] for clk in samples] == expected


def test_edge_history_is_separate_for_each_instance():
    first, second = state("F_TRIG"), state("F_TRIG")
    first.update({"CLK": True, "Q": False})
    assert second.update({"CLK": False, "Q": False}) == {"Q": False}
    assert first.update({"CLK": False, "Q": False}) == {"Q": True}


@pytest.mark.parametrize(
    ("kind", "set_name", "reset_name", "set_input", "reset_input", "old_q", "expected"),
    [
        ("SR", "SET1", "RESET", False, False, False, False),
        ("SR", "SET1", "RESET", False, False, True, True),
        ("SR", "SET1", "RESET", False, True, True, False),
        ("SR", "SET1", "RESET", True, False, False, True),
        ("SR", "SET1", "RESET", True, True, False, True),
        ("SR", "SET1", "RESET", True, True, True, True),
        ("RS", "SET", "RESET1", False, False, False, False),
        ("RS", "SET", "RESET1", False, False, True, True),
        ("RS", "SET", "RESET1", False, True, True, False),
        ("RS", "SET", "RESET1", True, False, False, True),
        ("RS", "SET", "RESET1", True, True, False, False),
        ("RS", "SET", "RESET1", True, True, True, False),
    ],
)
def test_bistable_level_sensitive_truth_table(
    kind, set_name, reset_name, set_input, reset_input, old_q, expected
):
    assert state(kind).update({set_name: set_input, reset_name: reset_input, "Q1": old_q}) == {
        "Q1": expected
    }


@pytest.mark.parametrize(
    ("kind", "set_name", "reset_name"), [("SR", "SET1", "RESET"), ("RS", "SET", "RESET1")]
)
def test_bistable_uses_current_q1_and_reapplies_held_levels(kind, set_name, reset_name):
    block = state(kind)
    assert block.update({set_name: True, reset_name: False, "Q1": False}) == {"Q1": True}
    # An ST assignment changed the normal output cell after the previous call.
    assert block.update({set_name: False, reset_name: False, "Q1": False}) == {"Q1": False}
    assert block.update({set_name: False, reset_name: False, "Q1": True}) == {"Q1": True}
    assert block.update({set_name: True, reset_name: False, "Q1": False}) == {"Q1": True}
    assert block.update({set_name: True, reset_name: False, "Q1": False}) == {"Q1": True}
    assert block.update({set_name: False, reset_name: True, "Q1": True}) == {"Q1": False}
    assert block.update({set_name: False, reset_name: True, "Q1": True}) == {"Q1": False}


def test_ctu_counts_rising_edges_beyond_pv_and_recomputes_q():
    block = state("CTU")
    values = counter_values("CTU", PV=1)
    for cu, expected in [
        (True, {"Q": True, "CV": 1}),
        (True, {"Q": True, "CV": 1}),
        (False, {"Q": True, "CV": 1}),
        (True, {"Q": True, "CV": 2}),
    ]:
        values["CU"] = cu
        result = block.update(values)
        assert result == expected
        values.update(result)
    values["PV"] = 3
    assert block.update(values) == {"Q": False, "CV": 2}


@pytest.mark.parametrize(("start", "expected"), [(65534, 65535), (65535, 65535)])
def test_ctu_saturates_at_word_maximum(start, expected):
    assert state("CTU").update(counter_values("CTU", CU=True, CV=start, PV=1)) == {
        "Q": True,
        "CV": expected,
    }


def test_ctu_reset_wins_counting_and_samples_the_edge():
    block = state("CTU")
    values = counter_values("CTU", CU=True, RESET=True, CV=8)
    assert block.update(values) == {"Q": False, "CV": 0}
    values.update(RESET=False, CV=0)
    assert block.update(values) == {"Q": False, "CV": 0}
    values["CU"] = False
    block.update(values)
    values["CU"] = True
    assert block.update(values) == {"Q": False, "CV": 1}


def test_ctd_load_wins_counting_and_samples_the_edge():
    block = state("CTD")
    values = counter_values("CTD", CD=True, LOAD=True)
    assert block.update(values) == {"Q": False, "CV": 3}
    values.update(LOAD=False, CV=3)
    assert block.update(values) == {"Q": False, "CV": 3}
    values["CD"] = False
    block.update(values)
    values["CD"] = True
    assert block.update(values) == {"Q": False, "CV": 2}


@pytest.mark.parametrize(("start", "expected", "q"), [(2, 1, False), (1, 0, True), (0, 0, True)])
def test_ctd_decrements_with_zero_floor(start, expected, q):
    assert state("CTD").update(counter_values("CTD", CD=True, CV=start)) == {
        "Q": q,
        "CV": expected,
    }


@pytest.mark.parametrize("kind", ["CTU", "CTD", "CTUD"])
def test_counter_reads_current_cv_and_does_not_hide_previous_outputs(kind):
    block = state(kind)
    values = counter_values(kind, CV=5)
    block.update(values)
    values["CV"] = 1
    values["CU" if kind != "CTD" else "CD"] = True
    expected = {
        "CTU": {"Q": False, "CV": 2},
        "CTD": {"Q": True, "CV": 0},
        "CTUD": {"QU": False, "QD": False, "CV": 2},
    }[kind]
    assert block.update(values) == expected


@pytest.mark.parametrize("kind", ["CTU", "CTD", "CTUD"])
def test_counter_zero_preset_recalculates_flags_on_first_call(kind):
    expected = {
        "CTU": {"Q": True, "CV": 0},
        "CTD": {"Q": True, "CV": 0},
        "CTUD": {"QU": True, "QD": True, "CV": 0},
    }[kind]
    assert state(kind).update(counter_values(kind, PV=0)) == expected


def test_ctud_reset_wins_load_and_count_then_load_wins_count():
    block = state("CTUD")
    values = counter_values("CTUD", CU=True, CD=True, RESET=True, LOAD=True, CV=9)
    assert block.update(values) == {"QU": False, "QD": True, "CV": 0}
    values.update(RESET=False, CV=0)
    assert block.update(values) == {"QU": True, "QD": False, "CV": 3}
    values.update(LOAD=False, CV=3)
    assert block.update(values) == {"QU": True, "QD": False, "CV": 3}


@pytest.mark.parametrize("priority", ["RESET", "LOAD"])
@pytest.mark.parametrize(("edge", "expected"), [("CU", 4), ("CD", 2)])
def test_ctud_samples_both_edge_inputs_during_reset_or_load(priority, edge, expected):
    block = state("CTUD")
    values = counter_values("CTUD", CU=True, CD=True, **{priority: True})
    block.update(values)
    values.update({priority: False, "CV": 3})
    assert block.update(values) == {"QU": True, "QD": False, "CV": 3}
    values[edge] = False
    block.update(values)
    values[edge] = True
    assert block.update(values) == {"QU": expected >= 3, "QD": False, "CV": expected}


@pytest.mark.parametrize(
    ("cv", "qu", "qd"), [(0, False, True), (2, False, False), (65535, True, False)]
)
def test_ctud_simultaneous_rising_edges_cancel_at_every_boundary(cv, qu, qd):
    assert state("CTUD").update(counter_values("CTUD", CU=True, CD=True, CV=cv)) == {
        "QU": qu,
        "QD": qd,
        "CV": cv,
    }


@pytest.mark.parametrize(
    ("cu", "cd", "start", "cv", "qu", "qd"),
    [
        (True, False, 2, 3, True, False),
        (True, False, 3, 4, True, False),
        (True, False, 65535, 65535, True, False),
        (False, True, 2, 1, False, False),
        (False, True, 1, 0, False, True),
        (False, True, 0, 0, False, True),
    ],
)
def test_ctud_counting_and_saturation(cu, cd, start, cv, qu, qd):
    assert state("CTUD").update(counter_values("CTUD", CU=cu, CD=cd, CV=start)) == {
        "QU": qu,
        "QD": qd,
        "CV": cv,
    }


def test_update_accepts_read_only_mapping_and_returns_only_outputs():
    values = counter_values("CTUD", CU=True)
    assert state("CTUD").update(MappingProxyType(values)) == {"QU": False, "QD": False, "CV": 1}
    assert values == counter_values("CTUD", CU=True)


def test_unknown_block_kind_fails_explicitly():
    with pytest.raises(ValueError, match="Unknown standard block kind"):
        state("OTHER").update({})


def test_standard_block_interfaces_have_exact_port_names_sections_and_word_counters():
    expected = {
        "R_TRIG": [("CLK", "BOOL", "VAR_INPUT"), ("Q", "BOOL", "VAR_OUTPUT")],
        "F_TRIG": [("CLK", "BOOL", "VAR_INPUT"), ("Q", "BOOL", "VAR_OUTPUT")],
        "SR": [
            ("SET1", "BOOL", "VAR_INPUT"),
            ("RESET", "BOOL", "VAR_INPUT"),
            ("Q1", "BOOL", "VAR_OUTPUT"),
        ],
        "RS": [
            ("SET", "BOOL", "VAR_INPUT"),
            ("RESET1", "BOOL", "VAR_INPUT"),
            ("Q1", "BOOL", "VAR_OUTPUT"),
        ],
        "CTU": [
            ("CU", "BOOL", "VAR_INPUT"),
            ("RESET", "BOOL", "VAR_INPUT"),
            ("PV", "WORD", "VAR_INPUT"),
            ("Q", "BOOL", "VAR_OUTPUT"),
            ("CV", "WORD", "VAR_OUTPUT"),
        ],
        "CTD": [
            ("CD", "BOOL", "VAR_INPUT"),
            ("LOAD", "BOOL", "VAR_INPUT"),
            ("PV", "WORD", "VAR_INPUT"),
            ("Q", "BOOL", "VAR_OUTPUT"),
            ("CV", "WORD", "VAR_OUTPUT"),
        ],
        "CTUD": [
            ("CU", "BOOL", "VAR_INPUT"),
            ("CD", "BOOL", "VAR_INPUT"),
            ("RESET", "BOOL", "VAR_INPUT"),
            ("LOAD", "BOOL", "VAR_INPUT"),
            ("PV", "WORD", "VAR_INPUT"),
            ("QU", "BOOL", "VAR_OUTPUT"),
            ("QD", "BOOL", "VAR_OUTPUT"),
            ("CV", "WORD", "VAR_OUTPUT"),
        ],
    }
    definitions = standard_block_definitions()
    assert isinstance(definitions, tuple)
    assert STANDARD_BLOCK_NAMES == frozenset(expected)
    assert {
        pou.name: [(v.name, v.type_name, v.section) for v in pou.variables] for pou in definitions
    } == expected
    for pou in definitions:
        assert pou.kind == "FUNCTION_BLOCK"
        assert pou.return_type is None
        assert pou.body == ()
        assert all(var.initial is None and var.default is None for var in pou.variables)
