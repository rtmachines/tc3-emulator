"""Method syntax contracts: preserve owner scope and section boundaries."""

import pytest

from tc_emulator.errors import ParseError
from tc_emulator.parser import parse


def test_nested_methods_keep_owner_body_signature_and_local_sections():
    owner = parse(
        """FUNCTION_BLOCK Motor
VAR total : INT; END_VAR
 total := 1;
 METHOD Start
 VAR_INPUT enable : BOOL := TRUE; END_VAR
 total := total + 1;
 END_METHOD
 METHOD PUBLIC Read : INT
 VAR CONSTANT offset : INT := 2; END_VAR
 VAR_INPUT amount : INT; END_VAR
 VAR_OUTPUT done : BOOL; END_VAR
 VAR_IN_OUT shared : INT; END_VAR
 VAR scratch : INT; END_VAR
 Read := total + offset;
 END_METHOD
 METHOD PRIVATE Clear
 total := 0;
 END_METHOD
END_FUNCTION_BLOCK""",
        "methods.st",
    ).pous[0]
    assert len(owner.body) == 1
    assert [method.name for method in owner.methods] == ["MOTOR.START", "MOTOR.READ", "MOTOR.CLEAR"]
    assert [method.access for method in owner.methods] == ["PUBLIC", "PUBLIC", "PRIVATE"]
    assert [method.return_type for method in owner.methods] == [None, "INT", None]
    assert all(method.kind == "METHOD" and method.owner == "MOTOR" for method in owner.methods)
    value = owner.methods[1]
    assert value.result_name == "READ"
    assert value.body[0].target.parts == ("READ",)
    assert [v.section for v in value.variables] == [
        "VAR",
        "VAR_INPUT",
        "VAR_OUTPUT",
        "VAR_IN_OUT",
        "VAR",
    ]
    assert value.variables[0].constant
    assert owner.methods[0].variables[0].initial.value is True
    assert (value.loc.source, value.loc.line, value.loc.column) == ("methods.st", 8, 2)
    assert owner.owner is None and owner.result_name == "MOTOR"


def test_method_names_are_scoped_per_owner():
    program = parse("""FUNCTION_BLOCK A METHOD M : INT M := 1; END_METHOD END_FUNCTION_BLOCK
FUNCTION_BLOCK B METHOD M : INT M := 2; END_METHOD END_FUNCTION_BLOCK""")
    assert [p.methods[0].name for p in program.pous] == ["A.M", "B.M"]


@pytest.mark.parametrize(
    "source",
    [
        "METHOD M END_METHOD",
        "PROGRAM P METHOD M END_METHOD END_PROGRAM",
        "FUNCTION F : INT METHOD M END_METHOD END_FUNCTION",
        "FUNCTION_BLOCK F METHOD M METHOD N END_METHOD END_METHOD END_FUNCTION_BLOCK",
        "FUNCTION_BLOCK F METHOD M END_METHOD F(); END_FUNCTION_BLOCK",
        "FUNCTION_BLOCK F METHOD M VAR_TEMP x : INT; END_VAR END_METHOD END_FUNCTION_BLOCK",
        "FUNCTION_BLOCK F METHOD M VAR_INPUT CONSTANT x : INT; END_VAR END_METHOD END_FUNCTION_BLOCK",
        "FUNCTION_BLOCK F METHOD PUBLIC PRIVATE M END_METHOD END_FUNCTION_BLOCK",
        "FUNCTION_BLOCK F METHOD PROTECTED M END_METHOD END_FUNCTION_BLOCK",
        "FUNCTION_BLOCK F METHOD INTERNAL M END_METHOD END_FUNCTION_BLOCK",
        "FUNCTION_BLOCK F METHOD FINAL M END_METHOD END_FUNCTION_BLOCK",
        "FUNCTION_BLOCK F METHOD M : END_METHOD END_FUNCTION_BLOCK",
        "FUNCTION_BLOCK F METHOD M END_FUNCTION_BLOCK",
    ],
)
def test_malformed_method_placement_modifiers_and_sections_are_rejected(source):
    with pytest.raises(ParseError):
        parse(source)


def test_access_modifiers_remain_valid_field_identifiers_outside_method_headers():
    owner = parse("""FUNCTION_BLOCK Existing
VAR public : INT; private : INT; END_VAR
public := private + 1;
END_FUNCTION_BLOCK""").pous[0]
    assert [v.name for v in owner.variables] == ["PUBLIC", "PRIVATE"]
    assert owner.body[0].target.parts == ("PUBLIC",)
