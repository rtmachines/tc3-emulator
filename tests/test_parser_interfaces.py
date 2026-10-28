"""Interface prototypes and IMPLEMENTS retain the existing immutable AST contracts."""

from dataclasses import FrozenInstanceError

import pytest

from tc_emulator import syntax, types
from tc_emulator.errors import ParseError
from tc_emulator.parser import parse


def test_old_ast_constructors_have_empty_interface_defaults():
    loc = syntax.Location("old.st", 1, 1)
    pou = syntax.Pou("FUNCTION_BLOCK", "F", None, (), (), loc)
    assert getattr(pou, "implements", None) == ()
    assert getattr(syntax.Program((pou,)), "interfaces", None) == ()


def test_interface_type_is_nominal_normalized_and_never_a_value():
    assert hasattr(types, "InterfaceType")
    interface = types.InterfaceType("I_Motor")
    assert interface.name == "I_MOTOR" and str(interface) == "I_MOTOR"
    assert types.same_type(interface, types.InterfaceType("i_motor"))
    assert not types.same_type(interface, types.InterfaceType("I_Other"))
    assert not types.is_value_type(interface)
    with pytest.raises(FrozenInstanceError):
        interface.name = "OTHER"
    for operation in (
        lambda: types.check_value(interface, 0),
        lambda: types.default_value(interface),
        lambda: types.resolve_type(interface, {}),
        lambda: types.resolve_type("I_MOTOR", {"I_MOTOR": interface}),
        lambda: types.ArrayType(((0, 1),), interface),
    ):
        with pytest.raises((TypeError, ValueError)):
            operation()


@pytest.mark.parametrize("name", ["", "I.Motor", "I Motor", "1I", None, 1])
def test_interface_type_requires_an_identifier(name):
    assert hasattr(types, "InterfaceType")
    with pytest.raises((TypeError, ValueError)):
        types.InterfaceType(name)


def test_interface_prototypes_and_implements_are_separate_from_executable_pous():
    program = parse(
        """FUNCTION_BLOCK Motor IMPLEMENTS I_Motor, I_Status END_FUNCTION_BLOCK
INTERFACE I_Motor
METHOD PUBLIC Set
VAR_INPUT speed : INT := 12; peer : I_Motor := 0; END_VAR
VAR_OUTPUT accepted : BOOL; END_VAR
VAR_IN_OUT counter : DINT; END_VAR
END_METHOD
PROPERTY PUBLIC Speed : INT GET PUBLIC END_GET SET END_SET END_PROPERTY
END_INTERFACE
INTERFACE I_Status END_INTERFACE""",
        "motor.st",
    )
    assert len(program.pous) == 1
    assert program.pous[0].implements == ("I_MOTOR", "I_STATUS")
    interface, empty = program.interfaces
    assert isinstance(interface, syntax.InterfaceDecl) and interface.name == "I_MOTOR"
    assert empty.methods == empty.properties == ()
    method = interface.methods[0]
    assert (method.name, method.kind, method.owner, method.result_name) == (
        "I_MOTOR.SET",
        "METHOD",
        "I_MOTOR",
        "SET",
    )
    assert method.body == () and method.access == "PUBLIC"
    assert [v.section for v in method.variables] == [
        "VAR_INPUT",
        "VAR_INPUT",
        "VAR_OUTPUT",
        "VAR_IN_OUT",
    ]
    assert method.variables[0].initial.value == 12
    assert method.variables[1].initial.value == 0
    prop = interface.properties[0]
    assert prop.getter.name == "I_MOTOR.SPEED.GET"
    assert prop.setter.name == "I_MOTOR.SPEED.SET"
    assert prop.getter.kind == "PROPERTY_GET" and prop.setter.kind == "PROPERTY_SET"
    assert prop.getter.owner == prop.setter.owner == "I_MOTOR"
    assert prop.getter.result_name == prop.setter.result_name == "SPEED"
    assert prop.getter.body == prop.setter.body == prop.variables == ()
    assert interface.loc.line == 2 and method.loc.line == 3


@pytest.mark.parametrize(
    "members",
    [
        "METHOD M M(); END_METHOD",
        "METHOD PRIVATE M END_METHOD",
        "METHOD M VAR x : INT; END_VAR END_METHOD",
        "METHOD M VAR_INST x : INT; END_VAR END_METHOD",
        "METHOD M VAR_TEMP x : INT; END_VAR END_METHOD",
        "METHOD M VAR_INPUT CONSTANT x : INT; END_VAR END_METHOD",
        "METHOD M VAR_OUTPUT x : INT := 1; END_VAR END_METHOD",
        "METHOD M VAR_IN_OUT x : INT := 1; END_VAR END_METHOD",
        "METHOD M METHOD Nested END_METHOD END_METHOD",
        "PROPERTY PRIVATE P : INT GET END_GET END_PROPERTY",
        "PROPERTY P : INT VAR x : INT; END_VAR GET END_GET END_PROPERTY",
        "PROPERTY P : INT GET PRIVATE END_GET END_PROPERTY",
        "PROPERTY P : INT GET VAR x : INT; END_VAR END_GET END_PROPERTY",
        "PROPERTY P : INT GET P := 1; END_GET END_PROPERTY",
        "VAR x : INT; END_VAR",
        "M();",
    ],
)
def test_interfaces_reject_executable_private_and_storage_members(members):
    with pytest.raises(ParseError):
        parse(f"INTERFACE I_Test {members} END_INTERFACE")


@pytest.mark.parametrize(
    "source",
    [
        "FUNCTION_BLOCK F IMPLEMENTS END_FUNCTION_BLOCK",
        "FUNCTION_BLOCK F IMPLEMENTS I, END_FUNCTION_BLOCK",
        "FUNCTION_BLOCK F IMPLEMENTS I, i END_FUNCTION_BLOCK",
        "FUNCTION_BLOCK F IMPLEMENTS I IMPLEMENTS J END_FUNCTION_BLOCK",
        "PROGRAM P IMPLEMENTS I END_PROGRAM",
        "FUNCTION F IMPLEMENTS I : INT END_FUNCTION",
        "FUNCTION F : INT IMPLEMENTS I END_FUNCTION",
        "INTERFACE I METHOD M END_METHOD",
    ],
)
def test_malformed_or_non_fb_implements_are_rejected(source):
    with pytest.raises(ParseError):
        parse(source)


def test_interface_get_set_names_remain_contextual():
    interface = parse("""INTERFACE I
METHOD Get : INT END_METHOD
METHOD Set VAR_INPUT get : INT; set : BOOL; END_VAR END_METHOD
PROPERTY P : INT GET END_GET SET END_SET END_PROPERTY
END_INTERFACE""").interfaces[0]
    assert [m.result_name for m in interface.methods] == ["GET", "SET"]
    assert [v.name for v in interface.methods[1].variables] == ["GET", "SET"]
