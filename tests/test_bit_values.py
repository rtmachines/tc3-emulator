"""Checked widths, operations, conversion and bit-location value contracts."""

from importlib import import_module
from importlib.util import find_spec

import pytest

from tc_emulator import standard_functions as sf
from tc_emulator.syntax import Argument, Literal, Location
from tc_emulator.types import (
    AliasType,
    ArrayType,
    EnumType,
    StructType,
    check_value,
    default_value,
    numeric_type,
)


def bits():
    assert find_spec("tc_emulator.bitwise") is not None, "Shared bit helpers are required"
    return import_module("tc_emulator.bitwise")


@pytest.mark.parametrize("kind,high", [("BYTE", 255), ("WORD", 65535), ("DWORD", 4294967295)])
def test_bitstring_storage_is_checked_and_keeps_numeric_arithmetic(kind, high):
    assert check_value(kind, high) == high
    assert default_value(AliasType("Bits", kind)) == 0
    assert numeric_type(kind, "INT") == "INTEGER"
    for value in (-1, high + 1):
        with pytest.raises(ValueError):
            check_value(kind, value)
    for value in (True, 1.0):
        with pytest.raises(TypeError):
            check_value(kind, value)


@pytest.mark.parametrize("kind", ["BYTE", "WORD", "DWORD"])
def test_enum_bases_reject_all_bitstrings(kind):
    with pytest.raises(ValueError):
        EnumType("Mode", (("OFF", 0),), kind)


@pytest.mark.parametrize(
    "kind,width",
    [
        ("BYTE", 8),
        ("WORD", 16),
        ("DWORD", 32),
        ("INT", 16),
        ("UINT", 16),
        ("DINT", 32),
        ("UDINT", 32),
    ],
)
def test_bit_width_resolves_scalar_aliases(kind, width):
    assert bits().bit_width(kind) == width
    assert bits().bit_width(AliasType("A", AliasType("B", kind))) == width


@pytest.mark.parametrize(
    "kind",
    [
        "BOOL",
        "TIME",
        "INTEGER",
        "REAL",
        "LREAL",
        EnumType("Mode", (("OFF", 0),)),
        ArrayType(((0, 1),), "BYTE"),
        StructType("Empty", ()),
    ],
)
def test_bit_width_rejects_non_storage_integer_types(kind):
    with pytest.raises((ValueError, TypeError)):
        bits().bit_width(kind)


@pytest.mark.parametrize(
    "op,left,right,want",
    [
        ("NOT", "BOOL", None, "BOOL"),
        ("AND", "BOOL", "BOOL", "BOOL"),
        ("OR", "BYTE", "WORD", "WORD"),
        ("XOR", "DWORD", "BYTE", "DWORD"),
        ("AND", "INTEGER", "BYTE", "BYTE"),
        ("OR", "WORD", "INTEGER", "WORD"),
        ("XOR", "INTEGER", "INTEGER", "DWORD"),
        ("NOT", "INTEGER", None, "DWORD"),
        ("NOT", AliasType("A", "BYTE"), None, "BYTE"),
    ],
)
def test_bitwise_result_uses_boolean_or_widest_unsigned_width(op, left, right, want):
    assert bits().bitwise_result_type(op, left, right) == want


@pytest.mark.parametrize(
    "left,right",
    [
        ("BOOL", "BYTE"),
        ("WORD", "BOOL"),
        ("INT", "BYTE"),
        ("WORD", "UINT"),
        ("DINT", "UDINT"),
        ("TIME", "INTEGER"),
        ("REAL", "REAL"),
    ],
)
def test_bitwise_result_requires_bitstrings_or_untyped_integers(left, right):
    with pytest.raises(TypeError):
        bits().bitwise_result_type("AND", left, right)


