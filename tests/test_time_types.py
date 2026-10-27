"""TIME storage stays distinct from numeric ST storage."""

import pytest

from tc_emulator.types import (
    INTEGER_TYPES,
    NUMERIC_TYPES,
    SCALAR_TYPES,
    ArrayType,
    array_initial_value,
    check_value,
    default_value,
    numeric_type,
)


def test_time_is_a_scalar_but_not_a_numeric_or_integer_type():
    assert "TIME" in SCALAR_TYPES
    assert "TIME" not in INTEGER_TYPES
    assert "TIME" not in NUMERIC_TYPES
    with pytest.raises(ValueError, match="Numeric"):
        numeric_type("TIME", "TIME")


@pytest.mark.parametrize("value", [0, 1, 4294967295])
def test_time_storage_accepts_uint32_milliseconds(value):
    assert check_value("TIME", value) == value
    assert type(check_value("TIME", value)) is int


@pytest.mark.parametrize("value", [-1, 4294967296, 10**100])
def test_time_storage_rejects_out_of_range_values(value):
    with pytest.raises(ValueError, match="TIME range"):
        check_value("TIME", value)


@pytest.mark.parametrize("value", [False, True, 0.0, 1.5, "1", None])
def test_time_storage_rejects_values_that_are_not_python_ints(value):
    with pytest.raises(TypeError, match="TIME requires a Python int"):
        check_value("TIME", value)


def test_time_defaults_and_arrays_use_checked_millisecond_storage():
    assert default_value("TIME") == 0
    kind = ArrayType(((1, 2), (0, 1)), "time")
    assert default_value(kind) == ((0, 0), (0, 0))
    assert array_initial_value(kind, [5, 4294967295]) == ((5, 4294967295), (0, 0))
    assert check_value(kind, [[1, 2], [3, 4]]) == ((1, 2), (3, 4))
    for value in ([[0, True], [0, 0]], [[0, -1], [0, 0]]):
        with pytest.raises((TypeError, ValueError)):
            check_value(kind, value)
