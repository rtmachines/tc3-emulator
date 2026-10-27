"""TIME literal grammar, exact precision and source-aware diagnostics."""

import pytest

from tc_emulator.errors import ParseError
from tc_emulator.parser import parse, parse_type
from tc_emulator.syntax import Binary, Literal, Location, Unary
from tc_emulator.types import ArrayType


def expression(text):
    return (
        parse(f"FUNCTION F : TIME\n  F := {text};\nEND_FUNCTION", "time.st").pous[0].body[0].value
    )


@pytest.mark.parametrize(
    ("text", "milliseconds"),
    [
        ("T#0ms", 0),
        ("time#1S", 1000),
        ("t#1h2m3s4ms", 3723004),
        ("TIME#1d_2h_3m_4s_5ms", 93784005),
        ("T#49d17h2m47s295ms", 4294967295),
        ("T#4294967295ms", 4294967295),
        ("T#25h", 90000000),
        ("T#61m", 3660000),
        ("T#61s", 61000),
        ("T#1001ms", 1001),
        ("T#1.5h", 5400000),
        ("T#1h_2.5m", 3750000),
        ("T#1.001s", 1001),
        ("T#0.00001d", 864),
        ("T#0.0000003125d", 27),
        ("T#0.0000025h", 9),
        ("T#1.000ms", 1),
        ("T#0.000000000000000000s", 0),
        ("T#00000000000000000001s", 1000),
    ],
)
def test_time_literals_produce_typed_integer_milliseconds(text, milliseconds):
    result = expression(text)
    assert isinstance(result, Literal)
    assert result.value == milliseconds
    assert type(result.value) is int
    assert result.type_name == "TIME"
    assert result.loc == Location("time.st", 2, 8)


@pytest.mark.parametrize(
    "text",
    [
        "T#",
        "TIME#",
        "T#-1s",
        "T#+1s",
        "T#1",
        "T#1us",
        "T#1ns",
        "LTIME#1s",
        "T#1s1m",
        "T#1s1s",
        "T#1d24h",
        "T#1h60m",
        "T#1m60s",
        "T#1s1000ms",
        "T#1.5h1m",
        "T#1.5h_1m",
        "T#0.0001ms",
        "T#0.0001s",
        "T#1e3ms",
        "T#1e-3s",
        "T#1_s",
        "T#_1s",
        "T#1s_",
        "T#1s__2ms",
        "T#1.s",
        "T#.5s",
        "T#1..2s",
        "T#1sXYZ",
        "T#4294967296ms",
        "T#50d",
        "T#49d17h2m47s296ms",
    ],
)
def test_malformed_and_overflowing_time_literals_are_rejected_at_the_prefix(text):
    with pytest.raises(ParseError) as caught:
        expression(text)
    assert caught.value.loc == Location("time.st", 2, 8)


def test_time_literals_keep_adjacent_operators_and_comments():
    result = expression("+T#1s+TIME#2s-T#3ms(*comment*)")
    assert isinstance(result, Binary) and result.op == "-"
    assert result.right.value == 3
    assert result.left.op == "+"
    assert isinstance(result.left.left, Unary)
    assert result.left.left.operand.value == 1000
    assert result.left.right.value == 2000


def test_time_arrays_and_repeated_declaration_initializers_parse():
    pou = parse("""FUNCTION F : TIME
VAR values : ARRAY[0..2] OF TIME := [2(T#1s), TIME#2ms]; END_VAR
F := values[0];
END_FUNCTION""").pous[0]
    assert pou.variables[0].type_name == ArrayType(((0, 2),), "TIME")
    assert [(item.count, item.value.value) for item in pou.variables[0].initial.items] == [
        (2, 1000),
        (1, 2),
    ]
    assert parse_type("TIME") == "TIME"


def test_time_literal_errors_preserve_original_source_mapping():
    with pytest.raises(ParseError) as caught:
        parse(
            "FUNCTION F : TIME\nF := T#1us;\nEND_FUNCTION",
            locations={2: Location("x.TcPOU", 40, 5)},
        )
    assert caught.value.loc == Location("x.TcPOU", 40, 10)


@pytest.mark.parametrize("body", ["9" * 5000 + "ms", "0." + "1" * 5000 + "s", "1s_" * 5000])
def test_excessive_time_text_has_parse_error_instead_of_conversion_failure(body):
    with pytest.raises(ParseError) as caught:
        expression("T#" + body)
    assert caught.value.loc == Location("time.st", 2, 8)


def test_existing_float_and_integer_literal_lexing_is_unchanged():
    for text, value, kind in [
        ("123", 123, None),
        ("1.5", 1.5, "LREAL"),
        ("1e-3", 0.001, "LREAL"),
        ("REAL#-1.5e+2", -150.0, "REAL"),
        ("LREAL#+2", 2.0, "LREAL"),
    ]:
        result = expression(text)
        assert result.value == value
        assert result.type_name == kind
