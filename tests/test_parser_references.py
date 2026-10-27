"""Reference syntax preserves binding intent and raw type/source information."""

from dataclasses import FrozenInstanceError

import pytest

from tc_emulator import syntax as st
from tc_emulator import types
from tc_emulator.errors import ParseError
from tc_emulator.parser import parse


def program(declarations="", body=""):
    return parse(f"PROGRAM P\n{declarations}\n{body}\nEND_PROGRAM", "references.st").pous[0]


@pytest.mark.parametrize(
    "target,want",
    [
        ("INT", "INT"),
        ("Config", "CONFIG"),
        ("ARRAY[-1..2] OF DINT", types.ArrayType(((-1, 2),), "DINT")),
        ("STRING(12)", types.StringType(12)),
    ],
)
def test_reference_declarations_keep_raw_reference_spec_even_for_resolved_targets(target, want):
    declaration = program(f"VAR r : REFERENCE TO {target}; END_VAR").variables[0]
    assert isinstance(declaration.type_name, st.ReferenceSpec)
    assert declaration.type_name.target == want
    assert declaration.type_name.loc == st.Location("references.st", 2, 9)
    assert declaration.initial is None
    with pytest.raises(FrozenInstanceError):
        declaration.type_name.target = "BOOL"


def test_reference_targets_preserve_constant_bound_expressions_for_later_resolution():
    variables = program(
        "VAR a : REFERENCE TO ARRAY[Lo..Hi + 1] OF STRING(Cap);\n"
        "b : REFERENCE TO STRING(Cap + 1); END_VAR"
    ).variables
    array = variables[0].type_name.target
    assert isinstance(array, st.ArrayBounds)
    assert array.bounds[0][0].parts == ("LO",)
    assert array.bounds[0][1].op == "+"
    assert array.bounds[0][1].left.parts == ("HI",)
    assert array.bounds[0][1].right.value == 1
    assert isinstance(array.element_type, st.StringBounds)
    assert array.element_type.length.parts == ("CAP",)
    assert isinstance(variables[1].type_name.target, st.StringBounds)
    assert variables[1].type_name.target.length.op == "+"


@pytest.mark.parametrize("operator", [":=", "REF=", "ref=", "ReF="])
@pytest.mark.parametrize("target", ["source", "0"])
def test_both_reference_initializer_spellings_use_existing_initial_expression(operator, target):
    declaration = program(f"VAR r : reference to INT {operator} {target}; END_VAR").variables[0]
    assert isinstance(declaration.type_name, st.ReferenceSpec)
    if target == "0":
        assert isinstance(declaration.initial, st.Literal)
        assert declaration.initial.value == 0
    else:
        assert isinstance(declaration.initial, st.Reference)
        assert declaration.initial.parts == ("SOURCE",)


def test_reference_binding_statements_are_distinct_from_value_assignments_and_keep_locations():
    pou = program(body="  r ref= other;\n  r := other;\n  r REF= 0;")
    binding, assignment, clear = pou.body
    assert isinstance(binding, st.RefAssign)
    assert binding.target.parts == ("R",)
    assert binding.value.parts == ("OTHER",)
    assert binding.loc == binding.target.loc == st.Location("references.st", 3, 3)
    assert binding.value.loc == st.Location("references.st", 3, 10)
    assert isinstance(assignment, st.Assign)
    assert assignment.value.parts == ("OTHER",)
    assert isinstance(clear, st.RefAssign) and clear.value.value == 0
    with pytest.raises(FrozenInstanceError):
        binding.value = clear.value


def test_ref_identifier_is_not_reserved_by_the_binding_operator():
    pou = program("VAR ref : INT; ref_value : INT; END_VAR", "ref := ref_value;")
    assert pou.variables[0].name == "REF"
    assert isinstance(pou.body[0], st.Assign)
    assert pou.body[0].target.parts == ("REF",)


def test_binding_lvalues_use_existing_this_super_member_and_index_ast():
    pou = program(body="THIS^.r REF= SUPER^.data[2].value;\nobj.refs[1].r REF= items[i];")
    first, second = pou.body
    assert isinstance(first, st.RefAssign)
    assert isinstance(first.target, st.Member) and isinstance(first.target.base, st.This)
    assert first.target.name == "R"
    assert isinstance(first.value, st.Member) and first.value.name == "VALUE"
    assert isinstance(first.value.base, st.Index) and first.value.base.indices[0].value == 2
    assert isinstance(first.value.base.base.base, st.Super)
    assert first.value.base.base.name == "DATA"
    assert isinstance(second.target, st.Member) and second.target.name == "R"
    assert isinstance(second.target.base, st.Index)
    assert second.target.base.base.parts == ("OBJ", "REFS")
    assert second.value.indices[0].parts == ("I",)


