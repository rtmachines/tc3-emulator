"""Resolution and strict source typing of declaration-only user types."""

import pytest

from tc_emulator.errors import ValidationError
from tc_emulator.parser import parse
from tc_emulator.validation import validate


def function(body="", declarations="", result="INT", name="F"):
    return f"\nFUNCTION {name} : {result}\n{declarations}\n{body}\nEND_FUNCTION\n"


def reject(source, match=None):
    with pytest.raises(ValidationError, match=match) as error:
        validate(parse(source, source="user-types.st"))
    assert error.value.loc is not None


def test_registry_keeps_builtin_pous_and_prepares_checked_scalar_defaults():
    registry = validate(parse(function(declarations="VAR x : REAL := 1; END_VAR")))
    assert hasattr(registry, "types")
    assert registry["TON"].kind == "FUNCTION_BLOCK"
    declaration = registry["F"].variables[0]
    assert declaration.default == 1.0
    assert type(declaration.default) is float
    assert declaration.initial.value == 1


def test_forward_alias_struct_enum_defaults_and_nested_initializers():
    source = """TYPE
    ConfigAlias : Config;
    Config : STRUCT
        state : State;
        wait : TIME := T#2s;
        values : ARRAY[1..2] OF Number := [4];
    END_STRUCT;
    Number : INT := 3;
    State : (Busy := 5, Idle := 0, Done) INT;
    END_TYPE
    """ + function(declarations="VAR x : ConfigAlias := (state := State.Done); END_VAR")
    registry = validate(parse(source))
    value = registry["F"].variables[0].default
    assert value["STATE"].name == "DONE"
    assert value["STATE"].value == 1
    assert value["WAIT"] == 2000
    assert value["VALUES"] == (4, 3)
    assert registry.types["STATE"].default_member == "IDLE"


@pytest.mark.parametrize(
    "types",
    [
        "A : B; B : A;",
        "A : STRUCT next : A; END_STRUCT;",
        "A : ARRAY[1..2] OF B; B : A;",
        "A : Missing;",
        "A : TON;",
        "INT : BOOL;",
        "TON : INT;",
        "A : INT; A : DINT;",
        "A : STRUCT x : INT; X : BOOL; END_STRUCT;",
        "A : (X, X);",
        "A : (X := 0, Y := 0);",
        "A : (X := 32768);",
        "A : (X) TIME;",
    ],
)
def test_invalid_type_graphs_and_definitions_are_rejected(types):
    reject(f"TYPE {types} END_TYPE" + function())


def test_pou_type_namespace_collision_is_rejected():
    reject("TYPE F : INT; END_TYPE" + function())


def test_aggregate_limit_and_named_resolution_depth_are_checked():
    reject(
        "TYPE Leaf : STRUCT a,b : INT; END_STRUCT; "
        "Huge : ARRAY[1..500001] OF Leaf; END_TYPE" + function(),
        "1000000|limit",
    )
    aliases = " ".join(f"A{i} : A{i + 1};" for i in range(65)) + " A65 : INT;"
    reject(f"TYPE {aliases} END_TYPE" + function(), "nesting|64|depth")


@pytest.mark.parametrize(
    "declaration",
    [
        "x : Config := (missing := 1);",
        "x : Config := (wait := T#0ms, WAIT := T#1s);",
        "x : Config := (wait := 0);",
        "x : Config := (state := 0);",
        "x : Config := (state := Other.Idle);",
        "x : Config := (state := Idle);",
        "x : Config := (wait := T#1s + 1);",
        "x : Config := (values := [1,2,3]);",
        "x : Config := (values := [T#1s]);",
        "x : Config := (values := [1+TRUE]);",
        "x : Config := 1;",
        "x : INT := (wait := 1);",
    ],
)
def test_nested_initializers_validate_each_source_and_destination(declaration):
    source = """TYPE State : (Idle, Run); Other : (Idle, Run);
    Config : STRUCT wait : TIME; state : State; values : ARRAY[1..2] OF INT;
    END_STRUCT; END_TYPE"""
    reject(source + function(declarations=f"VAR {declaration} END_VAR"))


@pytest.mark.parametrize("initial", ["Run", "State.Run"])
def test_enum_type_defaults_accept_short_and_qualified_members(initial):
    registry = validate(parse(f"TYPE State : (Idle, Run) := {initial}; END_TYPE" + function()))
    assert registry.types["STATE"].default_member == "RUN"


@pytest.mark.parametrize(
    "body",
    [
        "a := b;",
        "a := 0;",
        "F := a;",
        "a := a + a;",
        "a := -a;",
        "IF a = b THEN END_IF;",
        "IF a < 1 THEN END_IF;",
        "State.Run := a;",
        "CASE a OF 0: END_CASE;",
        "CASE a OF Other.Idle: END_CASE;",
        "CASE 1 OF State.Idle: END_CASE;",
        "CASE a OF State.Idle: State.Idle: END_CASE;",
    ],
)
def test_enums_reject_integer_mixing_other_enums_and_writable_constants(body):
    reject(
        "TYPE State : (Idle, Run); Other : (Idle, Run); END_TYPE"
        + function(body, "VAR a : State; b : Other; END_VAR")
    )


def test_enum_comparisons_case_and_storage_name_shadowing_are_valid():
    source = "TYPE State : (Idle, Run); S : STRUCT Run : INT; END_STRUCT; END_TYPE"
    source += function(
        "a := State.Run; IF a < State.Run OR a = State.Idle THEN F := 1; END_IF; "
        "CASE a OF State.Idle: F := 2; State.Run: F := 3; END_CASE;",
        "VAR a : State; END_VAR",
    )
    source += function("State.Run := 2; G := State.Run;", "VAR State : S; END_VAR", name="G")
    validate(parse(source))


