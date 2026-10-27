"""Pure standard-function binding, overload and conversion contracts."""

import pytest

from tc_emulator import standard_functions as sf
from tc_emulator.syntax import Argument, Literal, Location
from tc_emulator.types import AliasType, ArrayType, EnumType, StructField, StructType, check_value

LOC = Location("test", 1, 1)


def argument(name=None, value=1, mode=":="):
    return Argument(name, mode, Literal(value, LOC), LOC)


@pytest.mark.parametrize(
    "name", ["ABS", "MIN", "MAX", "LIMIT", "SEL", "MUX", "TO_INT", "REAL_TO_TIME", "WORD_TO_BOOL"]
)
def test_recognizes_supported_standard_functions(name):
    assert sf.is_standard_function(name)


@pytest.mark.parametrize(
    "name", ["abs", "SIN", "TO_INTEGER", "INT_TO_ENUM", "INTEGER_TO_INT", "X_TO_INT"]
)
def test_rejects_unknown_function_names(name):
    assert not sf.is_standard_function(name)


def test_binds_named_inputs_in_parameter_order_and_limit_synonyms():
    low, value, high = argument("MN", 0), argument("IN", 5), argument("MX", 9)
    assert sf.bind_arguments("LIMIT", (high, value, low)) == (low, value, high)
    alternatives = (argument("IN1", 2), argument("IN0", 1))
    assert sf.bind_arguments("MIN", alternatives) == alternatives[::-1]
    selector = argument("K", 0)
    assert sf.bind_arguments("MUX", (*alternatives, selector)) == (selector, *alternatives[::-1])
    assert sf.bind_arguments("ABS", (argument("IN"),)) == (argument("IN"),)


@pytest.mark.parametrize(
    "name,args",
    [
        ("MIN", (argument(),)),
        ("MAX", ()),
        ("ABS", (argument(), argument())),
        ("SEL", (argument(), argument())),
        ("MUX", (argument(),)),
        ("LIMIT", (argument("MIN"), argument("MN"), argument("IN"))),
        ("MIN", (argument("IN0"), argument("IN2"))),
        ("MIN", (argument("IN0"), argument("IN0"))),
        ("MIN", (argument("IN0"), argument())),
        ("ABS", (argument("OUT"),)),
        ("ABS", (argument("IN", mode="=>"),)),
        ("NOPE", (argument(),)),
    ],
)
def test_rejects_invalid_binding(name, args):
    with pytest.raises((ValueError, TypeError)):
        sf.bind_arguments(name, args)


@pytest.mark.parametrize(
    "name,types,want",
    [
        ("ABS", ("INT",), "INT"),
        ("MIN", ("UINT", "UINT"), "UINT"),
        ("MAX", ("INT", "DINT"), "INTEGER"),
        ("LIMIT", ("INT", "REAL", "LREAL"), "LREAL"),
        ("MIN", ("TIME", "TIME"), "TIME"),
        ("MAX", ("BOOL", "BOOL"), "BOOL"),
        ("SEL", ("BOOL", "INT", "REAL"), "REAL"),
        ("MUX", ("INTEGER", "INT"), "INT"),
        ("ABS", (AliasType("SMALL", "INT"),), "INT"),
    ],
)
def test_infers_canonical_overloads(name, types, want):
    assert sf.infer_result(name, types) == want


@pytest.mark.parametrize(
    "name,types",
    [
        ("ABS", ("BOOL",)),
        ("ABS", ("TIME",)),
        ("MIN", ("TIME", "INT")),
        ("MIN", ("BOOL", "INTEGER")),
        ("SEL", ("INTEGER", "INT", "INT")),
        ("MUX", ("BOOL", "INT")),
        ("MUX", ("REAL", "INT")),
    ],
)
def test_rejects_incompatible_overloads(name, types):
    with pytest.raises((ValueError, TypeError)):
        sf.infer_result(name, types)