def test_reference_validity_uses_the_existing_call_expression():
    call = program(body="ok := __isvalidref(r);").body[0].value
    assert isinstance(call, st.Call) and call.target.parts == ("__ISVALIDREF",)
    assert call.arguments[0].value.parts == ("R",)


@pytest.mark.parametrize(
    "declarations,body",
    [
        ("VAR r : REFERENCE INT; END_VAR", ""),
        ("VAR r : REFERENCE TO; END_VAR", ""),
        ("VAR r : REFERENCE TO INT REF=; END_VAR", ""),
        ("VAR x : INT REF= y; END_VAR", ""),
        ("VAR x : STRING(3) ref= y; END_VAR", ""),
        ("", "r REF=;"),
        ("", "r REF = x;"),
        ("", "r REF:= x;"),
        ("", "r REF= x REF= y;"),
        ("", "0 REF= x;"),
        ("", "r := x REF= y;"),
    ],
)
def test_malformed_reference_syntax_and_binding_initializers_on_values_are_rejected(
    declarations, body
):
    with pytest.raises(ParseError) as caught:
        program(declarations, body)
    assert caught.value.loc.source == "references.st"


def test_semantically_unsupported_reference_positions_remain_available_for_validation():
    result = parse("""TYPE Alias : REFERENCE TO INT;
Record : STRUCT r : REFERENCE TO INT; END_STRUCT; END_TYPE
FUNCTION F : REFERENCE TO INT
VAR_OUTPUT r : REFERENCE TO REFERENCE TO INT; END_VAR
VAR_IN_OUT a : REFERENCE TO ARRAY[*] OF INT; END_VAR
VAR refs : ARRAY[1..2] OF REFERENCE TO INT; END_VAR
END_FUNCTION
FUNCTION_BLOCK B
PROPERTY P : REFERENCE TO INT GET END_GET END_PROPERTY
END_FUNCTION_BLOCK""")
    assert isinstance(result.types[0].definition, st.ReferenceSpec)
    assert isinstance(result.types[1].definition.fields[0].type_name, st.ReferenceSpec)
    function = result.pous[0]
    assert isinstance(function.return_type, st.ReferenceSpec)
    assert isinstance(function.variables[0].type_name.target, st.ReferenceSpec)
    assert isinstance(function.variables[1].type_name.target, types.OpenArrayType)
    assert isinstance(function.variables[2].type_name, st.ArrayBounds)
    assert isinstance(function.variables[2].type_name.element_type, st.ReferenceSpec)
    assert isinstance(result.pous[1].properties[0].type_name, st.ReferenceSpec)


def test_resolved_reference_descriptor_is_rejected_by_value_utilities():
    assert hasattr(types, "ReferenceType")
    reference = types.ReferenceType("INT")
    assert reference.target == "INT" and str(reference) == "REFERENCE TO INT"
    assert not types.is_value_type(reference)
    with pytest.raises(FrozenInstanceError):
        reference.target = "BOOL"
    for operation in (
        lambda: types.check_value(reference, 0),
        lambda: types.default_value(reference),
        lambda: types.value_leaf_count(reference),
        lambda: types.resolve_type(reference, {}),
        lambda: types.resolve_type("Ref", {"REF": reference}),
        lambda: types.ArrayType(((0, 1),), reference),
    ):
        with pytest.raises((TypeError, ValueError), match="supported value type"):
            operation()


@pytest.mark.parametrize(
    "text,want",
    [
        ("a AND_THEN b AND_THEN c", ("AND_THEN", ("AND_THEN", "A", "B"), "C")),
        ("a OR_ELSE b OR_ELSE c", ("OR_ELSE", ("OR_ELSE", "A", "B"), "C")),
        ("a AND b AND_THEN c", ("AND_THEN", ("AND", "A", "B"), "C")),
        ("a AND_THEN b AND c", ("AND", ("AND_THEN", "A", "B"), "C")),
        ("a OR b OR_ELSE c", ("OR_ELSE", ("OR", "A", "B"), "C")),
        ("a OR_ELSE b OR c", ("OR", ("OR_ELSE", "A", "B"), "C")),
        (
            "a OR_ELSE b XOR c AND_THEN d",
            ("OR_ELSE", "A", ("XOR", "B", ("AND_THEN", "C", "D"))),
        ),
        (
            "NOT a = b and_then c < d or_else NOT e",
            ("OR_ELSE", ("AND_THEN", ("=", ("NOT", "A"), "B"), ("<", "C", "D")), ("NOT", "E")),
        ),
    ],
)
def test_short_circuit_operators_share_and_or_precedence_and_left_associativity(text, want):
    def shape(expression):
        if isinstance(expression, st.Binary):
            return (expression.op, shape(expression.left), shape(expression.right))
        if isinstance(expression, st.Unary):
            return (expression.op, shape(expression.operand))
        return expression.parts[0]

    assert shape(program(body=f"result := {text};").body[0].value) == want
