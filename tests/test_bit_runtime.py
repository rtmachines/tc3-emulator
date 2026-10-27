"""Bit operations and live views through ST and the public runtime API."""

import pytest

from tc_emulator import ArgumentError, ExecutionError, Runtime, RuntimeFaultedError, ValidationError


def test_python_bit_view_preserves_neighbors_and_tracks_parent_replacement():
    runtime = Runtime.from_source("")
    word = runtime.cell("WORD", 0xAA00)
    bit = word.bit(3)
    assert bit.type_name == "BOOL" and bit.value is False
    bit.value = True
    assert word.value == 0xAA08
    word.value = 0x5500
    assert bit.value is False
    bit.value = True
    assert word.value == 0x5508
    for invalid in (1, 0, "true", None):
        with pytest.raises(ArgumentError):
            bit.value = invalid
    assert word.value == 0x5508


@pytest.mark.parametrize("kind,index,expected", [("INT", 15, -32768), ("DINT", 31, -2147483648)])
def test_signed_python_bit_access_uses_twos_complement(kind, index, expected):
    word = Runtime.from_source("").cell(kind, 0)
    word.bit(index).value = True
    assert word.value == expected
    word.value = -1
    word.bit(index).value = False
    assert word.value == -expected - 1


def test_bit_view_survives_replacement_of_enclosing_structure_and_array():
    runtime = Runtime.from_source(
        """TYPE S:STRUCT words:ARRAY[1..2] OF WORD; END_STRUCT END_TYPE"""
    )
    cell = runtime.cell("S", {"words": [1, 2]})
    bit = cell.field("words").element(2).bit(1)
    assert bit.value is True
    cell.value = {"words": [3, 0]}
    bit.value = True
    assert cell.value["words"] == (3, 2)


def test_python_bit_arguments_are_rejected_as_inout_and_invalid_indices_are_atomic():
    runtime = Runtime.from_source("""FUNCTION Change:BOOL VAR_IN_OUT x:BOOL; END_VAR
    x:=TRUE; Change:=x; END_FUNCTION""")
    word = runtime.cell("WORD", 0)
    with pytest.raises(ArgumentError):
        runtime.call("Change", x=word.bit(0))
    for invalid in (-1, 16, True, 1.0):
        with pytest.raises(ArgumentError):
            word.bit(invalid)
    for kind, value in (("BOOL", False), ("TIME", 0), ("REAL", 0.0)):
        with pytest.raises(ArgumentError):
            runtime.cell(kind, value).bit(0)
    assert word.value == 0


@pytest.mark.parametrize(
    "expression,kind,expected",
    [
        ("NOT BYTE#0", "BYTE", 255),
        ("NOT WORD#0", "WORD", 65535),
        ("NOT DWORD#0", "DWORD", 4294967295),
        ("BYTE#16#F0 AND BYTE#16#3C", "BYTE", 0x30),
        ("16#0F OR WORD#16#8000", "WORD", 0x800F),
        ("DWORD#16#FFFF_FFFF XOR DWORD#16#8000_0000", "DWORD", 0x7FFFFFFF),
        ("WORD#16#FF00 AND 255", "WORD", 0),
        ("SHL(BYTE#1,7)", "BYTE", 128),
        ("SHL(BYTE#1,8)", "BYTE", 0),
        ("SHR(DWORD#16#8000_0000,31)", "DWORD", 1),
        ("ROL(BYTE#16#80,9)", "BYTE", 1),
        ("ROR(WORD#1,1)", "WORD", 0x8000),
        ("ROL(IN:=DWORD#1,N:=32)", "DWORD", 1),
        ("SHL(1,16)", "DWORD", 65536),
        ("WORD_TO_BYTE(SHR(WORD#16#ABCD,8))", "BYTE", 0xAB),
        ("DWORD_TO_LREAL(DWORD#16#FFFF_FFFF)", "LREAL", 4294967295.0),
        ("SHR(NOT BYTE#0,4)", "BYTE", 15),
    ],
)
def test_bit_expressions_preserve_width_through_real_st_calls(expression, kind, expected):
    runtime = Runtime.from_source(f"FUNCTION F:{kind} F:={expression}; END_FUNCTION")
    assert runtime.call("F").value == expected