@pytest.mark.parametrize(
    "op,left,right,kind,want",
    [
        ("NOT", False, None, "BOOL", True),
        ("AND", True, False, "BOOL", False),
        ("OR", True, False, "BOOL", True),
        ("XOR", True, True, "BOOL", False),
        ("NOT", 0, None, "BYTE", 255),
        ("NOT", 240, None, "BYTE", 15),
        ("NOT", 0, None, "WORD", 65535),
        ("NOT", 0, None, "DWORD", 4294967295),
        ("AND", 240, 170, "BYTE", 160),
        ("OR", 240, 170, "WORD", 250),
        ("XOR", 240, 170, "DWORD", 90),
    ],
)
def test_bitwise_values_preserve_fixed_width_or_boolean(op, left, right, kind, want):
    result = bits().bitwise_value(op, left, right, AliasType("Bits", kind))
    assert result == want
    assert type(result) is type(want)


@pytest.mark.parametrize("value", [-1, 256, 2**100, True, 1.0])
def test_bitwise_values_check_operands_before_operation(value):
    with pytest.raises((ValueError, TypeError)):
        bits().bitwise_value("AND", value, 0, "BYTE")
    with pytest.raises((ValueError, TypeError)):
        bits().bitwise_value("AND", 0, value, "BYTE")


@pytest.mark.parametrize("op", ["NAND", "", "ADD"])
def test_bitwise_rejects_unknown_operations(op):
    with pytest.raises(ValueError):
        bits().bitwise_result_type(op, "BYTE", "BYTE")
    with pytest.raises(ValueError):
        bits().bitwise_value(op, 1, 1, "BYTE")


@pytest.mark.parametrize(
    "op,value,count,kind,want",
    [
        ("SHL", 129, 1, "BYTE", 2),
        ("SHR", 129, 1, "BYTE", 64),
        ("ROL", 129, 1, "BYTE", 3),
        ("ROR", 129, 1, "BYTE", 192),
        ("SHL", 65535, 16, "WORD", 0),
        ("SHR", 4294967295, 32, "DWORD", 0),
        ("ROL", 32769, 16, "WORD", 32769),
        ("ROR", 2147483649, 33, "DWORD", 3221225472),
        ("SHL", 129, 0, "BYTE", 129),
        ("SHR", 129, 0, "BYTE", 129),
        ("SHL", 1, 2**1000, "BYTE", 0),
        ("SHR", 255, 2**1000, "BYTE", 0),
        ("ROL", 129, 2**1000 + 1, "BYTE", 3),
        ("ROR", 129, 2**1000 + 1, "BYTE", 192),
    ],
)
def test_shift_and_rotate_bound_counts_without_large_intermediates(op, value, count, kind, want):
    assert bits().shift_value(op, value, count, AliasType("Bits", kind)) == want


@pytest.mark.parametrize(
    "value,count,kind",
    [
        (256, 0, "BYTE"),
        (-1, 0, "WORD"),
        (1, -1, "BYTE"),
        (1, True, "BYTE"),
        (1, 1.0, "BYTE"),
        (True, 1, "BYTE"),
        (1, 0, "INT"),
        (1, 0, "INTEGER"),
    ],
)
def test_shift_rejects_invalid_input_count_and_width(value, count, kind):
    with pytest.raises((ValueError, TypeError)):
        bits().shift_value("SHL", value, count, kind)


@pytest.mark.parametrize(
    "kind,value,index,bit,want",
    [
        ("BYTE", 0, 7, True, 128),
        ("BYTE", 255, 0, False, 254),
        ("WORD", 1, 15, True, 32769),
        ("DWORD", 1, 31, True, 2147483649),
        ("INT", 1, 15, True, -32767),
        ("INT", -1, 15, False, 32767),
        ("DINT", 0, 31, True, -2147483648),
        ("DINT", -2147483648, 31, False, 0),
        ("UINT", 0, 15, True, 32768),
        ("UDINT", 0, 31, True, 2147483648),
    ],
)
def test_bit_write_reconstructs_signed_values_and_preserves_other_bits(
    kind, value, index, bit, want
):
    alias = AliasType("Bits", kind)
    assert bits().write_bit(value, alias, index, bit) == want
    assert bits().read_bit(want, alias, index) is bit


@pytest.mark.parametrize(
    "kind,value,index,want",
    [("INT", -1, 0, True), ("DINT", -2147483648, 0, False), ("BYTE", 128, 7, True)],
)
def test_bit_reads_signed_twos_complement(kind, value, index, want):
    assert bits().read_bit(value, kind, index) is want


