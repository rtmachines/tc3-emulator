"""Whole-project validation for shared globals and persistent PROGRAM objects."""

from dataclasses import replace

import pytest

from tc_emulator.errors import ValidationError
from tc_emulator.parser import parse
from tc_emulator.syntax import GlobalVarList, Program
from tc_emulator.types import canonical_type
from tc_emulator.validation import validate


def project(*sources, globals=(), programs=()):
    """Build canonical AST inputs without depending on the concurrent parser change."""
    pous, types, gvls = [], [], []
    for source in sources:
        parsed = parse(source)
        pous.extend(parsed.pous)
        types.extend(parsed.types)
    for name, declarations, qualified in globals:
        parsed = parse(f"FUNCTION_BLOCK {name} {declarations} END_FUNCTION_BLOCK").pous[0]
        gvls.append(
            GlobalVarList(
                name=name,
                variables=tuple(replace(v, section="VAR_GLOBAL") for v in parsed.variables),
                loc=parsed.loc,
                qualified_only=qualified,
            )
        )
    for source in programs:
        parsed = parse(source).pous[0]
        pous.append(replace(parsed, kind="PROGRAM"))
    return Program(tuple(pous), tuple(types), tuple(gvls))


def test_globals_resolve_across_functions_and_normalize_defaults():
    registry = validate(
        project(
            "FUNCTION F : INT F := Data.x + x; END_FUNCTION",
            globals=(("DATA", "VAR x : INT := 4; END_VAR", False),),
        )
    )
    assert registry.global_lists == {"DATA": False}
    assert registry.global_variables == {"X": ("DATA",)}
    assert registry["DATA"].kind == "GVL"
    assert registry["DATA"].variables[0].default == 4
    assert registry["DATA"].variables[0].section == "VAR"


def test_cross_list_constants_and_type_bounds_resolve_independent_of_order():
    registry = validate(
        project(
            "TYPE Row : ARRAY[1..A.n] OF STRING(B.n); END_TYPE",
            globals=(
                ("A", "VAR CONSTANT n : INT := B.n + 1; END_VAR VAR row : Row; END_VAR", False),
                ("B", "VAR CONSTANT n : INT := 2; END_VAR", True),
            ),
        )
    )
    assert registry["A"].variables[0].default == 3
    row = canonical_type(registry.types["ROW"])
    assert row.bounds == ((1, 3),)
    assert row.element_type.length == 2


@pytest.mark.parametrize("body", ["F := x;", "x := 1;"])
def test_ambiguous_unqualified_globals_reject(body):
    with pytest.raises(ValidationError, match="[Aa]mbiguous"):
        validate(
            project(
                f"FUNCTION F : INT {body} END_FUNCTION",
                globals=(
                    ("A", "VAR x : INT; END_VAR", False),
                    ("B", "VAR x : INT; END_VAR", False),
                ),
            )
        )


def test_local_names_shadow_global_namespaces_and_ambiguous_variables():
    validate(
        project(
            "TYPE S : STRUCT x : INT; END_STRUCT; END_TYPE FUNCTION F : INT VAR A : S; x : INT; END_VAR A.x := x; F := A.x; END_FUNCTION",
            globals=(("A", "VAR x : INT; END_VAR", False), ("B", "VAR x : INT; END_VAR", False)),
        )
    )


@pytest.mark.parametrize("initial", ["n", "other"])
def test_qualified_only_list_needs_explicit_qualification_even_in_initializer(initial):
    with pytest.raises(ValidationError, match="[Cc]onstant"):
        validate(
            project(
                globals=(("A", f"VAR CONSTANT n : INT := 2; m : INT := {initial}; END_VAR", True),)
            )
        )


def test_cross_list_constant_cycle_precedes_allocating_bad_type_defaults():
    with pytest.raises(ValidationError, match="cycle"):
        validate(
            project(
                "TYPE Big : ARRAY[1..1000000] OF INT := [TRUE]; END_TYPE",
                globals=(
                    ("A", "VAR CONSTANT x : INT := B.y; END_VAR", False),
                    ("B", "VAR CONSTANT y : INT := A.x; END_VAR", False),
                ),
            )
        )


