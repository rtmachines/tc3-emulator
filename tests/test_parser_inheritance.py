"""Inheritance syntax preserves lexical owners and explicit SUPER receivers."""

import pytest

from tc_emulator import syntax
from tc_emulator.errors import ParseError
from tc_emulator.parser import parse


def test_forward_base_with_implements_preserves_only_declared_members_and_owners():
    program = parse(
        """FUNCTION_BLOCK Child EXTENDS Base IMPLEMENTS I_Run, I_State
METHOD PROTECTED Step END_METHOD
PROPERTY PROTECTED Value : INT
GET Value := SUPER^.Value; END_GET
SET PRIVATE SUPER^.Value := Value; END_SET
END_PROPERTY
END_FUNCTION_BLOCK
FUNCTION_BLOCK Base METHOD Run END_METHOD END_FUNCTION_BLOCK""",
        "inheritance.st",
    )
    child, base = program.pous
    assert child.extends == "BASE"
    assert child.implements == ("I_RUN", "I_STATE")
    assert base.extends is None
    assert [method.name for method in child.methods] == ["CHILD.STEP"]
    assert child.methods[0].owner == "CHILD" and child.methods[0].access == "PROTECTED"
    assert base.methods[0].name == "BASE.RUN" and base.methods[0].owner == "BASE"
    prop = child.properties[0]
    assert prop.access == prop.getter.access == "PROTECTED"
    assert prop.setter.access == "PRIVATE"
    assert prop.getter.name == "CHILD.VALUE.GET" and prop.setter.name == "CHILD.VALUE.SET"
    assert prop.getter.owner == prop.setter.owner == "CHILD"
    assert child.loc == syntax.Location("inheritance.st", 1, 1)
    assert child.methods[0].loc == syntax.Location("inheritance.st", 2, 1)
    assert prop.getter.loc == syntax.Location("inheritance.st", 4, 1)


def test_super_body_method_property_and_indexed_field_paths_have_explicit_ast_receivers():
    owner = parse(
        """FUNCTION_BLOCK Child EXTENDS Base
  SUPER^();
  SUPER^.Run(value := SUPER^.items[2].value);
  SUPER^.Value := SUPER^.Read();
METHOD Read : INT Read := SUPER^.Value; END_METHOD
PROPERTY Value : INT GET Value := SUPER^.items[0].value; END_GET
SET SUPER^.Value := Value; END_SET END_PROPERTY
END_FUNCTION_BLOCK""",
        "super.st",
    ).pous[0]
    call = owner.body[0].call
    assert isinstance(call, syntax.Call) and isinstance(call.target, syntax.Super)
    assert call.arguments == ()
    assert call.target.loc == call.loc == syntax.Location("super.st", 2, 3)
    method = owner.body[1].call
    assert isinstance(method.target, syntax.Member) and method.target.name == "RUN"
    assert isinstance(method.target.base, syntax.Super)
    assert method.target.base.loc == syntax.Location("super.st", 3, 3)
    field = method.arguments[0].value
    assert isinstance(field, syntax.Member) and field.name == "VALUE"
    assert isinstance(field.base, syntax.Index) and field.base.indices[0].value == 2
    assert field.base.base.name == "ITEMS" and isinstance(field.base.base.base, syntax.Super)
    assert field.base.base.base.loc == syntax.Location("super.st", 3, 23)
    assignment = owner.body[2]
    assert assignment.target.name == "VALUE" and isinstance(assignment.target.base, syntax.Super)
    assert isinstance(assignment.value, syntax.Call) and assignment.value.target.name == "READ"
    assert isinstance(assignment.value.target.base, syntax.Super)
    assert isinstance(owner.methods[0].body[0].value.base, syntax.Super)
    assert isinstance(owner.properties[0].getter.body[0].value.base.base.base, syntax.Super)
    assert isinstance(owner.properties[0].setter.body[0].target.base, syntax.Super)


def test_explicit_protected_accessor_on_public_property_and_contextual_field_name():
    owner = parse("""FUNCTION_BLOCK B
VAR protected : INT; END_VAR
protected := 1;
PROPERTY P : INT GET PROTECTED P := protected; END_GET
SET PROTECTED protected := P; END_SET END_PROPERTY
END_FUNCTION_BLOCK""").pous[0]
    assert owner.variables[0].name == "PROTECTED"
    assert owner.body[0].target.parts == ("PROTECTED",)
    assert owner.properties[0].access == "PUBLIC"
    assert owner.properties[0].getter.access == owner.properties[0].setter.access == "PROTECTED"


@pytest.mark.parametrize(
    "source",
    [
        "PROGRAM P EXTENDS Base END_PROGRAM",
        "FUNCTION F EXTENDS Base : INT END_FUNCTION",
        "FUNCTION_BLOCK F EXTENDS END_FUNCTION_BLOCK",
        "FUNCTION_BLOCK F EXTENDS Base, Other END_FUNCTION_BLOCK",
        "FUNCTION_BLOCK F EXTENDS Base EXTENDS Other END_FUNCTION_BLOCK",
        "FUNCTION_BLOCK F IMPLEMENTS I EXTENDS Base END_FUNCTION_BLOCK",
        "FUNCTION_BLOCK ABSTRACT F EXTENDS Base END_FUNCTION_BLOCK",
        "FUNCTION_BLOCK FINAL F EXTENDS Base END_FUNCTION_BLOCK",
        "FUNCTION_BLOCK F EXTENDS Base METHOD PROTECTED PRIVATE M END_METHOD END_FUNCTION_BLOCK",
        "FUNCTION_BLOCK F EXTENDS Base METHOD INTERNAL M END_METHOD END_FUNCTION_BLOCK",
        "FUNCTION_BLOCK F EXTENDS Base METHOD FINAL M END_METHOD END_FUNCTION_BLOCK",
        "FUNCTION_BLOCK F EXTENDS Base PROPERTY PROTECTED PUBLIC P : INT GET END_GET END_PROPERTY END_FUNCTION_BLOCK",
        "FUNCTION_BLOCK F EXTENDS Base PROPERTY P : INT GET PROTECTED PRIVATE END_GET END_PROPERTY END_FUNCTION_BLOCK",
        "FUNCTION_BLOCK F EXTENDS Base SUPER(); END_FUNCTION_BLOCK",
        "FUNCTION_BLOCK F EXTENDS Base SUPER.Run(); END_FUNCTION_BLOCK",
        "INTERFACE I EXTENDS I_Base END_INTERFACE",
        "INTERFACE I METHOD PROTECTED M END_METHOD END_INTERFACE",
        "INTERFACE I PROPERTY PROTECTED P : INT GET END_GET END_PROPERTY END_INTERFACE",
        "INTERFACE I PROPERTY P : INT GET PROTECTED END_GET END_PROPERTY END_INTERFACE",
    ],
)
def test_malformed_inheritance_modifiers_and_interface_extensions_are_rejected(source):
    with pytest.raises(ParseError) as caught:
        parse(source, "invalid-inheritance.st")
    assert caught.value.loc.source == "invalid-inheritance.st"
    assert caught.value.loc.line == 1
