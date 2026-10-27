"""Whole-program static checks, including unreachable and uncalled bodies."""

import pytest

from tc_emulator.errors import ValidationError
from tc_emulator.parser import parse
from tc_emulator.validation import validate


def function(body="", declarations="", name="F", result="INT"):
    return f"FUNCTION {name} : {result}\n{declarations}\n{body}\nEND_FUNCTION\n"


def block(body="", declarations="", name="B"):
    return f"FUNCTION_BLOCK {name}\n{declarations}\n{body}\nEND_FUNCTION_BLOCK\n"


def reject(source):
    with pytest.raises(ValidationError) as error:
        validate(parse(source, source="invalid.st"))
    assert error.value.loc is not None
    assert "invalid.st" in str(error.value)


def test_forward_function_and_fb_types_are_validated_together():
    source = function("b(); F := G(a := b.y);", "VAR b : B; END_VAR")
    source += function("G := a + 1;", "VAR_INPUT a : UINT; END_VAR", name="G")
    source += block("y := 2;", "VAR_OUTPUT y : UINT; END_VAR")
    program = parse(source)
    assert {"F", "G", "B"} <= validate(program).keys()
    assert validate(program)["G"] is program.pous[1]


@pytest.mark.parametrize(
    "source",
    [
        function() + function(),
        function(declarations="VAR x : INT; x : BOOL; END_VAR"),
        function(declarations="VAR f : INT; END_VAR"),
        function(result="UNKNOWN"),
        function(declarations="VAR x : UNKNOWN; END_VAR"),
        function(declarations="VAR_TEMP x : INT; END_VAR"),
        function(declarations="VAR_INPUT x : B; END_VAR") + block(),
        block(declarations="VAR_OUTPUT x : B; END_VAR"),
        function(declarations="VAR x : F; END_VAR"),
    ],
)
def test_invalid_declarations_fail_before_execution(source):
    reject(source)


@pytest.mark.parametrize(
    "body",
    [
        "missing := 1;",
        "F := missing;",
        "missing();",
        "F := 1 + TRUE;",
        "F := TRUE;",
        "F := NOT REAL#1.0;",
        "F := TRUE AND 1;",
        "F := TRUE < FALSE;",
        "IF 1 THEN F := 2; END_IF;",
        "WHILE 1 DO END_WHILE;",
        "CASE TRUE OF 1: F := 1; END_CASE;",
        "EXIT;",
        "CASE 1 OF 1: F := 1; 1: F := 2; END_CASE;",
        "F := 9223372036854775808;",
        "IF FALSE THEN missing := 1; END_IF;",
        "RETURN; missing();",
    ],
)
def test_bad_statements_in_uncalled_functions_are_rejected(body):
    reject(function(name="Main") + function(body))


@pytest.mark.parametrize(
    "declaration",
    [
        "VAR x : INT := 32768; END_VAR",
        "VAR x : UINT := -1; END_VAR",
        "VAR x : BOOL := 1; END_VAR",
        "VAR x : INT := TRUE; END_VAR",
        "VAR x : INT := 1 + TRUE; END_VAR",
        "VAR x : INT := F(); END_VAR",
        "VAR_IN_OUT x : INT := 1; END_VAR",
    ],
)
def test_initializer_must_be_a_typed_in_range_constant(declaration):
    reject(function(declarations=declaration))


def test_constant_initializers_and_mixed_integer_expressions_are_allowed():
    source = function(
        "F := x + y;",
        """
        VAR x : INT := -32768; y : UINT := +3; b : BOOL := NOT FALSE; END_VAR
    """,
    )
    assert validate(parse(source))["F"].name == "F"


def test_loop_scopes_and_integer_bounds():
    source = function(
        """
        FOR i := 1 TO 5 BY 1 DO
            IF TRUE THEN EXIT; END_IF;
        END_FOR;
        WHILE FALSE DO EXIT; END_WHILE;
    """,
        "VAR i : INT; END_VAR",
    )
    validate(parse(source))
    reject(function("FOR i := TRUE TO 3 DO END_FOR;", "VAR i : INT; END_VAR"))
    reject(function("FOR i := 1 TO 3 DO END_FOR;", "VAR i : BOOL; END_VAR"))
    reject(function("FOR i := 1 TO 3 BY FALSE DO END_FOR;", "VAR i : INT; END_VAR"))


CALLEE = function(
    "G := x;",
    """
    VAR_INPUT x : INT; END_VAR
    VAR_IN_OUT ref : UINT; END_VAR
    VAR_OUTPUT out : DINT; END_VAR
""",
    name="G",
)


@pytest.mark.parametrize(
    "call",
    [
        "G();",
        "G(x := 1);",
        "G(ref := u);",
        "G(x := TRUE, ref := u);",
        "G(x := 1, ref := 2);",
        "G(x := 1, ref := i);",
        "G(x := 1, ref := u, out => 1);",
        "G(x := 1, ref := u, out => i);",
        "G(x := 1, ref := u, out := d);",
        "G(x => i, ref := u);",
        "G(1, ref := u);",
        "G(1, u, d);",
        "G(x := 1, x := 2, ref := u);",
        "G(x := 1, ref := u, unknown := 3);",
    ],
)
def test_invalid_function_argument_binding(call):
    reject(function(call, "VAR i : INT; u : UINT; d : DINT; END_VAR") + CALLEE)


def test_function_arguments_and_exact_binding_types():
    source = (
        function("G(1, u); F := G(x := 2, ref := u, out => d);", "VAR u : UINT; d : DINT; END_VAR")
        + CALLEE
    )
    validate(parse(source))


