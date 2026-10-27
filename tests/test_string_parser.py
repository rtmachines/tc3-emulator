"""Latin-1 STRING syntax, escapes, capacities and precise diagnostics."""

import pytest

from tc_emulator import types
from tc_emulator.errors import ParseError
from tc_emulator.parser import parse, parse_type
from tc_emulator.syntax import ArrayBounds, Binary, Literal, Location, Reference


def expression(text):
    return (
        parse(f"FUNCTION F : STRING\n  F := {text};\nEND_FUNCTION", "strings.st")
        .pous[0]
        .body[0]
        .value
    )


@pytest.mark.parametrize(
    "text,value,capacity",
    [
        ("''", "", 1),
        ("'Mixed Case'", "Mixed Case", 10),
        ("'(* // *)'", "(* // *)", 8),
        ("string#'AbC'", "AbC", 3),
        ("'caféÿ'", "caféÿ", 5),
        ("'$$$'$L$N$R$T$P$00$ff'", "$'\n\n\r\t\f", 9),
        ("'$l$n$r$t$p$4a$e9'", "\n\n\r\t\fJé", 7),
    ],
)
def test_string_literals_decode_preserve_case_and_normalize_nul(text, value, capacity):
    literal = expression(text)
    assert isinstance(literal, Literal)
    assert literal.value == value
    assert literal.type_name == types.StringType(capacity)
    assert literal.loc == Location("strings.st", 2, 8)


@pytest.mark.parametrize(
    "text",
    [
        "'unterminated",
        "'raw\nnewline'",
        "'raw\rcarriage'",
        "'$'",
        "'$Q'",
        "'$0'",
        "'$0G'",
        "'$GG'",
        "'€'",
        "'$00€'",
        '"wide"',
        "WSTRING#'wide'",
        "UTF8#'text'",
        "STRING#1",
    ],
)
def test_invalid_string_literals_have_source_location(text):
    with pytest.raises(ParseError) as caught:
        expression(text)
    assert caught.value.loc.source == "strings.st"
    assert caught.value.loc.line == 2
    assert caught.value.loc.column >= 8


def test_literal_source_mapping_and_adjacent_comment_are_preserved():
    pou = parse(
        "FUNCTION F : STRING\nF := 'Ab$27C'(* tail *);\nEND_FUNCTION",
        locations={2: Location("body.xml", 30, 5)},
    ).pous[0]
    assert pou.body[0].value.value == "Ab'C"
    assert pou.body[0].value.loc == Location("body.xml", 30, 10)


@pytest.mark.parametrize("text,capacity", [("STRING", 80), ("string(4)", 4), ("STRING[9]", 9)])
def test_literal_string_capacities_parse_as_value_types(text, capacity):
    assert parse_type(text) == types.StringType(capacity)
    pou = parse(f"FUNCTION F : {text} VAR x : {text}; END_VAR END_FUNCTION").pous[0]
    assert pou.return_type == types.StringType(capacity)
    assert pou.variables[0].type_name == types.StringType(capacity)


def test_named_and_arithmetic_capacities_remain_expressions_for_validation():
    pou = parse("""FUNCTION F : STRING(N)
VAR CONSTANT N : INT := 7; END_VAR
VAR x : STRING[N + 1]; a : ARRAY[1..2] OF STRING(N); END_VAR
END_FUNCTION""").pous[0]
    assert isinstance(pou.return_type.length, Reference)
    assert pou.return_type.length.parts == ("N",)
    assert isinstance(pou.variables[1].type_name.length, Binary)
    array = pou.variables[2].type_name
    assert isinstance(array, ArrayBounds)
    assert array.element_type.length.parts == ("N",)


def test_arrays_of_literal_strings_preserve_capacity_and_initializers():
    array = parse_type("ARRAY[-1..1, 2..3] OF STRING(12)")
    assert array == types.ArrayType(((-1, 1), (2, 3)), types.StringType(12))
    pou = parse("""FUNCTION F : INT
VAR a : ARRAY[1..N] OF STRING[4] := [2('Ab'), 'c']; END_VAR
END_FUNCTION""").pous[0]
    assert isinstance(pou.variables[0].type_name, ArrayBounds)
    assert pou.variables[0].type_name.element_type == types.StringType(4)
    assert [item.value.value for item in pou.variables[0].initial.items] == ["Ab", "c"]


@pytest.mark.parametrize("text", ["STRING(0)", "STRING[1000001]", "STRING(TRUE)", "STRING(1.5)"])
def test_invalid_literal_capacities_raise_parse_error(text):
    with pytest.raises(ParseError):
        parse_type(text)


@pytest.mark.parametrize("text", ["STRING(N)", "ARRAY[1..2] OF STRING(N)"])
def test_standalone_type_parser_rejects_capacity_names_without_scope(text):
    with pytest.raises(ParseError, match="capacity|constant|scope"):
        parse_type(text)


def test_oversized_literal_is_rejected_with_source_location():
    with pytest.raises(ParseError) as caught:
        expression("'" + "x" * 1_000_001 + "'")
    assert caught.value.loc == Location("strings.st", 2, 8)