@pytest.mark.parametrize("section", ["VAR_INPUT", "VAR_IN_OUT", "VAR_OUTPUT"])
def test_composite_parameters_use_nominal_structs_and_transparent_aliases(section):
    mode = "=>" if section == "VAR_OUTPUT" else ":="
    prefix = "TYPE S : STRUCT x : INT; END_STRUCT; A : S; "
    prefix += "Other : STRUCT x : INT; END_STRUCT; END_TYPE"
    callee = function(declarations=f"{section} x : S; END_VAR", name="G")
    validate(parse(prefix + function(f"G(x {mode} item);", "VAR item : A; END_VAR") + callee))
    reject(prefix + function(f"G(x {mode} item);", "VAR item : Other; END_VAR") + callee)


@pytest.mark.parametrize("section", ["VAR_IN_OUT", "VAR_OUTPUT"])
def test_enum_constants_cannot_bind_writable_parameters(section):
    mode = "=>" if section == "VAR_OUTPUT" else ":="
    reject(
        "TYPE State : (Idle, Run); END_TYPE"
        + function(f"G(x {mode} State.Run);")
        + function(declarations=f"{section} x : State; END_VAR", name="G"),
        "writable|constant",
    )


def test_alternating_fields_and_indices_and_alias_array_elements_resolve():
    source = """TYPE Row : ARRAY[1..2] OF INT; RowAlias : Row;
    Item : STRUCT rows : ARRAY[1..2] OF RowAlias; END_STRUCT;
    Items : ARRAY[1..2] OF Item; END_TYPE"""
    source += function(
        "items[1].rows[2][1] := 4; F := items[1].rows[2][1];", "VAR items : Items; END_VAR"
    )
    validate(parse(source))


def test_oversized_type_graph_is_rejected_before_dependency_defaults_are_evaluated():
    source = """TYPE
    Leaf : STRUCT values : ARRAY[1..1000000] OF INT := [TRUE]; END_STRUCT;
    Huge : ARRAY[1..2] OF Leaf;
    END_TYPE""" + function()
    reject(source, "1000000.*limit")


def test_empty_structure_cannot_evade_the_aggregate_memory_limit():
    reject("TYPE Empty : STRUCT END_STRUCT; END_TYPE" + function(), "field|empty")


@pytest.mark.parametrize("reverse", [False, True])
def test_exact_named_depth_limit_allows_64_and_rejects_65_even_with_cached_dependencies(reverse):
    definitions = [f"A{i} : A{i + 1};" for i in range(63)] + ["A63 : INT;"]
    if reverse:
        definitions.reverse()
    validate(parse("TYPE " + " ".join(definitions) + " END_TYPE" + function()))
    reject("TYPE TooDeep : A0; " + " ".join(definitions) + " END_TYPE" + function(), "64|depth")


def test_alias_defaults_and_nested_array_initializers_preserve_declared_element_defaults():
    source = """TYPE
    Number : INT := 7;
    Row : ARRAY[1..2] OF Number := [4];
    Item : STRUCT rows : ARRAY[1..2] OF Row; END_STRUCT;
    Config : Item := (rows := [[1]]);
    END_TYPE""" + function(declarations="VAR x : Config := (rows := [[]]); END_VAR")
    registry = validate(parse(source))
    assert registry.types["CONFIG"].default["ROWS"] == ((1, 7), (4, 7))
    assert registry["F"].variables[0].default["ROWS"] == ((7, 7), (4, 7))


@pytest.mark.parametrize("initializer", ["Run", "Other.Run", "0"])
def test_enum_type_default_must_belong_to_its_own_enum(initializer):
    # Short members are legal only for the enum being declared, not an alias.
    if initializer == "Run":
        source = "TYPE State : (Idle, Run); Alias : State := Run; END_TYPE"
    else:
        source = f"TYPE Other : (Idle, Run); State : (Idle, Run) := {initializer}; END_TYPE"
    reject(source + function())


def test_storage_shadowing_prevents_enum_constants_inside_initializers_and_case_labels():
    prefix = "TYPE State : (Idle, Run); S : STRUCT Run : INT; END_STRUCT; END_TYPE"
    reject(prefix + function(declarations="VAR State : S; x : INT := State.Run; END_VAR"))
    reject(prefix + function("CASE x OF State.Run: END_CASE;", "VAR State : S; x : State; END_VAR"))


def test_composite_result_and_member_outputs_support_transparent_aliases():
    source = "TYPE S : STRUCT x : INT; END_STRUCT; A : S; END_TYPE"
    source += function(
        "F := G(item); G(ref := item.x, value => item.x);", "VAR item : A; END_VAR", result="S"
    )
    # Keep required input and reference parameters on separate callees.
    source = source.replace("G(ref :=", "H(ref :=")
    source += function("G := x;", "VAR_INPUT x : A; END_VAR", result="S", name="G")
    source += function(
        "ref := 4; value := 5;",
        "VAR_IN_OUT ref : INT; END_VAR VAR_OUTPUT value : INT; END_VAR",
        name="H",
    )
    validate(parse(source))


def test_inline_pou_aggregate_is_checked_before_named_type_defaults():
    source = """TYPE Leaf : STRUCT
    values : ARRAY[1..1000000] OF INT := [TRUE];
    END_STRUCT; END_TYPE"""
    reject(source + function(declarations="VAR x : ARRAY[1..2] OF Leaf; END_VAR"), "1000000.*limit")
