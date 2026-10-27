"""Local constant expressions, safe array bounds and recursive read-only storage."""

import pytest

from tc_emulator import Runtime
from tc_emulator.errors import ParseError, ValidationError
from tc_emulator.parser import parse
from tc_emulator.syntax import VarDecl
from tc_emulator.types import ArrayType


def function(declarations, body="F := 0;", result="DINT"):
    return f"FUNCTION F : {result} {declarations} {body} END_FUNCTION"


def test_forward_constants_initialize_variables_bounds_and_case_labels():
    rt = Runtime.from_source(
        function(
            """
        VAR CONSTANT N : DINT := Base * 2; Base : DINT := 2; END_VAR
        VAR values : ARRAY[1..N] OF DINT := [N, Base + 1]; x : DINT := N; END_VAR
    """,
            """CASE x OF Base: F := -1; N: F := values[1] + values[2]; END_CASE;""",
        )
    )
    assert rt.call("F").value == 7


def test_literal_array_ast_and_old_variable_constructor_remain_compatible():
    pou = parse(function("VAR a : ARRAY[-1..2] OF INT; END_VAR")).pous[0]
    assert isinstance(pou.variables[0].type_name, ArrayType)
    old = VarDecl("X", "INT", "VAR", None, pou.loc)
    assert old.constant is False


def test_composite_constants_and_alias_copies_have_detached_storage():
    source = """TYPE S : STRUCT x : DINT; END_STRUCT; SA : S;
        A : ARRAY[1..2] OF SA; END_TYPE
    FUNCTION_BLOCK B
    VAR CONSTANT first : SA := (x := 3); original : A := [first, (x := 4)];
        copied : A := original; END_VAR
    VAR mutable : A := copied; END_VAR
    VAR_OUTPUT answer : DINT; END_VAR
    mutable[1].x := mutable[1].x + 1;
    answer := original[1].x * 100 + copied[1].x * 10 + mutable[1].x;
    END_FUNCTION_BLOCK"""
    fb = Runtime.from_source(source).instantiate("B")
    fb.call()
    assert fb.output("answer") == 334
    fb.call()
    assert fb.output("answer") == 335
    assert fb.inspect()["ORIGINAL"][0]["x"] == 3


def test_enum_constants_and_named_type_literal_arithmetic_bounds():
    rt = Runtime.from_source("""TYPE E : (A, B); V : ARRAY[1..1 + 1] OF DINT; END_TYPE
    FUNCTION F : DINT
    VAR CONSTANT chosen : E := E.B; END_VAR
    VAR data : V := [4, 5]; END_VAR
    CASE chosen OF E.A: F := 0; chosen: F := data[2]; END_CASE;
    END_FUNCTION""")
    assert rt.call("F").value == 5


@pytest.mark.parametrize(
    "declarations",
    [
        "VAR CONSTANT n : INT; END_VAR",
        "VAR CONSTANT n : INT := missing; END_VAR",
        "VAR CONSTANT n : INT := later; later : INT := n; END_VAR",
        "VAR x : INT := 1; END_VAR VAR CONSTANT n : INT := x; END_VAR",
        "VAR CONSTANT n : INT := F(); END_VAR",
        "VAR CONSTANT n : INT := 1; n : INT := 2; END_VAR",
        "VAR CONSTANT n : INT := TRUE; END_VAR",
        "VAR CONSTANT n : INT := 32767 + 1; END_VAR",
        "VAR CONSTANT n : INT := 1 / 0; END_VAR",
        "VAR CONSTANT n : INT := -(-9223372036854775808); END_VAR",
        "VAR CONSTANT n : DINT := 1000001; END_VAR VAR a : ARRAY[1..n] OF INT; END_VAR",
        "VAR CONSTANT n : REAL := REAL#2; END_VAR VAR a : ARRAY[1..n] OF INT; END_VAR",
        "VAR a : ARRAY[1..missing] OF INT; END_VAR",
        "VAR CONSTANT n : BOOL := TRUE; END_VAR VAR a : ARRAY[1..n] OF INT; END_VAR",
        "VAR_CONSTANT n : INT := 1; END_VAR",
    ],
)
def test_invalid_constants_and_bounds_rejected(declarations):
    with pytest.raises((ParseError, ValidationError)):
        Runtime.from_source(function(declarations))


@pytest.mark.parametrize("section", ["VAR_INPUT", "VAR_OUTPUT", "VAR_IN_OUT", "VAR_TEMP"])
def test_constant_qualifier_only_local_var(section):
    with pytest.raises((ParseError, ValidationError)):
        Runtime.from_source(
            f"FUNCTION_BLOCK B {section} CONSTANT n : INT := 1; END_VAR END_FUNCTION_BLOCK"
        )