def test_st_bit_paths_named_indices_and_output_bindings_write_through():
    runtime = Runtime.from_source("""TYPE S:STRUCT words:ARRAY[1..2] OF WORD; END_STRUCT END_TYPE
    FUNCTION Emit:BOOL VAR_OUTPUT signal:BOOL; END_VAR signal:=TRUE; Emit:=TRUE; END_FUNCTION
    FUNCTION F:WORD
    VAR CONSTANT enable:INT:=7; END_VAR
    VAR s:S:=(words:=[16#0100,16#8000]); END_VAR
    s.words[1].enable:=TRUE;
    Emit(signal=>s.words[1].0);
    IF s.words[1].enable THEN s.words[2].15:=FALSE; END_IF;
    F:=s.words[1] OR s.words[2]; END_FUNCTION""")
    assert runtime.call("F").value == 0x181


def test_st_signed_bit_access_and_bool_copy_input():
    runtime = Runtime.from_source("""FUNCTION Toggle:BOOL VAR_INPUT x:BOOL; END_VAR
    x:=NOT x; Toggle:=x; END_FUNCTION
    FUNCTION F:INT VAR word:INT; END_VAR
    word.15:=TRUE; IF Toggle(word.15) THEN word.0:=TRUE; END_IF;
    F:=word; END_FUNCTION""")
    assert runtime.call("F").value == -32768


def test_constant_bit_operations_and_bit_read_define_array_bounds():
    runtime = Runtime.from_source("""FUNCTION F:WORD
    VAR CONSTANT mask:WORD:=NOT WORD#16#FFFC; enabled:BOOL:=mask.0; END_VAR
    VAR a:ARRAY[0..mask] OF WORD; END_VAR
    IF enabled THEN a[3]:=16#CAFE; END_IF; F:=a[3]; END_FUNCTION""")
    assert runtime.call("F").value == 0xCAFE


def test_bit_indexed_owner_expression_is_evaluated_once():
    runtime = Runtime.from_source("""FUNCTION IndexOf:INT VAR_IN_OUT calls:INT; END_VAR
    calls:=calls+1; IndexOf:=1; END_FUNCTION
    FUNCTION F:WORD VAR_IN_OUT calls:INT; END_VAR
    VAR a:ARRAY[1..1] OF WORD; END_VAR
    a[IndexOf(calls)].3:=TRUE; F:=a[1]; END_FUNCTION""")
    calls = runtime.cell("INT", 0)
    assert runtime.call("F", calls=calls).value == 8
    assert calls.value == 1


@pytest.mark.parametrize("expression", ["SHL(BYTE#1,-1)", "WORD#1 AND -1", "TO_BYTE(256)"])
def test_bit_execution_errors_fault_runtime_but_keep_bit_views_readable(expression):
    runtime = Runtime.from_source(f"FUNCTION F:WORD F:={expression}; END_FUNCTION")
    cell = runtime.cell("WORD", 1)
    bit = cell.bit(0)
    with pytest.raises(ExecutionError):
        runtime.call("F")
    assert bit.value is True
    with pytest.raises(RuntimeFaultedError):
        bit.value = False


def test_bool_logical_operations_still_return_bool():
    runtime = Runtime.from_source("FUNCTION F:BOOL F:=NOT FALSE AND TRUE XOR FALSE; END_FUNCTION")
    assert runtime.call("F").value is True


@pytest.mark.parametrize("body", ["Change(x:=word.0);", "Change(x:=word.index);"])
def test_st_bit_locations_cannot_be_inout(body):
    with pytest.raises(ValidationError):
        Runtime.from_source(
            """FUNCTION Change:BOOL VAR_IN_OUT x:BOOL; END_VAR END_FUNCTION
        FUNCTION F:BOOL VAR word:WORD; END_VAR VAR CONSTANT index:INT:=0; END_VAR
        """
            + body
            + " END_FUNCTION"
        )