@pytest.mark.parametrize(
    "name,args,want",
    [
        ("ABS", ((-7, "INT"),), (7, "INT")),
        ("MIN", ((8, "UINT"), (2, "UINT")), (2, "UINT")),
        ("MAX", ((-8, "INT"), (2, "DINT")), (2, "INTEGER")),
        ("LIMIT", ((10, "INT"), (5, "INT"), (2, "INT")), (2, "INT")),
        ("MAX", ((False, "BOOL"), (True, "BOOL")), (True, "BOOL")),
        ("MIN", ((300, "TIME"), (100, "TIME")), (100, "TIME")),
        ("SEL", ((False, "BOOL"), (2, "INT"), (3.5, "REAL")), (2.0, "REAL")),
        ("MUX", ((100, "INTEGER"), (2, "INT"), (3, "INT")), (3, "INT")),
    ],
)
def test_evaluates_checked_operators(name, args, want):
    assert sf.evaluate(name, args) == want


@pytest.mark.parametrize(
    "type_name,minimum", [("INT", -32768), ("DINT", -2147483648), ("INTEGER", -(2**63))]
)
def test_absolute_value_rejects_signed_minimum_overflow(type_name, minimum):
    with pytest.raises(ValueError):
        sf.evaluate("ABS", ((minimum, type_name),))


def test_selection_supports_aggregate_aliases_and_nominal_enum_order():
    array = ArrayType(((1, 2),), "INT")
    structure = StructType("Pair", (StructField("X", "INT"),))
    enum = EnumType("State", (("HIGH", 10), ("LOW", -1)))
    assert sf.evaluate(
        "SEL", ((True, "BOOL"), ((1, 2), array), ((3, 4), AliasType("A", array)))
    ) == ((3, 4), array)
    selected, result_type = sf.evaluate("MUX", ((0, "INT"), ({"X": 4}, structure)))
    assert dict(selected) == {"X": 4}
    assert result_type == structure
    high, low = check_value(enum, "HIGH"), check_value(enum, "LOW")
    assert sf.evaluate("MIN", ((high, enum), (low, AliasType("S", enum)))) == (low, enum)
    with pytest.raises((ValueError, TypeError)):
        sf.infer_result("MIN", (array, array))
    with pytest.raises((ValueError, TypeError)):
        sf.infer_result("SEL", ("BOOL", enum, EnumType("Other", (("LOW", -1),))))


@pytest.mark.parametrize(
    "name,selector,count,want",
    [("SEL", False, 2, 1), ("SEL", True, 2, 2), ("MUX", 0, 2, 1), ("MUX", 9, 2, 2)],
)
def test_selection_index_uses_full_call_positions(name, selector, count, want):
    assert sf.selection_index(name, selector, count) == want


@pytest.mark.parametrize(
    "name,selector,count",
    [
        ("MUX", -1, 2),
        ("MUX", True, 2),
        ("MUX", 0, 0),
        ("SEL", 0, 2),
        ("SEL", False, 1),
        ("ABS", 0, 2),
    ],
)
def test_selection_index_rejects_invalid_selector(name, selector, count):
    with pytest.raises((ValueError, TypeError)):
        sf.selection_index(name, selector, count)