@pytest.mark.parametrize(
    "value,kind,index",
    [
        (0, "BYTE", -1),
        (0, "BYTE", 8),
        (0, "WORD", True),
        (0, "WORD", 1.0),
        (256, "BYTE", 0),
        (-32769, "INT", 0),
        (0, "BOOL", 0),
        (0, "TIME", 0),
    ],
)
def test_bit_access_validates_value_and_literal_index(value, kind, index):
    with pytest.raises((ValueError, TypeError)):
        bits().read_bit(value, kind, index)
    with pytest.raises((ValueError, TypeError)):
        bits().write_bit(value, kind, index, True)


@pytest.mark.parametrize("value", [0, 1, "TRUE", None])
def test_bit_write_requires_actual_bool(value):
    with pytest.raises(TypeError):
        bits().write_bit(0, "BYTE", 0, value)


@pytest.mark.parametrize("name", ["SHL", "SHR", "ROL", "ROR"])
def test_shift_standard_function_registration_binding_and_types(name):
    assert sf.is_standard_function(name)
    loc = Location("test", 1, 1)
    value = Argument("IN", ":=", Literal(129, loc), loc)
    count = Argument("N", ":=", Literal(1, loc), loc)
    assert sf.bind_arguments(name, (count, value)) == (value, count)
    assert sf.infer_result(name, (AliasType("A", "BYTE"), "INT")) == "BYTE"
    assert sf.infer_result(name, ("INTEGER", "UDINT")) == "DWORD"
    assert sf.evaluate(name, ((129, "BYTE"), (1, "INT"))) == (
        {"SHL": 2, "SHR": 64, "ROL": 3, "ROR": 192}[name],
        "BYTE",
    )


@pytest.mark.parametrize(
    "input_type,count_type",
    [("BOOL", "INT"), ("INT", "INT"), ("DWORD", "BOOL"), ("BYTE", "REAL"), ("WORD", "TIME")],
)
def test_shift_standard_function_rejects_wrong_categories(input_type, count_type):
    with pytest.raises(TypeError):
        sf.infer_result("SHL", (input_type, count_type))


@pytest.mark.parametrize("value,count", [(-1, 0), (2**32, 0), (1, -1), (True, 1)])
def test_shift_standard_function_rejects_values_before_evaluation(value, count):
    with pytest.raises((TypeError, ValueError)):
        sf.evaluate("SHL", ((value, "INTEGER"), (count, "INTEGER")))


SCALARS = ("BOOL", "INT", "UINT", "DINT", "UDINT", "BYTE", "WORD", "DWORD", "REAL", "LREAL", "TIME")


@pytest.mark.parametrize("source", SCALARS)
@pytest.mark.parametrize("target", SCALARS)
def test_all_scalar_conversion_pairs_include_byte_and_dword(source, target):
    value = True if source == "BOOL" else 1.0 if source in {"REAL", "LREAL"} else 1
    want = True if target == "BOOL" else 1.0 if target in {"REAL", "LREAL"} else 1
    assert sf.evaluate(f"{source}_TO_{target}", ((value, source),)) == (want, target)


@pytest.mark.parametrize(
    "name,value,source,want,target",
    [
        ("TO_BYTE", 254.5, "LREAL", 254, "BYTE"),
        ("TO_DWORD", 4294967295, "UDINT", 4294967295, "DWORD"),
        ("DWORD_TO_LREAL", 4294967295, "DWORD", 4294967295.0, "LREAL"),
    ],
)
def test_bitstring_conversions_keep_checked_rounding_and_full_unsigned_range(
    name, value, source, want, target
):
    assert sf.evaluate(name, ((value, source),)) == (want, target)


@pytest.mark.parametrize(
    "name,value,source",
    [
        ("TO_BYTE", 255.5, "LREAL"),
        ("TO_DWORD", -1, "INTEGER"),
        ("BYTE_TO_DWORD", 256, "INTEGER"),
        ("DWORD_TO_BYTE", 4294967295, "DWORD"),
    ],
)
def test_bitstring_conversions_reject_source_or_destination_overflow(name, value, source):
    with pytest.raises((TypeError, ValueError)):
        sf.evaluate(name, ((value, source),))
