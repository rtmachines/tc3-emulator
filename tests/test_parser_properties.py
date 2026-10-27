"""Property serialization, explicit self paths and persistent method syntax."""

import pytest

from tc_emulator import syntax
from tc_emulator.errors import ParseError
from tc_emulator.parser import parse


def test_properties_interleave_methods_and_preserve_accessor_contract():
    owner = parse(
        """FUNCTION_BLOCK Drive
VAR speed : INT; END_VAR
speed := 1;
METHOD Read : INT
VAR_INST count : INT := 0; END_VAR
Read := count;
END_METHOD
PROPERTY PUBLIC SpeedSetpoint : INT
VAR CONSTANT limit : INT := 10; END_VAR
GET PRIVATE
VAR scratch : INT; END_VAR
SpeedSetpoint := THIS^.speed + limit;
END_GET
SET
VAR value : INT; END_VAR
THIS^.speed := SpeedSetpoint;
END_SET
END_PROPERTY
METHOD Clear END_METHOD
PROPERTY PRIVATE Running : BOOL GET Running := TRUE; END_GET END_PROPERTY
END_FUNCTION_BLOCK""",
        "properties.st",
    ).pous[0]
    assert len(owner.body) == 1
    assert [m.name for m in owner.methods] == ["DRIVE.READ", "DRIVE.CLEAR"]
    assert owner.methods[0].variables[0].section == "VAR_INST"
    assert [p.name for p in owner.properties] == ["SPEEDSETPOINT", "RUNNING"]
    prop = owner.properties[0]
    assert prop.access == "PUBLIC" and prop.type_name == "INT"
    assert [v.name for v in prop.variables] == ["LIMIT"]
    getter, setter = prop.getter, prop.setter
    assert getter.name == "DRIVE.SPEEDSETPOINT.GET"
    assert setter.name == "DRIVE.SPEEDSETPOINT.SET"
    assert (getter.kind, setter.kind) == ("PROPERTY_GET", "PROPERTY_SET")
    assert getter.owner == setter.owner == "DRIVE"
    assert getter.return_type == setter.return_type == "INT"
    assert getter.result_name == setter.result_name == "SPEEDSETPOINT"
    assert getter.property_name == setter.property_name == "SPEEDSETPOINT"
    assert getter.access == "PRIVATE" and setter.access == "PUBLIC"
    assert [v.name for v in getter.variables] == ["LIMIT", "SCRATCH"]
    assert [v.name for v in setter.variables] == ["LIMIT", "VALUE"]
    assert getter.variables[0].constant
    assert owner.properties[1].getter.access == "PRIVATE"
    assert owner.properties[1].setter is None
    assert prop.loc.line == 8 and getter.loc.line == 10 and setter.loc.line == 14


def test_this_chains_retain_explicit_owner_base_in_body_methods_and_accessors():
    owner = parse("""FUNCTION_BLOCK Drive
THIS^.child[2].Tick();
METHOD M : INT M := THIS^.child[1].value; END_METHOD
PROPERTY P : INT SET THIS^.child[0].value := P; END_SET END_PROPERTY
END_FUNCTION_BLOCK""").pous[0]
    target = owner.body[0].call.target
    assert isinstance(target, syntax.Member) and target.name == "TICK"
    assert isinstance(target.base, syntax.Index)
    assert isinstance(target.base.base, syntax.Member) and target.base.base.name == "CHILD"
    assert isinstance(target.base.base.base, syntax.This)
    assert isinstance(owner.methods[0].body[0].value.base.base.base, syntax.This)
    assert isinstance(owner.properties[0].setter.body[0].target.base.base.base, syntax.This)


