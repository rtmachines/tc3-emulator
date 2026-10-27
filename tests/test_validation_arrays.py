"""Whole-program validation for real numbers and fixed scalar arrays."""

from dataclasses import replace

import pytest

from tc_emulator.errors import ValidationError
from tc_emulator.parser import parse
from tc_emulator.syntax import Assign, Literal, Location, Pou, Program, Reference
from tc_emulator.validation import validate


def function(body="", declarations="", name="F", result="INT"):
    return f"FUNCTION {name} : {result}\n{declarations}\n{body}\nEND_FUNCTION\n"


def reject(source, match=None):
    with pytest.raises(ValidationError, match=match) as error:
        validate(parse(source, source="invalid-arrays.st"))
    assert error.value.loc is not None
    assert "invalid-arrays.st" in str(error.value)


def scalar_program(value, result="LREAL"):
    loc = Location("constructed.st", 1, 1)
    return Program(
        (
            Pou(
                "FUNCTION",
                "F",
                result,
                (),
                (Assign(Reference(("F",), loc), Literal(value, loc), loc),),
                loc,
            ),
        )
    )


@pytest.mark.parametrize("result", ["REAL", "LREAL"])
def test_float_literals_and_integer_promotion_are_valid_for_real_results(result):
    validate(scalar_program(1.25, result))
    validate(scalar_program(2, result))


@pytest.mark.parametrize("value", [float("inf"), float("-inf"), float("nan")])
def test_nonfinite_literals_fail_even_in_uncalled_code(value):
    program = scalar_program(value)
    main = replace(program.pous[0], name="MAIN", return_type="INT", body=())
    with pytest.raises(ValidationError, match="finite"):
        validate(Program((main, *program.pous)))


@pytest.mark.parametrize(
    "expression",
    ["1 + REAL#2.5", "REAL#2.5 + 1", "REAL#2.5 / 2", "LREAL#2 + REAL#3", "-1.25"],
)
def test_numeric_expressions_accept_real_promotion(expression):
    validate(parse(function(f"F := {expression};", result="LREAL")))


@pytest.mark.parametrize(
    "body",
    [
        "F := 1.0;",
        "F := REAL#1;",
        "F := 1 MOD 1.0;",
        "F := REAL#1 MOD 1;",
        "IF REAL#1 THEN END_IF;",
        "IF TRUE = 1.0 THEN END_IF;",
        "IF FALSE THEN F := 1.0; END_IF;",
        "CASE 1.0 OF 1: END_CASE;",
        "FOR i := 1.0 TO 2 DO END_FOR;",
        "FOR r := 1 TO 2 DO END_FOR;",
        "F := NOT REAL#1;",
    ],
)
def test_float_to_integer_and_boolean_coercions_are_rejected_in_dead_code(body):
    reject(function(name="MAIN") + function(body, "VAR i : INT; r : REAL; END_VAR"))


@pytest.mark.parametrize(
    "declaration",
    [
        "x : INT := 1.0;",
        "x : REAL := TRUE;",
        "x : LREAL := 1e999;",
        "x : REAL := REAL#3.5e38;",
        "x : LREAL := REAL#3.5e38;",
    ],
)
def test_float_initializers_validate_source_and_destination_ranges(declaration):
    reject(function(declarations=f"VAR {declaration} END_VAR"))


def test_real_comparisons_accept_both_numeric_operand_orders():
    validate(parse(function("IF 1 = 1.0 AND REAL#2 <> 3 AND REAL#2 < 3.0 THEN F := 1; END_IF;")))


def test_arrays_support_return_copy_indexing_parameters_and_fb_fields():
    source = function(
        "a := G(a); b := a; b[-1,2] := 3.5; child.x := b; "
        "child(ref := a, y => b); F := child.y[-1,2];",
        "VAR a,b : ARRAY[-1..0,2..3] OF LREAL; child : B; END_VAR",
        result="LREAL",
    )
    source += function(
        "G := x;",
        "VAR_INPUT x : ARRAY[-1..0,2..3] OF LREAL; END_VAR",
        name="G",
        result="ARRAY[-1..0,2..3] OF LREAL",
    )
    source += """FUNCTION_BLOCK B
    VAR_INPUT x : ARRAY[-1..0,2..3] OF LREAL; END_VAR
    VAR_IN_OUT ref : ARRAY[-1..0,2..3] OF LREAL; END_VAR
    VAR_OUTPUT y : ARRAY[-1..0,2..3] OF LREAL; END_VAR
    VAR_TEMP scratch : ARRAY[1..2] OF BOOL := [TRUE]; END_VAR
    y := x; ref := y;
    END_FUNCTION_BLOCK"""
    validate(parse(source))


