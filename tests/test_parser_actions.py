"""Actions retain their owner and cannot introduce declaration scopes."""

import pytest

from tc_emulator.errors import ParseError
from tc_emulator.parser import parse


@pytest.mark.parametrize("kind", ["FUNCTION_BLOCK", "PROGRAM"])
def test_actions_keep_owner_body_and_qualified_statement_scopes(kind):
    owner = parse(
        f"""{kind} Motor
VAR count : INT; END_VAR
count := 1;
ACTION Add:
count := count + 1;
END_ACTION
ACTION Clear: RETURN; END_ACTION
END_{kind}""",
        "actions.st",
    ).pous[0]
    assert len(owner.body) == 1
    assert [a.name for a in owner.actions] == ["MOTOR.ADD", "MOTOR.CLEAR"]
    action = owner.actions[0]
    assert action.kind == "ACTION" and action.owner == "MOTOR"
    assert action.variables == () and action.return_type is None
    assert (action.loc.source, action.loc.line, action.loc.column) == ("actions.st", 4, 1)
    assert action.body[0].loc.line == 5


def test_actions_interleave_with_methods_and_properties_without_merging_bodies():
    owner = parse("""FUNCTION_BLOCK B
ACTION First: END_ACTION
METHOD M END_METHOD
ACTION Second: END_ACTION
PROPERTY Value : INT GET Value := 1; END_GET END_PROPERTY
ACTION Third: END_ACTION
END_FUNCTION_BLOCK""").pous[0]
    assert [a.result_name for a in owner.actions] == ["FIRST", "SECOND", "THIRD"]
    assert len(owner.methods) == len(owner.properties) == 1
    assert owner.body == ()


@pytest.mark.parametrize(
    "source",
    [
        "ACTION A: END_ACTION",
        "FUNCTION F : INT ACTION A: END_ACTION END_FUNCTION",
        "INTERFACE I ACTION A: END_ACTION END_INTERFACE",
        "FUNCTION_BLOCK B ACTION A END_ACTION END_FUNCTION_BLOCK",
        "FUNCTION_BLOCK B ACTION A: INT END_ACTION END_FUNCTION_BLOCK",
        "FUNCTION_BLOCK B ACTION A: VAR x : INT; END_VAR END_ACTION END_FUNCTION_BLOCK",
        "FUNCTION_BLOCK B ACTION A: ACTION C: END_ACTION END_ACTION END_FUNCTION_BLOCK",
        "FUNCTION_BLOCK B METHOD M ACTION A: END_ACTION END_METHOD END_FUNCTION_BLOCK",
        "FUNCTION_BLOCK B ACTION A: END_FUNCTION_BLOCK",
        "PROGRAM P ACTION A: END_ACTION x := 1; END_PROGRAM",
    ],
)
def test_malformed_and_nested_action_scopes_are_rejected(source):
    with pytest.raises(ParseError):
        parse(source)
