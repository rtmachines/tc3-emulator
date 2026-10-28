"""Only direct owned interface arrays enter the storage type system."""

import pytest

from tc_emulator import ParseError, ValidationError
from tc_emulator.parser import parse
from tc_emulator.types import InterfaceArrayType, InterfaceType
from tc_emulator.validation import validate

INTERFACES = """
INTERFACE I METHOD Add : INT VAR_INPUT amount : INT; END_VAR END_METHOD
PROPERTY Value : INT GET END_GET SET END_SET END_PROPERTY END_INTERFACE
INTERFACE Derived EXTENDS I END_INTERFACE
"""


def check(source):
    return validate(parse(INTERFACES + source, source="interface-arrays.st"))


@pytest.mark.parametrize(
    "source,owner",
    [
        ("PROGRAM P VAR a : ARRAY[-1..0,2..3] OF Derived; END_VAR END_PROGRAM", "P"),
        ("FUNCTION_BLOCK P VAR a : ARRAY[-1..0,2..3] OF Derived; END_VAR END_FUNCTION_BLOCK", "P"),
        ("FUNCTION P : INT VAR a : ARRAY[-1..0,2..3] OF Derived; END_VAR END_FUNCTION", "P"),
        ("VAR_GLOBAL a : ARRAY[-1..0,2..3] OF Derived; END_VAR", "GVL"),
        ("PROGRAM P VAR_TEMP a : ARRAY[-1..0,2..3] OF Derived; END_VAR END_PROGRAM", "P"),
        (
            "FUNCTION_BLOCK P VAR_TEMP a : ARRAY[-1..0,2..3] OF Derived; END_VAR END_FUNCTION_BLOCK",
            "P",
        ),
        (
            "FUNCTION_BLOCK P METHOD M VAR a : ARRAY[-1..0,2..3] OF Derived; END_VAR END_METHOD END_FUNCTION_BLOCK",
            "P.M",
        ),
        (
            "FUNCTION_BLOCK P METHOD M VAR_INST a : ARRAY[-1..0,2..3] OF Derived; END_VAR END_METHOD END_FUNCTION_BLOCK",
            "P.M",
        ),
        (
            "FUNCTION_BLOCK P PROPERTY V : INT GET VAR a : ARRAY[-1..0,2..3] OF Derived; END_VAR END_GET END_PROPERTY END_FUNCTION_BLOCK",
            "P.V.GET",
        ),
        (
            "FUNCTION_BLOCK P PROPERTY V : INT SET VAR a : ARRAY[-1..0,2..3] OF Derived; END_VAR END_SET END_PROPERTY END_FUNCTION_BLOCK",
            "P.V.SET",
        ),
    ],
)
def test_owned_storage_is_normalized(source, owner):
    registry = check(source)
    assert registry[owner].variables[0].type_name == InterfaceArrayType(
        ((-1, 0), (2, 3)), InterfaceType("Derived")
    )
    assert registry[owner].variables[0].default is None


def test_expression_bounds_and_inherited_element_contract():
    registry = check("""
    VAR_GLOBAL CONSTANT N : INT := 3; END_VAR
    PROGRAM P
    VAR a : ARRAY[N-4..0,2..N] OF Derived; result : INT; END_VAR
    result := LOWER_BOUND(a, 1) + UPPER_BOUND(a, 2);
    result := a[-1,3].Add(2); a[0,2].Value := result; result := a[0,2].Value;
    END_PROGRAM
    """)
    assert registry["P"].variables[0].type_name.bounds == ((-1, 0), (2, 3))
    assert registry.method_calls
    assert registry.property_reads and registry.property_writes


@pytest.mark.parametrize("mode", ["VAR_INPUT", "VAR_OUTPUT", "VAR_IN_OUT"])
@pytest.mark.parametrize("bounds", ["1..2", "*"])
@pytest.mark.parametrize("prototype", [False, True])
def test_parameters_are_rejected_including_unused_prototypes(mode, bounds, prototype):
    declaration = f"{mode} a : ARRAY[{bounds}] OF I; END_VAR"
    source = (
        f"INTERFACE Other METHOD M {declaration} END_METHOD END_INTERFACE"
        if prototype
        else f"FUNCTION F : INT {declaration} END_FUNCTION"
    )
    with pytest.raises(ValidationError):
        check(source)


