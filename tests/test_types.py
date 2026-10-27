"""Checked PLC scalar storage and intermediate arithmetic."""

import pytest

from tc_emulator.types import check_value, checked_integer, default_value, trunc_div


@pytest.mark.parametrize(
    ("type_name", "low", "high"),
    [
        ("INT", -32768, 32767),
        ("UINT", 0, 65535),
        ("DINT", -2147483648, 2147483647),
        ("UDINT", 0, 4294967295),
    ],
)
def test_scalar_storage_ranges(type_name, low, high):
    assert check_value(type_name, low) == low
    assert check_value(type_name, high) == high
    for value in (low - 1, high + 1):
        with pytest.raises(ValueError):
            check_value(type_name, value)


@pytest.mark.parametrize(
    ("type_name", "value"),
    [("BOOL", 1), ("BOOL", 0), ("INT", True), ("UINT", False), ("DINT", 1.0), ("UDINT", "1")],
)
def test_python_values_do_not_coerce_to_plc_types(type_name, value):
    with pytest.raises(TypeError):
        check_value(type_name, value)


def test_defaults_and_unknown_types():
    assert default_value("BOOL") is False
    assert check_value("BOOL", True) is True
    assert default_value("INT") == 0
    for operation in (default_value, lambda name: check_value(name, 0)):
        with pytest.raises(ValueError):
            operation("STRING")


def test_signed64_intermediate_bounds():
    assert checked_integer(-(2**63)) == -(2**63)
    assert checked_integer(2**63 - 1) == 2**63 - 1
    for value in (-(2**63) - 1, 2**63):
        with pytest.raises(ValueError):
            checked_integer(value)
    with pytest.raises(TypeError):
        checked_integer(True)


@pytest.mark.parametrize(
    ("left", "right", "expected"),
    [
        (-7, 3, -2),
        (7, -3, -2),
        (-7, -3, 2),
        (7, 3, 2),
        (9223372036854775807, 3, 3074457345618258602),
    ],
)
def test_division_truncates_without_float_rounding(left, right, expected):
    assert trunc_div(left, right) == expected


def test_division_by_zero():
    with pytest.raises(ZeroDivisionError):
        trunc_div(1, 0)