@pytest.mark.parametrize(
    "source",
    [
        "FUNCTION_BLOCK F PROPERTY P : INT END_PROPERTY END_FUNCTION_BLOCK",
        "FUNCTION_BLOCK F PROPERTY P : INT GET END_GET GET END_GET END_PROPERTY END_FUNCTION_BLOCK",
        "FUNCTION_BLOCK F PROPERTY P : INT SET END_SET SET END_SET END_PROPERTY END_FUNCTION_BLOCK",
        "PROGRAM P PROPERTY X : INT GET END_GET END_PROPERTY END_PROGRAM",
        "FUNCTION F : INT PROPERTY X : INT GET END_GET END_PROPERTY END_FUNCTION",
        "FUNCTION_BLOCK F PROPERTY P : INT VAR_INPUT x : INT; END_VAR GET END_GET END_PROPERTY END_FUNCTION_BLOCK",
        "FUNCTION_BLOCK F PROPERTY P : INT GET VAR_INST x : INT; END_VAR END_GET END_PROPERTY END_FUNCTION_BLOCK",
        "FUNCTION_BLOCK F PROPERTY P : INT GET VAR_TEMP x : INT; END_VAR END_GET END_PROPERTY END_FUNCTION_BLOCK",
        "FUNCTION_BLOCK F PROPERTY P : INT GET VAR CONSTANT x : INT; END_VAR END_PROPERTY END_FUNCTION_BLOCK",
        "FUNCTION_BLOCK F PROPERTY P : INT GET END_GET P := 1; END_PROPERTY END_FUNCTION_BLOCK",
        "FUNCTION_BLOCK F PROPERTY PUBLIC PRIVATE P : INT GET END_GET END_PROPERTY END_FUNCTION_BLOCK",
        "FUNCTION_BLOCK F VAR_INST x : INT; END_VAR END_FUNCTION_BLOCK",
        "FUNCTION F : INT VAR_INST x : INT; END_VAR END_FUNCTION",
        "PROGRAM P VAR_INST x : INT; END_VAR END_PROGRAM",
        "FUNCTION_BLOCK F METHOD M VAR_INST CONSTANT x : INT; END_VAR END_METHOD END_FUNCTION_BLOCK",
        "FUNCTION_BLOCK F METHOD M VAR_INST RETAIN x : INT; END_VAR END_METHOD END_FUNCTION_BLOCK",
        "FUNCTION_BLOCK F METHOD M VAR_INST PERSISTENT x : INT; END_VAR END_METHOD END_FUNCTION_BLOCK",
        "FUNCTION_BLOCK F THIS(); END_FUNCTION_BLOCK",
        "FUNCTION_BLOCK F VAR x : INT; END_VAR x := THIS; END_FUNCTION_BLOCK",
        "FUNCTION_BLOCK F VAR x : INT; END_VAR x := THIS^; END_FUNCTION_BLOCK",
        "FUNCTION_BLOCK F VAR x : INT; END_VAR x := x^; END_FUNCTION_BLOCK",
    ],
)
def test_malformed_properties_self_paths_and_instance_sections_rejected(source):
    with pytest.raises(ParseError):
        parse(source)


def test_get_and_set_remain_valid_identifiers_outside_accessor_headers():
    owner = parse("""FUNCTION_BLOCK Existing
VAR get : INT; set : INT; END_VAR
get := set;
METHOD Set VAR_INPUT value : INT; END_VAR get := value; END_METHOD
METHOD Get : INT Get := get; END_METHOD
PROPERTY P : INT GET P := get; END_GET END_PROPERTY
END_FUNCTION_BLOCK""").pous[0]
    assert [v.name for v in owner.variables] == ["GET", "SET"]
    assert [m.name for m in owner.methods] == ["EXISTING.SET", "EXISTING.GET"]
    assert owner.properties[0].getter.body[0].value.parts == ("GET",)


@pytest.mark.parametrize("type_name", ["BOOL", "TIME", "STRING(12)", "State", "Alias"])
def test_property_type_descriptors_and_setter_only_accessors(type_name):
    prop = (
        parse(f"""FUNCTION_BLOCK B
PROPERTY PRIVATE Value : {type_name}
SET Value := Value; END_SET
END_PROPERTY END_FUNCTION_BLOCK""")
        .pous[0]
        .properties[0]
    )
    assert prop.getter is None and prop.setter.access == "PRIVATE"
    assert prop.setter.return_type == prop.type_name
    assert prop.setter.result_name == "VALUE"


def test_var_inst_accepts_existing_value_and_fb_declaration_shapes():
    method = (
        parse("""FUNCTION_BLOCK B METHOD Step
VAR_INST
n : INT := 1;
data : ARRAY[0..2] OF INT := [3(0)];
record : Data := (value := 2);
timer : TON;
children : ARRAY[1..3] OF Child;
END_VAR
VAR scratch : INT; END_VAR
END_METHOD END_FUNCTION_BLOCK""")
        .pous[0]
        .methods[0]
    )
    assert [v.name for v in method.variables] == [
        "N",
        "DATA",
        "RECORD",
        "TIMER",
        "CHILDREN",
        "SCRATCH",
    ]
    assert [v.section for v in method.variables] == ["VAR_INST"] * 5 + ["VAR"]
    assert method.variables[0].initial.value == 1


@pytest.mark.parametrize(
    "section", ["VAR_INPUT", "VAR_OUTPUT", "VAR_IN_OUT", "VAR_TEMP", "VAR_INST"]
)
@pytest.mark.parametrize("position", ["property", "getter", "setter"])
def test_properties_reject_nonlocal_variable_sections(section, position):
    declarations = f"{section} x : INT; END_VAR"
    header = declarations if position == "property" else ""
    getter = declarations if position == "getter" else ""
    setter = declarations if position == "setter" else ""
    with pytest.raises(ParseError):
        parse(f"""FUNCTION_BLOCK B PROPERTY P : INT {header}
GET {getter} END_GET SET {setter} END_SET END_PROPERTY END_FUNCTION_BLOCK""")