@pytest.mark.parametrize(
    "declaration",
    [
        "VAR CONSTANT a : ARRAY[1..2] OF I := [0,0]; END_VAR",
        "VAR a : ARRAY[1..2] OF I := [0,0]; END_VAR",
        "VAR a : ARRAY[1..2] OF I := 0; END_VAR",
        "VAR a : ARRAY[1..2] OF I(); END_VAR",
        "VAR a : ARRAY[1..2] OF I[(),()]; END_VAR",
        "VAR a : REFERENCE TO ARRAY[1..2] OF I; END_VAR",
    ],
)
def test_unsupported_declarations_have_no_value_or_constructor_semantics(declaration):
    with pytest.raises(ValidationError):
        check(f"PROGRAM P {declaration} END_PROGRAM")


@pytest.mark.parametrize(
    "declaration",
    [
        "TYPE A : ARRAY[1..2] OF I; END_TYPE",
        "TYPE A : STRUCT a : ARRAY[1..2] OF I; END_STRUCT; END_TYPE",
        "FUNCTION F : ARRAY[1..2] OF I END_FUNCTION",
    ],
)
def test_no_alias_struct_field_or_return_type(declaration):
    with pytest.raises(ValidationError):
        check(declaration)


@pytest.mark.parametrize(
    "body",
    [
        "a := a;",
        "ok := a = a;",
        "ok := a <> 0;",
        "a[1].hidden := 2;",
        "a[TRUE] := 0;",
        "a[1,2] := 0;",
        "n := LOWER_BOUND(a, TRUE);",
    ],
)
def test_unsupported_operations_are_source_aware(body):
    with pytest.raises(ValidationError) as caught:
        check(f"PROGRAM P VAR a : ARRAY[1..2] OF I; ok : BOOL; n : INT; END_VAR {body} END_PROGRAM")
    assert caught.value.loc.source == "interface-arrays.st"


def storage_source(extra=""):
    return f"""
    FUNCTION_BLOCK Leaf VAR a : ARRAY[1..1000] OF I; END_VAR END_FUNCTION_BLOCK
    FUNCTION_BLOCK Group VAR children : ARRAY[1..1000] OF Leaf; {extra} END_VAR END_FUNCTION_BLOCK
    """


def test_expanded_nested_storage_limit_is_checked_without_runtime_allocation():
    check(storage_source())
    with pytest.raises(
        ValidationError, match="Expanded storage exceeds the 1000000 scalar leaf limit"
    ):
        check(storage_source("one : I;"))


def test_method_instance_arrays_contribute_to_storage_limit():
    with pytest.raises(ValidationError, match="Expanded storage"):
        check("""
        FUNCTION_BLOCK P
        VAR a : ARRAY[1..1000000] OF I; END_VAR
        METHOD M VAR_INST one : ARRAY[1..1] OF I; END_VAR END_METHOD
        END_FUNCTION_BLOCK
        """)


def test_nested_array_syntax_is_outside_the_checked_profile():
    with pytest.raises(ParseError):
        check("PROGRAM P VAR a : ARRAY[1..2] OF ARRAY[1..2] OF I; END_VAR END_PROGRAM")


@pytest.mark.parametrize("body", ["derived[1] := base[1];", "base[1] := sibling[1];"])
def test_element_assignment_preserves_declared_contract_direction(body):
    with pytest.raises(ValidationError, match="implementing|interface|Interface"):
        check(f"""
        INTERFACE Sibling END_INTERFACE
        PROGRAM P VAR base : ARRAY[1..1] OF I; derived : ARRAY[1..1] OF Derived;
        sibling : ARRAY[1..1] OF Sibling; END_VAR {body} END_PROGRAM
        """)


def test_array_dispatch_still_contributes_to_static_recursion_checks():
    with pytest.raises(ValidationError, match="Recursive call"):
        check("""
        VAR_GLOBAL devices : ARRAY[1..1] OF I; END_VAR
        FUNCTION_BLOCK B IMPLEMENTS I
        METHOD Add : INT VAR_INPUT amount : INT; END_VAR Add := devices[1].Add(amount); END_METHOD
        PROPERTY Value : INT GET END_GET SET END_SET END_PROPERTY
        END_FUNCTION_BLOCK
        """)


@pytest.mark.parametrize(
    "name,section",
    [("Missing", "VAR"), ("I", "VAR_INPUT"), ("I", "VAR_OUTPUT"), ("I", "VAR_IN_OUT")],
)
def test_caller_constructed_descriptors_cannot_bypass_declaration_checks(name, section):
    from dataclasses import replace

    program = parse(INTERFACES + "PROGRAM P VAR a : INT; END_VAR END_PROGRAM")
    pou = program.pous[0]
    variable = replace(
        pou.variables[0],
        type_name=InterfaceArrayType(((1, 2),), InterfaceType(name)),
        section=section,
    )
    with pytest.raises(ValidationError):
        validate(replace(program, pous=(replace(pou, variables=(variable,)),)))
