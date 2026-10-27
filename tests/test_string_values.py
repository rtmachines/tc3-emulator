"""STRING storage, pure text functions and explicit conversion boundaries."""

from dataclasses import FrozenInstanceError

import pytest

from tc_emulator import standard_functions as sf
from tc_emulator import types as t
from tc_emulator.syntax import Argument, Literal, Location


def string(length=80):
    assert hasattr(t, "StringType"), "STRING capacity descriptor is required"
    return t.StringType(length)


def text_call(name, *values):
    arguments = tuple(
        (value, string(max(1, len(value)))) if isinstance(value, str) else (value, "INTEGER")
        for value in values
    )
    return sf.evaluate(name, arguments)


def test_storage_descriptor_is_frozen_and_preserves_exact_capacity():
    kind = string()
    assert str(kind) == "STRING(80)"
    assert hash(kind) == hash(string(80))
    assert t.same_type(t.AliasType("Text", string(12)), string(12))
    assert not t.same_type(string(12), string(13))
    with pytest.raises(FrozenInstanceError):
        kind.length = 3


@pytest.mark.parametrize("length", [True, False, 1.0, "3", None, 0, -1, 1_000_001])
def test_storage_rejects_invalid_capacity(length):
    with pytest.raises((TypeError, ValueError)):
        string(length)


@pytest.mark.parametrize("value,want", [("", ""), ("éÿ", "éÿ"), ("abcde", "abc"), ("a\0bc", "a")])
def test_storage_clips_latin1_and_terminates_at_nul(value, want):
    assert t.check_value(string(3), value) == want


@pytest.mark.parametrize("value", [123, b"a", None, True, "abc😀", "a\0😀"])
def test_storage_validates_entire_input_before_truncation(value):
    kind = string(1)
    with pytest.raises((TypeError, ValueError)):
        t.check_value(kind, value)


def test_storage_helpers_support_aliases_arrays_structs_and_defaults():
    kind = string(2)
    assert t.default_value(kind) == ""
    assert t.is_value_type(kind)
    assert t.resolve_type("string", {}) == string(80)
    assert t.resolve_type(kind, {}) == kind
    alias = t.AliasType("Short", kind, "long")
    assert t.default_value(alias) == "lo"
    array = t.ArrayType(((1, 2),), alias)
    assert t.resolve_type(array, {}) == array
    assert t.check_value(array, ["abc", "é"]) == ("ab", "é")
    assert t.default_value(array) == ("lo", "lo")
    assert t.array_initial_value(array, ["abcd"]) == ("ab", "lo")
    assert t.value_leaf_count(array) == 2
    structure = t.StructType("Recipe", (t.StructField("name", kind), t.StructField("tags", array)))
    value = t.check_value(structure, {"name": "Test", "tags": ["A", "BC"]})
    assert value["name"] == "Te"
    assert value["tags"] == ("A", "BC")
    assert t.default_value(structure)["name"] == ""


@pytest.mark.parametrize(
    "name,values,want",
    [
        ("LEN", ("éÿ",), 2),
        ("LEFT", ("abc", 0), ""),
        ("LEFT", ("abc", 2), "ab"),
        ("LEFT", ("abc", 9), "abc"),
        ("RIGHT", ("abc", 0), ""),
        ("RIGHT", ("abc", 2), "bc"),
        ("RIGHT", ("abc", 9), "abc"),
        ("MID", ("abcde", 2, 2), "bc"),
        ("MID", ("abc", 2, 9), ""),
        ("MID", ("abc", 0, 1), ""),
        ("CONCAT", ("é", "ÿ"), "éÿ"),
        ("FIND", ("banana", "ana"), 2),
        ("FIND", ("abc", "x"), 0),
        ("FIND", ("abc", ""), 1),
        ("INSERT", ("abc", "XY", 0), "XYabc"),
        ("INSERT", ("abc", "XY", 2), "abXYc"),
        ("INSERT", ("abc", "XY", 9), "abcXY"),
        ("DELETE", ("abcde", 2, 2), "ade"),
        ("DELETE", ("abc", 2, 9), "abc"),
        ("DELETE", ("abc", 0, 2), "abc"),
        ("REPLACE", ("abcde", "XY", 2, 2), "aXYde"),
        ("REPLACE", ("abc", "XY", 2, 9), "abcXY"),
        ("REPLACE", ("abc", "XY", 0, 2), "aXYbc"),
    ],
)
def test_text_operations_use_documented_position_profiles(name, values, want):
    result, kind = text_call(name, *values)
    assert result == want
    assert kind == ("INT" if type(want) is int else string(255))


