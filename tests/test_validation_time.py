"""TIME stays distinct from numbers across static checking and timer interfaces."""

import pytest

from tc_emulator.errors import ValidationError
from tc_emulator.syntax import (
    Argument,
    ArrayInitializer,
    ArrayItem,
    Assign,
    Binary,
    Call,
    CallStatement,
    Literal,
    Location,
    Pou,
    Program,
    Reference,
    Unary,
    VarDecl,
)
from tc_emulator.types import ArrayType
from tc_emulator.validation import validate

LOC = Location("time-validation.st", 3, 7)


def literal(value=1000, type_name="TIME"):
    return Literal(value, LOC, type_name)


def ref(*parts):
    return Reference(parts, LOC)


def variable(name, type_name="TIME", section="VAR", initial=None):
    return VarDecl(name, type_name, section, initial, LOC)


def function(body=(), variables=(), name="F", result="TIME"):
    return Pou("FUNCTION", name, result, tuple(variables), tuple(body), LOC)


def check_expression(expression, result="TIME", variables=()):
    return validate(
        Program((function((Assign(ref("F"), expression, LOC),), variables, result=result),))
    )


def reject_expression(expression, result="TIME", variables=()):
    with pytest.raises(ValidationError) as error:
        check_expression(expression, result, variables)
    assert error.value.loc == LOC


def call(target, *arguments):
    return Call(ref(target), tuple(arguments), LOC)


def argument(name, value, mode=":="):
    return Argument(name, mode, value, LOC)


@pytest.mark.parametrize("expression", [literal(), Unary("+", literal(), LOC)])
def test_time_literals_and_unary_plus_produce_time(expression):
    check_expression(expression)


@pytest.mark.parametrize("op", ["+", "-"])
def test_time_arithmetic_produces_time(op):
    check_expression(Binary(op, literal(2000), literal(1000), LOC))


@pytest.mark.parametrize("op", ["=", "<>", "<", "<=", ">", ">="])
def test_time_comparisons_produce_bool(op):
    check_expression(Binary(op, literal(), literal(), LOC), "BOOL")


@pytest.mark.parametrize("op", ["*", "/", "MOD", "AND", "OR", "XOR"])
def test_time_has_no_other_binary_operators(op):
    reject_expression(Binary(op, literal(), literal(), LOC))


@pytest.mark.parametrize("op", ["-", "NOT"])
def test_time_has_no_negation(op):
    reject_expression(Unary(op, literal(), LOC))


@pytest.mark.parametrize("op", ["+", "-", "*", "/", "MOD", "=", "<>", "<", "<=", ">", ">="])
@pytest.mark.parametrize("reverse", [False, True])
def test_time_rejects_mixed_numeric_operands(op, reverse):
    operands = [literal(), literal(1, None)]
    if reverse:
        operands.reverse()
    reject_expression(
        Binary(op, *operands, LOC), "BOOL" if op in {"=", "<>", "<", "<=", ">", ">="} else "TIME"
    )


@pytest.mark.parametrize("value,type_name", [(0, None), (0.0, "LREAL"), (False, None)])
def test_numeric_and_bool_expressions_cannot_assign_time(value, type_name):
    reject_expression(literal(value, type_name))


@pytest.mark.parametrize("result", ["INT", "UDINT", "REAL", "LREAL", "BOOL"])
def test_time_expressions_cannot_assign_numeric_or_bool(result):
    reject_expression(literal(), result)


@pytest.mark.parametrize("value", [-1, 2**32, True, 1.0])
def test_direct_ast_time_literal_must_fit_time_storage(value):
    reject_expression(literal(value))


@pytest.mark.parametrize("array", [False, True])
@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("signed", [False, True])
def test_initializers_reject_time_integer_mixing_even_for_zero(array, reverse, signed):
    declared = "UDINT" if reverse else "TIME"
    initial = literal(0, "TIME" if reverse else None)
    if signed:
        initial = Unary("+", initial, LOC)
    if array:
        declared = ArrayType(((1, 2),), declared)
        initial = ArrayInitializer((ArrayItem(initial, 2),), LOC)
    with pytest.raises(ValidationError) as error:
        validate(Program((function(variables=(variable("X", declared, initial=initial),)),)))
    assert error.value.loc == LOC


