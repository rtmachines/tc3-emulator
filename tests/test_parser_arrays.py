"""Syntax regressions for floating literals and fixed scalar arrays."""

import pytest

from tc_emulator import parser
from tc_emulator.errors import ParseError
from tc_emulator.syntax import Location


def expression(text):
    return parser.parse(f"FUNCTION F : LREAL F := {text}; END_FUNCTION").pous[0].body[0].value


@pytest.mark.parametrize(
    "text,value,precision",
    [
        ("1.25", 1.25, "LREAL"),
        ("1e-3", 0.001, "LREAL"),
        ("2E+3", 2000.0, "LREAL"),
        ("REAL#1", 1.0, "REAL"),
        ("real#-1.25", -1.25, "REAL"),
        ("LREAL#+2e3", 2000.0, "LREAL"),
    ],
)
def test_real_literal_keeps_its_precision(text, value, precision):
    literal = expression(text)
    assert literal.value == value
    assert literal.type_name == precision
    assert type(literal.value) is float


def test_multidimensional_type_and_compact_initializer():
    pou = parser.parse("""FUNCTION F : ARRAY[-2..0, +1..2] OF REAL
    VAR_INPUT a : ARRAY[-2..0, 1..2] OF REAL := [2(REAL#1.5), -2.0, 3]; END_VAR
    F := a;
    END_FUNCTION""").pous[0]
    assert pou.return_type.bounds == ((-2, 0), (1, 2))
    assert pou.return_type.element_type == "REAL"
    assert pou.variables[0].type_name == pou.return_type
    initial = pou.variables[0].initial
    assert [item.count for item in initial.items] == [2, 1, 1]
    assert initial.items[0].value.value == 1.5
    assert initial.items[1].value.op == "-"


def test_index_read_write_call_bindings_and_loop_target():
    pou = parser.parse("""FUNCTION F : INT
    child.output[i, 2] := a[-1];
    child(v := a[i], v2 => a[j]);
    FOR a[0] := 1 TO 3 DO F := a[0]; END_FOR;
    END_FUNCTION""").pous[0]
    target = pou.body[0].target
    assert target.base.parts == ("CHILD", "OUTPUT")
    assert len(target.indices) == 2
    assert pou.body[0].value.base.parts == ("A",)
    assert pou.body[1].call.arguments[1].value.base.parts == ("A",)
    assert pou.body[2].variable.base.parts == ("A",)


def test_array_source_positions_survive_section_mapping():
    pou = parser.parse(
        "FUNCTION F : INT\nVAR a : ARRAY[1..2] OF LREAL := [1.5]; END_VAR\na[1] := a[2];\nEND_FUNCTION",
        locations={2: Location("vars.xml", 20, 4), 3: Location("body.xml", 30, 8)},
    ).pous[0]
    assert pou.variables[0].loc == Location("vars.xml", 20, 8)
    assert pou.variables[0].initial.loc == Location("vars.xml", 20, 36)
    assert pou.body[0].target.loc == Location("body.xml", 30, 8)
    assert pou.body[0].target.indices[0].loc == Location("body.xml", 30, 10)


def test_empty_array_initializer_and_large_repetition_are_not_expanded():
    pou = parser.parse("""FUNCTION F : INT
    VAR a : ARRAY[1..3] OF INT := []; b : ARRAY[1..3] OF INT := [1000000(1)]; END_VAR
    END_FUNCTION""").pous[0]
    assert pou.variables[0].initial.items == ()
    assert len(pou.variables[1].initial.items) == 1
    assert pou.variables[1].initial.items[0].count == 1000000


@pytest.mark.parametrize("text", ["INT#TRUE", "LREAL#TRUE", "REAL#--1", "1e", "1e+"])
def test_malformed_or_unsupported_typed_literals_rejected(text):
    with pytest.raises(ParseError):
        expression(text)


@pytest.mark.parametrize(
    "declaration",
    [
        "ARRAY[*, 1..2] OF INT",
        "ARRAY[2..1] OF INT",
        "ARRAY[1.0..2] OF INT",
        "ARRAY[1..2] OF ARRAY[1..2] OF INT",
        "ARRAY[1..2] OF 123",
        "ARRAY[1..1000001] OF INT",
        "ARRAY[-2147483649..0] OF INT",
        "ARRAY[1..2] OF INT := [0(1)]",
        "ARRAY[1..2] OF INT := [2()]",
    ],
)
def test_invalid_array_declarations_rejected(declaration):
    with pytest.raises(ParseError):
        parser.parse(f"FUNCTION F : INT VAR a : {declaration}; END_VAR END_FUNCTION")


@pytest.mark.parametrize("text", ["a[]", "a[1..2]", "a[1][]", "a[1](2,)", "[1,2]"])
def test_only_supported_index_syntax_is_an_expression(text):
    with pytest.raises(ParseError):
        expression(text)


def test_standalone_type_parser_consumes_all_tokens():
    array = parser.parse_type("array[-1..1,2..3] of lreal")
    assert array.bounds == ((-1, 1), (2, 3))
    assert array.element_type == "LREAL"
    assert parser.parse_type("real") == "REAL"
    for text in ("INT;", "INT junk", "ARRAY[1..2] OF REAL; RETURN;", "__import__('os')"):
        with pytest.raises(ParseError):
            parser.parse_type(text)


@pytest.mark.parametrize(
    "text,raw_text",
    [
        ("REAL#1.00000005960464477539062500000000001", "1.00000005960464477539062500000000001"),
        ("REAL#-1.00000005960464477539062500000000001", "-1.00000005960464477539062500000000001"),
        ("LREAL#+2e3", "+2e3"),
        ("2E+003", "2E+003"),
        ("REAL#1", "1"),
    ],
)
def test_float_literal_keeps_exact_decimal_source_for_precision_rounding(text, raw_text):
    literal = expression(text)
    assert literal.raw_text == raw_text
    assert type(literal.value) is float
