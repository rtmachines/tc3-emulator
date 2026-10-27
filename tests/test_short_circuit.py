"""BOOL short circuit operators preserve eager AND/OR behavior."""

import pytest

from tc_emulator import ExecutionError, Runtime, ValidationError


@pytest.mark.parametrize(
    "expression,expected", [("FALSE AND_THEN Hit()", False), ("TRUE OR_ELSE Hit()", True)]
)
def test_skipped_calls_have_no_effect(expression, expected):
    rt = Runtime.from_source(f"""
    VAR_GLOBAL hits : INT; END_VAR
    FUNCTION Hit : BOOL hits := hits + 1; Hit := TRUE; END_FUNCTION
    FUNCTION Test : BOOL Test := {expression}; END_FUNCTION
    """)
    assert rt.call("Test").value is expected
    assert rt.global_cell("GVL", "hits").value == 0


@pytest.mark.parametrize("operator", ["AND", "OR"])
def test_existing_boolean_operators_remain_eager(operator):
    rt = Runtime.from_source(
        f"FUNCTION Test : BOOL Test := FALSE {operator} (1 / 0 = 0); END_FUNCTION"
    )
    with pytest.raises(ExecutionError):
        rt.call("Test")


@pytest.mark.parametrize("expression", ["FALSE AND_THEN missing", "TRUE OR_ELSE 1", "1 AND_THEN 2"])
def test_skipped_operands_still_validate(expression):
    with pytest.raises(ValidationError):
        Runtime.from_source(f"FUNCTION Test : BOOL Test := {expression}; END_FUNCTION")


def test_constant_short_circuit_skips_arithmetic_fault():
    rt = Runtime.from_source("""
    FUNCTION Test : BOOL
    VAR CONSTANT safe : BOOL := FALSE AND_THEN (1 / 0 = 0); END_VAR
    Test := safe;
    END_FUNCTION
    """)
    assert rt.call("Test").value is False


def test_guards_and_left_to_right_evaluation():
    rt = Runtime.from_source("""
    VAR_GLOBAL calls : INT; END_VAR
    FUNCTION Mark : BOOL VAR_INPUT digit : INT; value : BOOL; END_VAR
    calls := calls * 10 + digit; Mark := value; END_FUNCTION
    FUNCTION Guard : BOOL VAR r : REFERENCE TO INT; END_VAR
    Guard := __ISVALIDREF(r) AND_THEN (r > 0);
    END_FUNCTION
    FUNCTION Ordered : BOOL
    Ordered := Mark(1, TRUE) AND_THEN Mark(2, FALSE) OR_ELSE Mark(3, TRUE) OR_ELSE Mark(4, TRUE);
    END_FUNCTION
    """)
    assert rt.call("Guard").value is False
    assert rt.call("Ordered").value is True
    assert rt.global_cell("GVL", "calls").value == 123


@pytest.mark.parametrize(
    "expression", ["TRUE OR_ELSE missing", "FALSE AND_THEN 1", "FALSE AND_THEN (TRUE + FALSE = 0)"]
)
def test_skipped_constant_branches_still_check_names_and_types(expression):
    with pytest.raises(ValidationError):
        Runtime.from_source(
            f"FUNCTION F : BOOL VAR CONSTANT c : BOOL := {expression}; END_VAR F := c; END_FUNCTION"
        )


def test_constant_bounds_can_short_circuit_before_arithmetic_fault():
    rt = Runtime.from_source("""
    FUNCTION F : BOOL
    VAR CONSTANT safe : BOOL := TRUE OR_ELSE (1 / 0 = 0); END_VAR
    F := safe;
    END_FUNCTION
    """)
    assert rt.call("F").value is True


def test_skipped_constant_minimum_integer_is_still_a_valid_literal():
    rt = Runtime.from_source("""
    FUNCTION F : BOOL VAR CONSTANT result : BOOL := FALSE AND_THEN (-9223372036854775808 = 0); END_VAR
    F := result; END_FUNCTION
    """)
    assert rt.call("F").value is False


def test_skipped_constant_projection_does_not_evaluate_its_index():
    rt = Runtime.from_source("""
    TYPE Item : STRUCT value : INT; END_STRUCT END_TYPE
    FUNCTION F : BOOL
    VAR CONSTANT values : ARRAY[1..1] OF Item := [(value := 3)];
    result : BOOL := FALSE AND_THEN (values[1 / 0].value = 3); END_VAR
    F := result; END_FUNCTION
    """)
    assert rt.call("F").value is False


def test_skipped_calls_still_participate_in_static_recursion_checks():
    with pytest.raises(ValidationError, match="Recursive call"):
        Runtime.from_source("FUNCTION F : BOOL F := FALSE AND_THEN F(); END_FUNCTION")