@pytest.mark.parametrize(
    "body",
    [
        "a[1] := 1;",
        "a[1,2,3] := 1;",
        "a[TRUE,2] := 1;",
        "a[1.0,2] := 1;",
        "F := i[1];",
        "a := i;",
        "i := a;",
        "a := b;",
        "a := c;",
        "IF a = a THEN END_IF;",
        "IF a <> a THEN END_IF;",
        "a := a + a;",
        "a := -a;",
        "F := a[1,2] MOD REAL#1;",
    ],
)
def test_array_rank_index_types_and_exact_copy_type_are_checked(body):
    reject(
        function(
            body,
            """VAR
        a : ARRAY[1..2,2..3] OF INT;
        b : ARRAY[0..1,2..3] OF INT;
        c : ARRAY[1..2,2..3] OF DINT;
        i : INT;
        END_VAR""",
        )
    )


@pytest.mark.parametrize("initializer", ["[1,2]", "[2(1)]", "[1]", "[]"])
def test_array_initializers_allow_partial_repeated_and_empty_values(initializer):
    validate(parse(function(declarations=f"VAR a : ARRAY[1..2] OF REAL := {initializer}; END_VAR")))


@pytest.mark.parametrize(
    "declaration",
    [
        "VAR a : ARRAY[1..2] OF INT := [1,2,3]; END_VAR",
        "VAR a : ARRAY[1..2] OF INT := [999999999999999(1)]; END_VAR",
        "VAR a : ARRAY[1..2] OF INT := [1.0]; END_VAR",
        "VAR a : ARRAY[1..2] OF BOOL := [1]; END_VAR",
        "VAR a : ARRAY[1..2] OF INT := [32768]; END_VAR",
        "VAR a : ARRAY[1..2] OF INT := [1+TRUE]; END_VAR",
        "VAR a : ARRAY[1..2] OF INT := [a[1]]; END_VAR",
        "VAR a : ARRAY[1..2] OF INT := 1; END_VAR",
        "VAR i : INT := [1]; END_VAR",
        "VAR_IN_OUT a : ARRAY[1..2] OF INT := [1]; END_VAR",
        "VAR a : ARRAY[1..2] OF LREAL := [REAL#3.5e38]; END_VAR",
    ],
)
def test_array_initializers_enforce_shape_constant_type_and_storage(declaration):
    reject(function(declarations=declaration))


@pytest.mark.parametrize("section", ["VAR_IN_OUT", "VAR_OUTPUT"])
def test_array_elements_are_writable_exact_type_call_arguments(section):
    mode = "=>" if section == "VAR_OUTPUT" else ":="
    source = function(
        f"G(x {mode} a[1]);",
        "VAR a : ARRAY[1..2] OF REAL; END_VAR",
    ) + function(declarations=f"{section} x : REAL; END_VAR", name="G")
    validate(parse(source))
    reject(source.replace("x : REAL;", "x : LREAL;"))


@pytest.mark.parametrize("section", ["VAR_INPUT", "VAR_IN_OUT", "VAR_OUTPUT"])
def test_whole_array_arguments_require_exact_bounds_and_element_type(section):
    mode = "=>" if section == "VAR_OUTPUT" else ":="
    callee = function(declarations=f"{section} x : ARRAY[1..2] OF REAL; END_VAR", name="G")
    validate(parse(function(f"G(x {mode} a);", "VAR a : ARRAY[1..2] OF REAL; END_VAR") + callee))
    for actual in ["ARRAY[0..1] OF REAL", "ARRAY[1..2] OF LREAL", "REAL"]:
        reject(function(f"G(x {mode} a);", f"VAR a : {actual}; END_VAR") + callee)


def test_out_of_range_constant_indices_remain_runtime_checks():
    validate(parse(function("a[-99] := 1; F := a[99];", "VAR a : ARRAY[1..2] OF INT; END_VAR")))


@pytest.mark.parametrize("sign", ["", "-"])
def test_exact_real_literal_below_overflow_midpoint_is_a_valid_constant(sign):
    # This integer is one unit below the exact binary32 overflow midpoint.
    # Its Python float approximation is at the midpoint and would overflow.
    literal = f"REAL#{sign}340282356779733661637539395458142568447"
    source = function(declarations=f"VAR x : LREAL := {literal}; END_VAR")
    validate(parse(source))


@pytest.mark.parametrize("element_type", ["REAL", "LREAL"])
def test_typed_real_initializer_rounds_exact_decimal_once_before_storage(element_type):
    from tc_emulator import Runtime

    literal = "REAL#1.00000005960464477539062500000000001"
    source = function(
        "F := scalar;",
        f"VAR scalar : LREAL := {literal}; END_VAR\n"
        f"VAR_OUTPUT values : ARRAY[1..2] OF {element_type} := [2({literal})]; END_VAR",
        result="LREAL",
    )
    result = Runtime.from_source(source).call("F")
    assert result.value == 1.0000001192092896
    assert result.outputs["VALUES"] == (1.0000001192092896, 1.0000001192092896)