def test_text_functions_clip_each_input_then_output():
    assert text_call("LEN", "a" * 300) == (255, "INT")
    assert text_call("RIGHT", "a" * 255 + "b", 1) == ("a", string(255))
    assert text_call("FIND", "a\0b", "b") == (0, "INT")
    assert text_call("CONCAT", "a" * 254, "bc") == ("a" * 254 + "b", string(255))


@pytest.mark.parametrize(
    "name,values",
    [
        ("LEFT", ("a", -1)),
        ("RIGHT", ("a", 32768)),
        ("MID", ("a", 1, 0)),
        ("MID", ("a", -1, 1)),
        ("INSERT", ("a", "b", -1)),
        ("DELETE", ("a", 1, 0)),
        ("REPLACE", ("a", "b", -1, 1)),
        ("REPLACE", ("a", "b", 0, 0)),
    ],
)
def test_text_numeric_parameters_are_checked_to_int_and_position_domain(name, values):
    arguments = tuple(
        (value, string()) if isinstance(value, str) else (value, "DINT") for value in values
    )
    with pytest.raises((TypeError, ValueError)):
        sf.evaluate(name, arguments)


@pytest.mark.parametrize(
    "name,parameters",
    [
        ("LEN", ("STR",)),
        ("LEFT", ("STR", "SIZE")),
        ("RIGHT", ("STR", "SIZE")),
        ("MID", ("STR", "LEN", "POS")),
        ("CONCAT", ("STR1", "STR2")),
        ("FIND", ("STR1", "STR2")),
        ("INSERT", ("STR1", "STR2", "POS")),
        ("DELETE", ("STR", "LEN", "POS")),
        ("REPLACE", ("STR1", "STR2", "L", "P")),
    ],
)
def test_text_functions_bind_named_arguments_in_exact_order(name, parameters):
    loc = Location("test", 1, 1)
    arguments = tuple(Argument(key, ":=", Literal(1, loc), loc) for key in parameters)
    assert sf.bind_arguments(name, arguments[::-1]) == arguments
    with pytest.raises(ValueError):
        sf.bind_arguments(name, arguments + arguments[:1])


@pytest.mark.parametrize("name", ["SEL", "MUX"])
def test_selection_uses_max_text_capacity_across_aliases(name):
    selector = (True, "BOOL") if name == "SEL" else (1, "INT")
    arguments = (selector, ("short", t.AliasType("A", string(5))), ("longer", string(12)))
    assert sf.evaluate(name, arguments) == ("longer", string(12))


@pytest.mark.parametrize("name", ["MIN", "MAX", "LIMIT"])
def test_ordered_aggregate_text_overloads_are_not_enabled(name):
    with pytest.raises(TypeError):
        sf.infer_result(name, (string(),) * (3 if name == "LIMIT" else 2))


