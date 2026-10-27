"""Storage and memory contracts for floats and fixed scalar arrays."""

import math

import pytest

from tc_emulator.types import check_value, default_value


def test_real32_rounding_and_lreal64_storage():
    assert check_value("REAL", 16777217) == 16777216.0
    assert check_value("LREAL", 16777217) == 16777217.0
    assert check_value("REAL", 0.1) == 0.10000000149011612
    assert check_value("LREAL", 0.1) == 0.1
    assert default_value("REAL") == 0.0
    assert math.copysign(1, check_value("REAL", -0.0)) == -1


@pytest.mark.parametrize("sign", [-1, 1])
@pytest.mark.parametrize("offset", [-1, 0, 1])
def test_integer_to_real_rounds_exact_value_once(sign, offset):
    midpoint = 2**60 + 2**36
    expected = 2**60 + (2**37 if offset > 0 else 0)
    assert check_value("REAL", sign * (midpoint + offset)) == sign * expected


@pytest.mark.parametrize("kind", ["REAL", "LREAL"])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_storage_rejected(kind, value):
    with pytest.raises(ValueError):
        check_value(kind, value)


@pytest.mark.parametrize("kind", ["REAL", "LREAL"])
def test_float_storage_rejects_bool_and_text(kind):
    with pytest.raises(TypeError):
        check_value(kind, True)
    with pytest.raises(TypeError):
        check_value(kind, "1.5")


def test_real_overflow_and_subnormals():
    with pytest.raises(ValueError):
        check_value("REAL", 1e39)
    assert check_value("REAL", 1.401298464324817e-45) == 1.401298464324817e-45
    assert check_value("REAL", 1e-50) == 0.0


def test_array_descriptor_shape_initialization_and_copies():
    from tc_emulator.types import ArrayType, array_initial_value

    kind = ArrayType(((-1, 0), (3, 4)), "REAL")
    assert kind.shape == (2, 2)
    assert kind.size == 4
    values = [[1, 2], [3, 16777217]]
    result = check_value(kind, values)
    assert result == ((1.0, 2.0), (3.0, 16777216.0))
    values[0][0] = 90
    assert result[0][0] == 1.0
    assert array_initial_value(kind, [10, 20, 30]) == ((10.0, 20.0), (30.0, 0.0))
    with pytest.raises(ValueError):
        array_initial_value(kind, [1, 2, 3, 4, 5])
    assert default_value(kind) == ((0.0, 0.0), (0.0, 0.0))


@pytest.mark.parametrize(
    "bounds",
    [
        (),
        ((2, 1),),
        ((True, 3),),
        ((-2147483649, 0),),
        ((0, 2147483648),),
        ((0, 1000000),),
        ((0, 0),) * 9,
    ],
)
def test_invalid_array_bounds_rejected(bounds):
    from tc_emulator.types import ArrayType

    with pytest.raises((TypeError, ValueError)):
        ArrayType(bounds, "INT")


@pytest.mark.parametrize("values", [[1, 2], [[1, 2]], [[1, 2], [3]], [[1, 2], [3, True]], "1234"])
def test_array_requires_exact_shape_and_valid_elements(values):
    from tc_emulator.types import ArrayType

    with pytest.raises((TypeError, ValueError)):
        check_value(ArrayType(((1, 2), (1, 2)), "INT"), values)


def test_whole_array_write_preserves_element_alias_and_is_atomic():
    from tc_emulator import ArgumentError, Runtime
    from tc_emulator.types import ArrayType

    rt = Runtime.from_source("FUNCTION F:INT END_FUNCTION")
    cell = rt.cell(ArrayType(((-1, 0), (3, 4)), "INT"), [[1, 2], [3, 4]])
    alias = cell.element(0, 3)
    cell.value = [[10, 20], [30, 40]]
    assert alias.value == 30
    alias.value = 35
    assert cell.value == ((10, 20), (35, 40))
    with pytest.raises(ArgumentError):
        cell.value = [[99, 20], [30, 40000]]
    assert cell.value == ((10, 20), (35, 40))
    for indices in [(-2, 3), (0, 5), (True, 3), (0,), (0, 3, 1)]:
        with pytest.raises(ArgumentError):
            cell.element(*indices)