def test_constant_fb_instance_and_top_level_local_bound_rejected():
    with pytest.raises(ValidationError):
        Runtime.from_source(
            "FUNCTION_BLOCK B END_FUNCTION_BLOCK " + function("VAR CONSTANT n : B := 0; END_VAR")
        )
    with pytest.raises(ValidationError):
        Runtime.from_source(
            "TYPE A : ARRAY[1..N] OF INT; END_TYPE "
            + function("VAR CONSTANT N : INT := 2; END_VAR")
        )


@pytest.mark.parametrize(
    "body",
    [
        "n := 2;",
        "s.x := 2;",
        "a[1].x := 2;",
        "FOR n := 1 TO 2 DO END_FOR;",
        "FOR a[1].x := 1 TO 2 DO END_FOR;",
        "Change(v := n);",
        "Change(v := s.x);",
        "Change(v := a[1].x);",
        "Output(v => n);",
        "Output(v => s.x);",
        "Output(v => a[1].x);",
    ],
)
def test_constant_writes_rejected_at_every_binding_path(body):
    source = """TYPE S : STRUCT x : DINT; END_STRUCT; END_TYPE
    FUNCTION Change : DINT VAR_IN_OUT v : DINT; END_VAR END_FUNCTION
    FUNCTION Output : DINT VAR_OUTPUT v : DINT; END_VAR END_FUNCTION
    """ + function(
        """VAR CONSTANT n : DINT := 1; s : S := (x := 1);
        a : ARRAY[1..1] OF S := [s]; END_VAR""",
        body,
    )
    with pytest.raises(ValidationError, match="[Cc]onstant|[Ww]rit"):
        Runtime.from_source(source)


@pytest.mark.parametrize(
    "expression, result, expected",
    [
        ("REAL#16777216 + REAL#1", "REAL", 16777216.0),
        ("T#2s - T#500ms", "TIME", 1500),
        ("NOT FALSE AND (2 < 3)", "BOOL", True),
        ("-7 MOD 3", "DINT", -1),
    ],
)
def test_constant_operations_follow_runtime_precision_and_categories(expression, result, expected):
    rt = Runtime.from_source(
        function(f"VAR CONSTANT n : {result} := {expression}; END_VAR", "F := n;", result)
    )
    assert rt.call("F").value == expected


@pytest.mark.parametrize("expression", ["T#1s + 1", "T#1s * T#2s", "-T#1s", "T#1ms - T#2ms"])
def test_invalid_time_constant_operations(expression):
    with pytest.raises(ValidationError):
        Runtime.from_source(function(f"VAR CONSTANT n : TIME := {expression}; END_VAR"))


def test_scalar_alias_bound_and_forward_composite_copy():
    source = """TYPE Count : DINT; S : STRUCT x : INT; END_STRUCT; END_TYPE
    FUNCTION F : INT
    VAR CONSTANT n : Count := 1 + 1; copied : S := original; original : S := (x := 6); END_VAR
    VAR a : ARRAY[0..n - 1] OF S := [copied, original]; END_VAR
    F := a[0].x + a[1].x;
    END_FUNCTION"""
    assert Runtime.from_source(source).call("F").value == 12


def test_constants_copy_to_inputs_and_detached_inspection():
    source = """TYPE S : STRUCT x : DINT; END_STRUCT; END_TYPE
    FUNCTION Change : DINT VAR_INPUT v : S; END_VAR v.x := 9; Change := v.x; END_FUNCTION
    FUNCTION_BLOCK B
    VAR CONSTANT s : S := (x := 3); END_VAR
    VAR_OUTPUT answer : DINT; END_VAR
    answer := Change(s) + s.x;
    END_FUNCTION_BLOCK"""
    fb = Runtime.from_source(source).instantiate("B")
    fb.call()
    assert fb.output("answer") == 12
    view = fb.inspect()
    view["S"] = {"x": 100}
    fb.call()
    assert fb.output("answer") == 12


@pytest.mark.parametrize(
    "expression, expected",
    [
        ("REAL#1.00000005960464477539062500000000001 + REAL#0", 1.0000001192092896),
        ("(1.5 + REAL#0.5) * REAL#2", 4.0),
        ("-7 / 3", -2.0),
    ],
)
def test_initializer_precision_and_integer_division(expression, expected):
    rt = Runtime.from_source(
        function(f"VAR n : LREAL := {expression}; END_VAR", "F := n;", "LREAL")
    )
    assert rt.call("F").value == expected


