"""Integer literal grammar and bit-location syntax retain precise AST metadata."""

from dataclasses import FrozenInstanceError

import pytest

from tc_emulator import syntax
from tc_emulator.errors import ParseError
from tc_emulator.parser import parse, parse_type


def expression(text):
    return parse(f"FUNCTION F : DINT\nF := {text};\nEND_FUNCTION", "bits.st").pous[0].body[0].value


@pytest.mark.parametrize(
    ("text", "value", "type_name"),
    [
        ("2#1111_0000", 240, "BYTE"),
        ("8#777", 511, "WORD"),
        ("16#ff", 255, "BYTE"),
        ("16#100", 256, "WORD"),
        ("16#FFFF", 65535, "WORD"),
        ("16#1_0000", 65536, "DWORD"),
        ("16#FFFF_FFFF", 4294967295, "DWORD"),
        ("byte#16#A5", 165, "BYTE"),
        ("WORD#255", 255, "WORD"),
        ("DWORD#2#1", 1, "DWORD"),
        ("INT#-32768", -32768, "INT"),
        ("UINT#+65535", 65535, "UINT"),
        ("DINT#-2147483648", -2147483648, "DINT"),
        ("UDINT#4294967295", 4294967295, "UDINT"),
        ("1_000_000", 1000000, None),
    ],
)
def test_integer_literals_preserve_value_type_and_start(text, value, type_name):
    literal = expression(text)
    assert isinstance(literal, syntax.Literal)
    assert (literal.value, literal.type_name) == (value, type_name)
    assert literal.loc == syntax.Location("bits.st", 2, 6)


@pytest.mark.parametrize("path", ["word.0", "a[i].0", "fb.output.31", "s.array[i].field.0"])
def test_numeric_dot_paths_are_frozen_bit_accesses(path):
    pou = parse(f"FUNCTION F : BOOL\n{path} := TRUE; F := {path};\nEND_FUNCTION", "bits.st").pous[0]
    target, value = pou.body[0].target, pou.body[1].value
    assert isinstance(target, syntax.BitAccess)
    assert isinstance(value, syntax.BitAccess)
    assert target.index.value == (31 if path == "fb.output.31" else 0)
    assert target.index.loc.column == path.rindex(".") + 2
    assert target.loc == syntax.Location("bits.st", 2, 1)
    with pytest.raises(FrozenInstanceError):
        target.index = syntax.Literal(2, target.loc)


def test_named_paths_and_cast_calls_retain_legacy_ast():
    assert expression("config.word.cBit").parts == ("CONFIG", "WORD", "CBIT")
    member = expression("config.words[i].cBit")
    assert isinstance(member, syntax.Member) and member.name == "CBIT"
    call = expression("WORD_TO_BYTE(word)")
    assert isinstance(call, syntax.Call) and call.target.parts == ("WORD_TO_BYTE",)
    assert isinstance(expression("WORD(2)"), syntax.Call)
    assert isinstance(expression("WORD#2"), syntax.Literal)


@pytest.mark.parametrize(
    "text",
    [
        "2#",
        "2#102",
        "8#89",
        "16#FG",
        "3#12",
        "16#1tail",
        "16#1#2",
        "2#_1",
        "16#1_",
        "16#1__0",
        "1__0",
        "1_",
        "BYTE#256",
        "WORD#-1",
        "DWORD#4294967296",
        "INT#16#FFFF",
        "UINT#-1",
        "UDINT#-1",
        "DINT#2147483648",
        "16#100000000",
        "BYTE#16#GG",
        "WORD#1#2",
        "BYTE#1_",
        "BYTE#1name",
        "LWORD#1",
        "16#1.0",
        "(word).0",
        "(1 + 2).0",
        "word.(1)",
        "word.-1",
        "word.0()",
        "words[0].method()",
        "REAL#1_",
        "LREAL#1__0",
        "1_.0",
        "1__0e0",
        "1_e2",
    ],
)
def test_malformed_integer_literals_and_nonlocation_bit_paths_rejected(text):
    with pytest.raises(ParseError):
        expression(text)


def test_integer_literal_metadata_can_be_discarded_in_integer_only_positions():
    assert parse_type("ARRAY[BYTE#0..16#2] OF INT").bounds == ((0, 2),)
    program = parse("""TYPE State : (Idle := INT#-1, Run := 16#2); END_TYPE
    FUNCTION F : INT VAR a : ARRAY[0..1] OF INT := [BYTE#2(7)]; END_VAR
    CASE 1 OF WORD#1: F := 1; 16#2, INT#-1: F := 2; END_CASE;
    END_FUNCTION""")
    assert [member.value for member in program.types[0].definition.members] == [-1, 2]
    assert program.pous[0].variables[0].initial.items[0].count == 2
    assert [arm[0] for arm in program.pous[0].body[0].arms] == [(1,), (2, -1)]


def test_based_literal_negation_remains_unary_and_decimal_signed_minimum_unchanged():
    negative = expression("-16#1")
    assert isinstance(negative, syntax.Unary) and negative.op == "-"
    assert (negative.operand.value, negative.operand.type_name) == (1, "BYTE")
    assert expression("-9223372036854775808").operand.value == 9223372036854775808


@pytest.mark.parametrize("text", ["1.25", "1e-3", "REAL#1", "LREAL#-1.5", "T#1s"])
def test_existing_float_and_time_grammar_keeps_typed_literals(text):
    assert isinstance(expression(text), syntax.Literal)


def test_bit_locations_preserve_remapped_source_positions():
    pou = parse(
        "FUNCTION F : BOOL\n F := words[i].7;\nEND_FUNCTION",
        locations={2: syntax.Location("original.st", 40, 9)},
    ).pous[0]
    bit = pou.body[0].value
    assert bit.loc == syntax.Location("original.st", 40, 15)
    assert bit.index.loc == syntax.Location("original.st", 40, 24)