@pytest.mark.parametrize(
    "body",
    [
        "b(1);",
        "b();",
        "b(x := TRUE, ref := u);",
        "F := b(ref := u);",
        "b.secret := 1;",
        "F := b.secret;",
        "F := b.ref;",
        "F := b.nope;",
    ],
)
def test_fb_calls_and_private_fields(body):
    source = function(body, "VAR b : B; u : UINT; END_VAR")
    source += block(
        declarations="""
        VAR_INPUT x : INT; END_VAR VAR_IN_OUT ref : UINT; END_VAR
        VAR_OUTPUT y : INT; END_VAR VAR secret : INT; END_VAR
    """
    )
    reject(source)


def test_fb_inputs_optional_and_public_fields_writable():
    source = function("b.x := 3; b(ref := u, y => F); F := b.y;", "VAR b : B; u : UINT; END_VAR")
    source += block(
        "y := x;",
        """
        VAR_INPUT x : INT; END_VAR VAR_IN_OUT ref : UINT; END_VAR
        VAR_OUTPUT y : INT; END_VAR
    """,
    )
    validate(parse(source))


@pytest.mark.parametrize(
    "source",
    [
        function("F := F();"),
        function("G();") + function("F();", name="G"),
        block(declarations="VAR self : B; END_VAR"),
        block(declarations="VAR c : C; END_VAR")
        + block(declarations="VAR b : B; END_VAR", name="C"),
        function("b();", "VAR b : B; END_VAR") + block("F();"),
        block("F();") + function("b();", "VAR b : B; END_VAR"),
    ],
)
def test_call_and_containment_cycles_are_rejected(source):
    reject(source)


def test_fb_name_does_not_reserve_a_function_result_variable():
    validate(parse(block("B := B + 1;", "VAR B : INT; END_VAR")))


def test_nested_fb_temporaries_are_allowed_and_function_instances_are_fresh_locals():
    source = function("local(); F := local.y;", "VAR local : Outer; END_VAR")
    source += block(
        "scratch(); retained(); y := scratch.y;",
        """
        VAR retained : Inner; END_VAR
        VAR_TEMP scratch : Inner; END_VAR
        VAR_OUTPUT y : INT; END_VAR
    """,
        name="Outer",
    )
    source += block("y := 1;", "VAR_OUTPUT y : INT; END_VAR", name="Inner")
    validate(parse(source))


@pytest.mark.parametrize(
    "body",
    [
        "F := b;",
        "b := b;",
        "Inner();",
        "b.x.nope := 1;",
        "F := b.inner.y;",
    ],
)
def test_fb_values_and_nested_private_instances_are_not_public(body):
    source = function(body, "VAR b : B; END_VAR")
    source += block(declarations="VAR_INPUT x : INT; END_VAR VAR inner : Inner; END_VAR")
    source += block(declarations="VAR_OUTPUT y : INT; END_VAR", name="Inner")
    reject(source)


def test_boolean_equality_and_order_independent_forward_reference():
    source = function("IF (TRUE = FALSE) OR (TRUE <> FALSE) THEN F := 1; END_IF;")
    validate(parse(source))


@pytest.mark.parametrize("section", ["VAR_INPUT", "VAR_OUTPUT", "VAR_IN_OUT"])
def test_all_public_fb_parameters_must_be_scalars(section):
    reject(block(declarations=f"{section} value : Inner; END_VAR") + block(name="Inner"))


def test_fb_instance_initializers_are_rejected():
    reject(function(declarations="VAR instance : B := 0; END_VAR") + block())


def test_signed64_minimum_literal_is_valid_as_an_integer_expression():
    program = parse(function("F := -9223372036854775808 < 0;", result="BOOL"))
    validate(program)


@pytest.mark.parametrize(
    "expression", ["9223372036854775808", "+9223372036854775808", "-9223372036854775809"]
)
def test_signed_literal_exception_does_not_admit_out_of_range_magnitudes(expression):
    reject(function(f"F := {expression} < 0;", result="BOOL"))


def test_signed64_minimum_initializer_reaches_the_declared_storage_range_check():
    with pytest.raises(ValidationError, match="outside DINT range"):
        validate(parse(function(declarations="VAR x : DINT := -9223372036854775808; END_VAR")))


def test_double_negation_of_minimum_is_validated_before_runtime_overflow_check():
    validate(parse(function("F := -(-9223372036854775808) < 0;", result="BOOL")))


def test_deep_expression_in_uncalled_pou_has_a_source_aware_validation_error():
    source = function(name="Main") + function("F := " + "+".join("1" for _ in range(1000)) + ";")
    program = parse(source, source="deep-expression.st")
    with pytest.raises(ValidationError, match="nesting") as error:
        validate(program)
    assert error.value.loc == program.pous[1].loc
    assert "deep-expression.st" in str(error.value)


@pytest.mark.parametrize("kind", ["call", "containment"])
def test_deep_acyclic_graph_has_a_source_aware_validation_error(kind):
    units = []
    for index in range(1000):
        if kind == "call":
            value = f"F{index + 1}()" if index < 999 else "1"
            units.append(function(f"F{index} := {value};", name=f"F{index}"))
        else:
            declaration = f"VAR child : B{index + 1}; END_VAR" if index < 999 else ""
            units.append(block(declarations=declaration, name=f"B{index}"))
    program = parse("\n".join(units), source="chain.st")
    with pytest.raises(ValidationError, match="nesting") as error:
        validate(program)
    assert error.value.loc == program.pous[0].loc
    assert "chain.st" in str(error.value)