def test_aggregate_leaf_budget_applies_after_constant_bound_resolution():
    source = """TYPE Big : ARRAY[1..1000] OF DINT; END_TYPE
    FUNCTION F : DINT VAR CONSTANT n : DINT := 1001; END_VAR
    VAR a : ARRAY[1..n] OF Big; END_VAR END_FUNCTION"""
    with pytest.raises(ValidationError, match="1000000"):
        Runtime.from_source(source)


@pytest.mark.parametrize(
    "declarations, body",
    [
        ("VAR CONSTANT a : INT := b; b : INT := a; END_VAR", ""),
        ("VAR CONSTANT n : INT := 2; END_VAR", "CASE n OF n: RETURN; 2: RETURN; END_CASE;"),
        ("VAR n : INT := 2; END_VAR", "CASE n OF n: RETURN; END_CASE;"),
    ],
)
def test_cycles_and_duplicate_or_mutable_case_labels(declarations, body):
    with pytest.raises(ValidationError):
        Runtime.from_source(function(declarations, body))


@pytest.mark.parametrize(
    "initial, match", [("later", "cycle"), ("missing", "constant"), ("F()", "[Cc]all|constant")]
)
def test_invalid_constant_dependencies_rejected_before_named_aggregate_defaults(initial, match):
    source = (
        """TYPE Big : ARRAY[1..1000000] OF INT := [TRUE]; END_TYPE
    FUNCTION F : DINT VAR CONSTANT early : DINT := """
        + initial
        + "; later : DINT := early; END_VAR END_FUNCTION"
    )
    with pytest.raises(ValidationError, match=match):
        Runtime.from_source(source)


def test_array_bounds_resolve_scalar_constants_projected_from_composite_constants():
    source = """TYPE S : STRUCT width : DINT := 2; END_STRUCT;
    DefaultS : S := (width := 3); Counts : ARRAY[-1..0] OF DINT := [2, 3]; END_TYPE
    FUNCTION F : DINT
    VAR CONSTANT n : DINT := config.width + values[-1];
        config : DefaultS := (); values : Counts := [2, 4];
        copied : DefaultS := config; m : DINT := copied.width; END_VAR
    VAR a : ARRAY[1..n] OF DINT := [5(1)]; b : ARRAY[1..m] OF DINT; END_VAR
    F := a[5] + b[3];
    END_FUNCTION"""
    assert Runtime.from_source(source).call("F").value == 1


def test_projected_bounds_remain_lazy_until_aggregate_budget_preflight():
    source = """TYPE Huge : STRUCT
    width : DINT := 2; data : ARRAY[1..1000000] OF DINT := [TRUE]; END_STRUCT; END_TYPE
    FUNCTION F : DINT VAR CONSTANT config : Huge := (); n : DINT := config.width; END_VAR
    VAR a : ARRAY[1..n] OF Huge; END_VAR END_FUNCTION"""
    with pytest.raises(ValidationError, match="1000000.*limit"):
        Runtime.from_source(source)


def test_projection_dependencies_reject_cycles():
    source = """TYPE S : STRUCT width : DINT; END_STRUCT; END_TYPE
    FUNCTION F : DINT VAR CONSTANT config : S := (width := n); n : DINT := config.width; END_VAR
    VAR a : ARRAY[1..n] OF INT; END_VAR END_FUNCTION"""
    with pytest.raises(ValidationError, match="cycle"):
        Runtime.from_source(source)


def test_lazy_projection_supports_multidimensional_repetitions_and_nested_members():
    source = """TYPE S : STRUCT n : INT := 2; END_STRUCT;
        Row : ARRAY[1..2] OF S; AliasRow : Row := [(n := 3)];
        Container : STRUCT rows : ARRAY[-1..0,1..2] OF AliasRow; END_STRUCT; END_TYPE
    FUNCTION F : INT VAR CONSTANT c : Container := (); n : INT := c.rows[-1,1][1].n; END_VAR
    VAR a : ARRAY[1..n] OF INT := [3(7)]; END_VAR F := a[3]; END_FUNCTION"""
    assert Runtime.from_source(source).call("F").value == 7


def test_cycle_through_projected_array_type_bounds_is_rejected():
    source = function("""VAR CONSTANT values : ARRAY[1..n] OF INT := [2];
        n : INT := values[1]; END_VAR""")
    with pytest.raises(ValidationError, match="cycle"):
        Runtime.from_source(source)