@pytest.mark.parametrize(
    "body", ["A.s.x := 1;", "A.a[1] := 1;", "G(v := A.s.x);", "B(y => A.a[1]);"]
)
def test_global_constants_are_readonly_on_nested_writes_and_bindings(body):
    with pytest.raises(ValidationError, match="[Cc]onstant"):
        validate(
            project(
                "TYPE S : STRUCT x : INT; END_STRUCT; END_TYPE FUNCTION G : INT VAR_IN_OUT v : INT; END_VAR END_FUNCTION ",
                globals=(
                    (
                        "A",
                        "VAR CONSTANT s : S := (); a : ARRAY[1..1] OF INT := [0]; END_VAR",
                        False,
                    ),
                ),
                programs=(
                    f"FUNCTION_BLOCK Main {body} END_FUNCTION_BLOCK",
                    "FUNCTION_BLOCK B VAR_OUTPUT y : INT; END_VAR END_FUNCTION_BLOCK",
                )
                if body.startswith("B(")
                else (f"FUNCTION_BLOCK Main {body} END_FUNCTION_BLOCK",),
            )
        )


def test_program_state_fields_and_calls_are_valid():
    registry = validate(
        project(
            programs=(
                "FUNCTION_BLOCK Main VAR z : INT; END_VAR Child(x := 4, y => z); z := Child.private; END_FUNCTION_BLOCK",
                "FUNCTION_BLOCK Child VAR_INPUT x : INT; END_VAR VAR_OUTPUT y : INT; END_VAR VAR private : INT; END_VAR VAR_TEMP scratch : INT; END_VAR y := x; END_FUNCTION_BLOCK",
            )
        )
    )
    assert registry["MAIN"].kind == "PROGRAM"


@pytest.mark.parametrize(
    "caller",
    ["FUNCTION F : INT Child(); END_FUNCTION", "FUNCTION F : INT F := Child.x; END_FUNCTION"],
)
def test_function_cannot_call_program_but_can_read_state(caller):
    source = project(
        caller, programs=("FUNCTION_BLOCK Child VAR x : INT; END_VAR END_FUNCTION_BLOCK",)
    )
    if "Child()" in caller:
        with pytest.raises(ValidationError, match="FUNCTION.*PROGRAM"):
            validate(source)
    else:
        validate(source)


@pytest.mark.parametrize(
    "body", ["Child(1);", "x := Child();", "x := Child.scratch;", "Child := Child;", "Child();"]
)
def test_invalid_program_usage_and_recursive_calls_reject(body):
    with pytest.raises(ValidationError):
        validate(
            project(
                programs=(
                    f"FUNCTION_BLOCK Child VAR x : INT; END_VAR VAR_TEMP scratch : INT; END_VAR {body} END_FUNCTION_BLOCK",
                )
            )
        )


def test_shared_global_fb_calls_and_public_fields_validate():
    validate(
        project(
            "FUNCTION F : BOOL A.timer(IN := TRUE, PT := T#1s); F := timer.Q; END_FUNCTION",
            globals=(("A", "VAR timer : TON; END_VAR", False),),
        )
    )


def test_cross_list_array_constant_copy_uses_resolved_bounds_in_either_order():
    first = parse("VAR_GLOBAL CONSTANT a : ARRAY[1..B.n] OF INT := B.b; END_VAR", gvl_name="A")
    second = parse(
        "VAR_GLOBAL CONSTANT n : INT := 2; b : ARRAY[1..n] OF INT := [3, 4]; END_VAR", gvl_name="B"
    )
    for lists in ((first.gvls[0], second.gvls[0]), (second.gvls[0], first.gvls[0])):
        registry = validate(Program((), (), lists))
        assert registry["A"].variables[0].default == (3, 4)


def test_cross_list_projected_bounds_preflight_precedes_huge_default_allocation():
    source = parse("""TYPE Huge : STRUCT width : INT := 2;
        data : ARRAY[1..1000000] OF INT := [TRUE]; END_STRUCT; END_TYPE
        VAR_GLOBAL CONSTANT config : Huge := (); END_VAR
        PROGRAM Main VAR a : ARRAY[1..GVL.config.width] OF Huge; END_VAR END_PROGRAM""")
    with pytest.raises(ValidationError, match="1000000.*limit"):
        validate(source)


