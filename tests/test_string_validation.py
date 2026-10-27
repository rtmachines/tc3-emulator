"""Static string storage, constant-capacity and compatibility contracts."""

import pytest

from tc_emulator.errors import ValidationError
from tc_emulator.parser import parse
from tc_emulator.syntax import Assign, Binary, Literal, Location, Pou, Program, Reference
from tc_emulator.validation import validate


def function(declarations="", body="", result="INT", name="F"):
    return f"FUNCTION {name} : {result} {declarations} {body} END_FUNCTION\n"


def prepared(source):
    return validate(parse(source, source="strings.st"))


def reject(source, match=None):
    with pytest.raises(ValidationError, match=match) as error:
        prepared(source)
    assert error.value.loc is not None


def test_constructed_untyped_string_literals_cannot_enter_integer_arithmetic():
    loc = Location("constructed.st", 1, 1)
    expression = Binary("+", Literal("a", loc), Literal("b", loc), loc)
    assignment = Assign(Reference(("F",), loc), expression, loc)
    program = Program((Pou("FUNCTION", "F", "INT", (), (assignment,), loc),))
    with pytest.raises(ValidationError):
        validate(program)


@pytest.mark.parametrize("operator", ["=", "<>", "<", "<=", ">", ">="])
def test_comparisons_accept_different_string_capacities(operator):
    prepared(function("VAR a : STRING(2); b : STRING(9); END_VAR", f"F := a {operator} b;", "BOOL"))


def test_scalar_copies_and_output_bindings_allow_different_capacities():
    source = function(
        "VAR a : STRING(2); b : STRING(9); END_VAR",
        "a := b; b := a; a := Copy(x := b, result => a);",
        "STRING(3)",
    ) + function(
        "VAR_INPUT x : STRING(4); END_VAR VAR_OUTPUT result : STRING(8); END_VAR",
        "Copy := x; result := x;",
        "STRING(6)",
        "Copy",
    )
    prepared(source)


def test_capacity_constant_dependencies_and_nested_array_elements_resolve():
    source = function(
        "VAR CONSTANT n : INT := base + 1; base : INT := 2; END_VAR "
        "VAR a : STRING(n); b : ARRAY[1..2] OF STRING[n + 1]; END_VAR",
        result="STRING(n + 2)",
    )
    pou = prepared(source)["F"]
    assert str(pou.return_type) == "STRING(5)"
    assert str(pou.variables[2].type_name) == "STRING(3)"
    assert str(pou.variables[3].type_name.element_type) == "STRING(4)"


def test_string_named_aliases_and_structure_defaults_truncate():
    source = """TYPE Text : STRING(2) := 'long';
        Record : STRUCT message : Text; label : STRING(3) := 'hello'; END_STRUCT;
        Texts : ARRAY[1..2] OF STRING(4); END_TYPE
        FUNCTION F : Text
        VAR CONSTANT c : Record := (); a : Texts := ['abcde']; END_VAR
        VAR x : STRING(3) := c.message; END_VAR F := x; END_FUNCTION"""
    pou = prepared(source)["F"]
    assert pou.variables[0].default["MESSAGE"] == "lo"
    assert pou.variables[0].default["LABEL"] == "hel"
    assert pou.variables[1].default == ("abcd", "")
    assert pou.variables[2].default == "lo"


def test_text_constant_comparisons_use_truncated_and_nul_normalized_values():
    source = function(
        "VAR CONSTANT a : STRING(2) := 'abc'; b : STRING(4) := 'ab$00x'; "
        "same : BOOL := a = b; ordered : BOOL := 'A' < 'a'; END_VAR",
    )
    variables = prepared(source)["F"].variables
    assert variables[0].default == "ab"
    assert variables[1].default == "ab"
    assert variables[2].default is True
    assert variables[3].default is True


def test_capacity_projection_from_text_comparison_does_not_allocate_composites():
    source = """TYPE Settings : STRUCT label : STRING(3) := 'abc';
        data : ARRAY[1..1000000] OF INT := [TRUE]; END_STRUCT; END_TYPE
        FUNCTION F : INT
        VAR CONSTANT config : Settings := (); n : BOOL := config.label = 'abc'; END_VAR
        VAR text : STRING(n); END_VAR END_FUNCTION"""
    reject(source, "Expected INTEGER")