@pytest.mark.parametrize(
    "name,source,value,want",
    [
        ("TO_STRING", "BOOL", True, "TRUE"),
        ("BOOL_TO_STRING", "BOOL", False, "FALSE"),
        ("INT_TO_STRING", "INTEGER", -123, "-123"),
        ("TO_STRING", "INTEGER", 120, "120"),
        ("BYTE_TO_STRING", "INTEGER", 255, "255"),
        ("DWORD_TO_STRING", "DWORD", 4294967295, "4294967295"),
        ("INT_TO_STRING", "LREAL", 3.5, "4"),
    ],
)
def test_numeric_to_text_conversions_check_source_before_decimal_format(name, source, value, want):
    assert sf.evaluate(name, ((value, source),)) == (want, string(255))


@pytest.mark.parametrize("name", ["TO_STRING", "STRING_TO_STRING"])
def test_text_to_text_conversion_uses_255_byte_storage(name):
    assert sf.evaluate(name, (("a" * 300, string(300)),)) == ("a" * 255, string(255))


@pytest.mark.parametrize(
    "value,want",
    [("TRUE", True), ("true", True), ("True", False), ("1", False), ("FALSE", False), ("", False)],
)
@pytest.mark.parametrize("name", ["TO_BOOL", "STRING_TO_BOOL"])
def test_text_to_bool_uses_exact_vendor_rule(name, value, want):
    assert sf.evaluate(name, ((value, string()),)) == (want, "BOOL")


@pytest.mark.parametrize(
    "target,value,want",
    [
        ("INT", "-32_768", -32768),
        ("UINT", "+65_535", 65535),
        ("DINT", "-2147483648", -2147483648),
        ("UDINT", "4294967295", 4294967295),
        ("BYTE", "255", 255),
        ("WORD", "65535", 65535),
        ("DWORD", "4294967295", 4294967295),
    ],
)
@pytest.mark.parametrize("prefix", ["TO_", "STRING_TO_"])
def test_text_to_integer_parses_decimal_and_checks_destination(target, value, want, prefix):
    assert sf.evaluate(prefix + target, ((value, string()),)) == (want, target)


@pytest.mark.parametrize(
    "value", ["", "+", " 1", "1 ", "1.0", "16#FF", "1_", "_1", "1__2", "١", "32768", "9" * 5000]
)
def test_text_to_integer_rejects_incomplete_nondecimal_or_overflow(value):
    kind = string(max(1, len(value)))
    with pytest.raises((ValueError, TypeError)) as caught:
        sf.evaluate("STRING_TO_INT", ((value, kind),))
    assert "conversion: value has" not in str(caught.value)


def test_text_integer_conversion_handles_many_leading_zeroes_without_python_digit_limit():
    assert sf.evaluate("TO_INT", (("0" * 5000 + "12", string(5002)),)) == (12, "INT")


@pytest.mark.parametrize(
    "name,source",
    [
        ("TO_STRING", "REAL"),
        ("TO_STRING", "TIME"),
        ("REAL_TO_STRING", "REAL"),
        ("TIME_TO_STRING", "TIME"),
        ("STRING_TO_REAL", "text"),
        ("STRING_TO_TIME", "text"),
        ("TO_REAL", "text"),
        ("INT_TO_STRING", "text"),
        ("STRING_TO_INT", "INT"),
        ("BOOL_TO_STRING", "INT"),
    ],
)
def test_text_conversions_reject_unsupported_type_categories(name, source):
    kind = string() if source == "text" else source
    with pytest.raises((TypeError, ValueError)):
        sf.infer_result(name, (kind,))


@pytest.mark.parametrize("bad", ["BOOL", "REAL", "TIME"])
def test_text_functions_reject_noninteger_numeric_parameters(bad):
    with pytest.raises(TypeError):
        sf.infer_result("LEFT", (string(), bad))


def test_text_functions_reject_nontext_and_enum_inputs():
    with pytest.raises(TypeError):
        sf.infer_result("LEN", ("INT",))
    enum = t.EnumType("State", (("A", 0),))
    with pytest.raises(TypeError):
        sf.infer_result("TO_STRING", (enum,))
    with pytest.raises(ValueError):
        sf.evaluate("INT_TO_STRING", ((32768, "INTEGER"),))