@pytest.mark.parametrize(
    "declaration",
    [
        "VAR_GLOBAL x : INT; END_VAR VAR_GLOBAL CONSTANT y : INT := x; END_VAR",
        "VAR_GLOBAL CONSTANT y : INT := F(); END_VAR FUNCTION F : INT END_FUNCTION",
        "VAR_GLOBAL CONSTANT timer : TON := 1; END_VAR",
        "PROGRAM Main VAR_IN_OUT x : INT; END_VAR END_PROGRAM",
        "PROGRAM Main END_PROGRAM PROGRAM Other VAR instance : Main; END_VAR END_PROGRAM",
        "VAR_GLOBAL x : INT; END_VAR PROGRAM GVL END_PROGRAM",
        "VAR_GLOBAL x : INT; END_VAR TYPE GVL : INT; END_TYPE",
    ],
)
def test_invalid_global_and_program_declarations_fail(declaration):
    # Parser also rejects invalid PROGRAM sections: construct the AST for that case.
    if "VAR_IN_OUT" in declaration:
        source = project(programs=(declaration.replace("PROGRAM", "FUNCTION_BLOCK"),))
    else:
        source = parse(declaration)
    with pytest.raises(ValidationError):
        validate(source)


@pytest.mark.parametrize("body", ["Child.c := 2;", "Child.c.x := 2;", "Child.c[1] := 2;"])
def test_program_constant_descendants_are_readonly(body):
    declaration = (
        "INT := 1"
        if body == "Child.c := 2;"
        else "S := ()"
        if ".x" in body
        else "ARRAY[1..1] OF INT := [1]"
    )
    with pytest.raises(ValidationError, match="[Cc]onstant"):
        validate(
            parse(
                f"TYPE S : STRUCT x : INT; END_STRUCT; END_TYPE PROGRAM Child VAR CONSTANT c : {declaration}; END_VAR END_PROGRAM PROGRAM Main {body} END_PROGRAM"
            )
        )


def test_globals_shadow_named_function_call_targets():
    registry = validate(
        parse(
            "VAR_GLOBAL work : TON; END_VAR FUNCTION work : BOOL END_FUNCTION PROGRAM Main work(IN := TRUE, PT := T#1s); END_PROGRAM"
        )
    )
    assert registry["GVL"].variables[0].type_name == "TON"


def test_global_constants_supply_symbolic_bit_selectors():
    registry = validate(
        parse(
            "VAR_GLOBAL CONSTANT bit : INT := 2; END_VAR PROGRAM Main VAR x : BYTE; END_VAR x.bit := TRUE; END_PROGRAM"
        )
    )
    assert len(registry.bit_accesses) == 1


def test_qualified_only_own_initializer_accepts_explicit_constant_reference():
    registry = validate(
        parse(
            "{attribute 'qualified_only'} VAR_GLOBAL CONSTANT n : INT := 2; m : INT := GVL.n + 1; END_VAR"
        )
    )
    assert registry["GVL"].variables[1].default == 3


def test_global_variable_root_shadows_enum_type_for_nested_field_access():
    registry = validate(
        parse(
            "TYPE E : (A, B); S : STRUCT A : INT; END_STRUCT; END_TYPE VAR_GLOBAL E : S; END_VAR FUNCTION F : INT F := E.A; END_FUNCTION"
        )
    )
    assert registry["F"].return_type == "INT"


def test_cross_list_cycle_through_type_field_default_precedes_other_defaults():
    source = parse("""TYPE Big : ARRAY[1..1000000] OF INT := [TRUE];
        S : STRUCT width : INT := GVL.n; END_STRUCT; END_TYPE
        VAR_GLOBAL CONSTANT config : S := (); n : INT := GVL.config.width; END_VAR""")
    with pytest.raises(ValidationError, match="cycle"):
        validate(source)


def test_global_constant_array_projection_keeps_caller_index_scope():
    registry = validate(
        parse("""VAR_GLOBAL CONSTANT items : ARRAY[1..2] OF INT := [3, 5]; END_VAR
        PROGRAM Main VAR CONSTANT pos : INT := 2; END_VAR
        VAR values : ARRAY[1..GVL.items[pos]] OF INT; END_VAR END_PROGRAM""")
    )
    assert registry["MAIN"].variables[1].type_name.bounds == ((1, 5),)


def test_type_default_projection_keeps_global_scope_despite_local_shadow():
    registry = validate(
        parse("""VAR_GLOBAL CONSTANT n : INT := 2; END_VAR
        TYPE S : STRUCT width : INT := n; END_STRUCT; END_TYPE
        PROGRAM Main VAR CONSTANT n : INT := 5; config : S := (); END_VAR
        VAR values : ARRAY[1..config.width] OF INT; END_VAR END_PROGRAM""")
    )
    assert registry["MAIN"].variables[2].type_name.bounds == ((1, 2),)