@pytest.mark.parametrize(
    "name,value,source,want,target",
    [
        ("TO_INT", 2.5, "LREAL", 2, "INT"),
        ("TO_INT", 3.5, "LREAL", 4, "INT"),
        ("TO_DINT", -2.5, "REAL", -2, "DINT"),
        ("TO_DINT", -3.5, "LREAL", -4, "DINT"),
        ("TO_BOOL", -1, "INT", True, "BOOL"),
        ("TO_BOOL", -0.0, "REAL", False, "BOOL"),
        ("BOOL_TO_INT", True, "BOOL", 1, "INT"),
        ("BOOL_TO_REAL", False, "BOOL", 0.0, "REAL"),
        ("TIME_TO_UDINT", 4294967295, "TIME", 4294967295, "UDINT"),
        ("TO_TIME", 12.5, "LREAL", 12, "TIME"),
        ("TIME_TO_INT", 10, "INTEGER", 10, "INT"),
        ("REAL_TO_DINT", 16777217, "INTEGER", 16777216, "DINT"),
        ("INT_TO_LREAL", 3.5, "LREAL", 4.0, "LREAL"),
        ("TO_LREAL", 16777217, "REAL", 16777216.0, "LREAL"),
        ("TO_WORD", 65535, "INTEGER", 65535, "WORD"),
        ("WORD_TO_UINT", 65535, "WORD", 65535, "UINT"),
        ("UINT_TO_WORD", 65535, "UINT", 65535, "WORD"),
    ],
)
def test_converts_scalars_with_checked_sources_and_half_even_rounding(
    name, value, source, want, target
):
    assert sf.infer_result(name, (source,)) == target
    result, result_type = sf.evaluate(name, ((value, source),))
    assert (result, result_type) == (want, target)
    assert type(result) is type(want)


@pytest.mark.parametrize(
    "name,value,source",
    [
        ("TO_UINT", -1, "INTEGER"),
        ("TO_WORD", 65536, "INTEGER"),
        ("TO_INT", 32767.5, "LREAL"),
        ("TO_TIME", -1.0, "LREAL"),
        ("TO_TIME", 4294967295.5, "LREAL"),
        ("TO_UDINT", 4294967296, "INTEGER"),
        ("INT_TO_LREAL", 32768, "INTEGER"),
        ("UINT_TO_DINT", -1, "INTEGER"),
        ("REAL_TO_BOOL", 1e39, "LREAL"),
        ("TO_BOOL", float("nan"), "REAL"),
        ("TO_LREAL", float("inf"), "LREAL"),
        ("TO_DINT", 2**63, "INTEGER"),
    ],
)
def test_conversions_reject_overflow_nonfinite_and_invalid_source_values(name, value, source):
    with pytest.raises((ValueError, TypeError)):
        sf.evaluate(name, ((value, source),))


@pytest.mark.parametrize(
    "name,source",
    [
        ("BOOL_TO_INT", "INTEGER"),
        ("TIME_TO_REAL", "INT"),
        ("TIME_TO_REAL", "LREAL"),
        ("INT_TO_REAL", "BOOL"),
        ("INT_TO_REAL", "TIME"),
        ("TO_INT", EnumType("Choice", (("A", 0),))),
        ("TO_INT", ArrayType(((0, 1),), "INT")),
        ("TO_INT", StructType("Thing", ())),
    ],
)
def test_conversion_source_category_is_enforced_statically(name, source):
    with pytest.raises((ValueError, TypeError)):
        sf.infer_result(name, (source,))


def test_conversions_accept_transparent_scalar_aliases():
    assert sf.evaluate("TO_INT", ((3.5, AliasType("Reading", "LREAL")),)) == (4, "INT")
    assert sf.evaluate("BOOL_TO_TIME", ((True, AliasType("Flag", "BOOL")),)) == (1, "TIME")


@pytest.mark.parametrize(
    "source", ["BOOL", "INT", "UINT", "DINT", "UDINT", "WORD", "REAL", "LREAL", "TIME"]
)
@pytest.mark.parametrize(
    "target", ["BOOL", "INT", "UINT", "DINT", "UDINT", "WORD", "REAL", "LREAL", "TIME"]
)
def test_all_named_scalar_conversion_pairs_accept_checked_unit_value(source, target):
    value = True if source == "BOOL" else 1.0 if source in {"REAL", "LREAL"} else 1
    want = True if target == "BOOL" else 1.0 if target in {"REAL", "LREAL"} else 1
    assert sf.evaluate(f"{source}_TO_{target}", ((value, source),)) == (want, target)


def test_binds_parser_positional_arguments_without_named_mode():
    value = argument(mode="")
    assert sf.bind_arguments("ABS", (value,)) == (value,)