def test_capacity_resolves_array_projected_string_in_constant_comparison():
    source = function(
        "VAR CONSTANT texts : ARRAY[1..2] OF STRING(2) := ['abc', 'zz']; "
        "matches : BOOL := texts[1] = 'ab'; END_VAR "
        "VAR text : STRING(matches); END_VAR",
    )
    reject(source, "Expected INTEGER")


@pytest.mark.parametrize(
    "declarations",
    [
        "VAR n : INT := 3; text : STRING(n); END_VAR",
        "VAR CONSTANT n : BOOL := TRUE; END_VAR VAR text : STRING(n); END_VAR",
        "VAR CONSTANT n : REAL := 1.0; END_VAR VAR text : STRING(n); END_VAR",
        "VAR text : STRING(1 - 1); END_VAR",
        "VAR text : STRING(1000000 + 1); END_VAR",
        "VAR text : STRING(missing); END_VAR",
        "VAR CONSTANT n : INT := n; END_VAR VAR text : STRING(n); END_VAR",
        "VAR CONSTANT text : STRING(n) := 'x'; n : INT := text; END_VAR",
        "VAR CONSTANT n : INT := F(); END_VAR VAR text : STRING(n); END_VAR",
    ],
)
def test_invalid_capacity_dependencies_are_source_aware(declarations):
    reject(function(declarations))


def test_enum_capacity_is_rejected():
    reject("TYPE E : (A := 2); END_TYPE " + function("VAR text : STRING(E.A); END_VAR"))


def test_named_capacity_cannot_see_pou_local_constants():
    reject("TYPE Text : STRING(n); END_TYPE " + function("VAR CONSTANT n : INT := 2; END_VAR"))


@pytest.mark.parametrize(
    "body",
    [
        "text := 1;",
        "n := text;",
        "F := text = 1;",
        "F := text < 1;",
        "text := text + 'a';",
        "text := -text;",
        "text := NOT text;",
        "n := text[1];",
        "text[1] := 1;",
        "F := text.0;",
        "CASE text OF 1: END_CASE;",
    ],
)
def test_string_numeric_coercion_arithmetic_and_byte_indexing_rejected(body):
    reject(function("VAR text : STRING; n : INT; END_VAR", body, "BOOL"))


@pytest.mark.parametrize("section", ["VAR_INPUT", "VAR_OUTPUT", "VAR_IN_OUT"])
def test_string_arrays_require_exact_element_capacity_for_calls(section):
    mode = "=>" if section == "VAR_OUTPUT" else ":="
    source = function("VAR a : ARRAY[1..2] OF STRING(3); END_VAR", f"G(x {mode} a);")
    source += function(f"{section} x : ARRAY[1..2] OF STRING(4); END_VAR", name="G")
    reject(source)


def test_string_arrays_require_exact_element_capacity_for_assignment():
    reject(
        function(
            "VAR a : ARRAY[1..2] OF STRING(3); b : ARRAY[1..2] OF STRING(4); END_VAR", "a := b;"
        )
    )


def test_in_out_string_capacity_is_exact_but_aliases_are_transparent():
    callee = function("VAR_IN_OUT text : STRING(3); END_VAR", name="G")
    prepared(
        "TYPE Text : STRING(3); END_TYPE "
        + function("VAR text : Text; END_VAR", "G(text);")
        + callee
    )
    reject(function("VAR text : STRING(4); END_VAR", "G(text);") + callee, "exact type")


def test_string_constant_cannot_be_writable_call_binding():
    reject(
        function("VAR CONSTANT text : STRING(3) := 'abc'; END_VAR", "G(text);")
        + function("VAR_IN_OUT text : STRING(3); END_VAR", name="G"),
        "not a writable",
    )


def test_constructed_default_string_type_resolves_for_results_and_array_elements():
    from tc_emulator.syntax import VarDecl
    from tc_emulator.types import ArrayType

    loc = Location("constructed.st", 1, 1)
    variable = VarDecl("TEXTS", ArrayType(((1, 2),), "STRING"), "VAR", None, loc)
    program = Program((Pou("FUNCTION", "F", "STRING", (variable,), (), loc),))
    pou = validate(program)["F"]
    assert str(pou.return_type) == "STRING(80)"
    assert str(pou.variables[0].type_name.element_type) == "STRING(80)"


@pytest.mark.parametrize(
    "kind", ["TYPE STRING : INT; END_TYPE", "FUNCTION STRING : INT END_FUNCTION"]
)
def test_default_string_type_name_is_reserved(kind):
    reject(kind)