@pytest.mark.parametrize("array", [False, True])
@pytest.mark.parametrize("signed", [False, True])
def test_time_initializers_allow_literals_and_unary_plus(array, signed):
    declared = "TIME"
    initial = literal(1234)
    if signed:
        initial = Unary("+", initial, LOC)
    if array:
        declared = ArrayType(((1, 3),), declared)
        initial = ArrayInitializer((ArrayItem(initial, 2),), LOC)
    validate(Program((function(variables=(variable("X", declared, initial=initial),)),)))


def test_time_negation_is_rejected_in_initializers():
    with pytest.raises(ValidationError):
        validate(
            Program((function(variables=(variable("X", initial=Unary("-", literal(0), LOC)),)),))
        )


@pytest.mark.parametrize("section", ["VAR_INPUT", "VAR_IN_OUT", "VAR_OUTPUT"])
def test_time_calls_accept_matching_values_references_and_arrays(section):
    for kind in ["TIME", ArrayType(((1, 2),), "TIME")]:
        mode = "=>" if section == "VAR_OUTPUT" else ":="
        callee = function(variables=(variable("X", kind, section),), name="G")
        caller = function(
            (CallStatement(call("G", argument("X", ref("VALUE"), mode)), LOC),),
            (variable("VALUE", kind),),
        )
        validate(Program((caller, callee)))


@pytest.mark.parametrize("section", ["VAR_INPUT", "VAR_IN_OUT", "VAR_OUTPUT"])
@pytest.mark.parametrize("reverse", [False, True])
def test_time_calls_reject_integer_coercion(section, reverse):
    expected, actual = ("UDINT", "TIME") if reverse else ("TIME", "UDINT")
    mode = "=>" if section == "VAR_OUTPUT" else ":="
    callee = function(variables=(variable("X", expected, section),), name="G")
    caller = function(
        (CallStatement(call("G", argument("X", ref("VALUE"), mode)), LOC),),
        (variable("VALUE", actual),),
    )
    with pytest.raises(ValidationError):
        validate(Program((caller, callee)))


@pytest.mark.parametrize("timer", ["TON", "TOF", "TP"])
def test_timers_are_available_without_user_declarations(timer):
    caller = function(
        (
            CallStatement(
                call(
                    "T",
                    argument("IN", literal(True, None)),
                    argument("PT", literal()),
                    argument("Q", ref("FLAG"), "=>"),
                    argument("ET", ref("ELAPSED"), "=>"),
                ),
                LOC,
            ),
            CallStatement(call("T"), LOC),
            Assign(ref("F"), ref("T", "ET"), LOC),
        ),
        (variable("T", timer), variable("FLAG", "BOOL"), variable("ELAPSED")),
    )
    table = validate(Program((caller,)))
    assert table[timer].kind == "FUNCTION_BLOCK"


@pytest.mark.parametrize("timer", ["TON", "TOF", "TP"])
@pytest.mark.parametrize("kind", ["FUNCTION", "FUNCTION_BLOCK"])
def test_user_pous_cannot_override_reserved_timer_names(timer, kind):
    impostor = Pou(kind, timer, "TIME" if kind == "FUNCTION" else None, (), (), LOC)
    with pytest.raises(ValidationError, match="reserved|Duplicate"):
        validate(Program((impostor,)))


@pytest.mark.parametrize(
    "arguments",
    [
        (argument("IN", literal()),),
        (argument("PT", literal(0, None)),),
        (argument("UNKNOWN", literal()),),
        (argument("IN", literal(True, None)), argument("IN", literal(False, None))),
        (argument("PT", ref("VALUE"), "=>"),),
        (argument("ET", ref("NUMBER"), "=>"),),
        (argument("Q", ref("VALUE"), "=>"),),
        (argument("ET", literal(), "=>"),),
        (Argument(None, "", literal(), LOC),),
    ],
)
def test_timer_calls_check_arguments(arguments):
    caller = function(
        (CallStatement(call("T", *arguments), LOC),),
        (variable("T", "TON"), variable("VALUE"), variable("NUMBER", "UDINT")),
    )
    with pytest.raises(ValidationError):
        validate(Program((caller,)))


@pytest.mark.parametrize("timer", ["TON", "TOF", "TP"])
def test_timer_type_cannot_be_called_without_an_instance(timer):
    with pytest.raises(ValidationError, match="require an instance"):
        validate(Program((function((CallStatement(call(timer), LOC),)),)))


def test_timer_call_cannot_be_used_as_expression():
    reject_expression(call("T"), variables=(variable("T", "TON"),))
