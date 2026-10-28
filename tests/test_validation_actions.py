"""Action lookup, owner contracts and mixed recursion are checked before execution."""

import pytest

from tc_emulator import ValidationError
from tc_emulator.parser import parse
from tc_emulator.validation import validate


def check(source):
    return validate(parse(source, "actions.st"))


def test_local_this_instance_array_and_program_actions_are_resolved():
    registry = check("""FUNCTION_BLOCK B
VAR_INPUT amount : INT; END_VAR VAR_OUTPUT n : INT; END_VAR
Add(); THIS^.Add();
ACTION Add: n := n + amount; END_ACTION END_FUNCTION_BLOCK
PROGRAM Main VAR fb : B; items : ARRAY[1..2] OF B; END_VAR
fb.Add(amount := 2); items[2].Add();
ACTION Run: fb.Add(); END_ACTION END_PROGRAM
PROGRAM Other Main.Run(); END_PROGRAM""")
    assert registry["B.ADD"].kind == "ACTION"
    assert registry.action_for("B", "ADD").name == "B.ADD"
    assert len(registry.action_calls) == 6


@pytest.mark.parametrize("body", ["n := Add();", "n := THIS^.Add();"])
def test_action_cannot_be_used_as_a_value(body):
    with pytest.raises(ValidationError, match="[Aa]ction.*expression"):
        check(f"""FUNCTION_BLOCK B VAR n : INT; END_VAR {body}
ACTION Add: END_ACTION END_FUNCTION_BLOCK""")


@pytest.mark.parametrize(
    "declarations,members",
    [
        ("", "ACTION Add: END_ACTION ACTION Add: END_ACTION"),
        ("VAR Add : INT; END_VAR", "ACTION Add: END_ACTION"),
        ("", "METHOD Add END_METHOD ACTION Add: END_ACTION"),
        ("", "PROPERTY Add : INT GET Add := 1; END_GET END_PROPERTY ACTION Add: END_ACTION"),
    ],
)
def test_action_names_cannot_collide_with_local_members(declarations, members):
    with pytest.raises(ValidationError, match="[Dd]uplicate|collision"):
        check(f"FUNCTION_BLOCK B {declarations} {members} END_FUNCTION_BLOCK")


@pytest.mark.parametrize(
    "base,derived",
    [
        ("ACTION Add: END_ACTION", "VAR Add : INT; END_VAR"),
        ("ACTION Add: END_ACTION", "METHOD Add END_METHOD"),
        ("VAR Add : INT; END_VAR", "ACTION Add: END_ACTION"),
        ("METHOD Add END_METHOD", "ACTION Add: END_ACTION"),
        ("PROPERTY Add : INT GET Add := 1; END_GET END_PROPERTY", "ACTION Add: END_ACTION"),
    ],
)
def test_inherited_action_member_kind_collisions_are_rejected(base, derived):
    with pytest.raises(ValidationError, match="collision"):
        check(
            f"FUNCTION_BLOCK A {base} END_FUNCTION_BLOCK\n"
            f"FUNCTION_BLOCK B EXTENDS A {derived} END_FUNCTION_BLOCK"
        )


@pytest.mark.parametrize(
    "body,expected",
    [
        ("fb.Add();", "Missing required parameter SHARED"),
        ("fb.Add(shared := value, amount := TRUE);", "expected|Expected"),
        ("fb.Add(value);", "named arguments"),
        ("fb.Add(shared := value, n := value);", "requires =>"),
        ("fb.Add(shared := value, missing := 1);", "Unknown parameter"),
        ("fb.Add(shared := value, amount := 1, AMOUNT := 2);", "Duplicate"),
    ],
)
def test_external_action_calls_use_owner_named_parameter_rules(body, expected):
    with pytest.raises(ValidationError, match=expected):
        check(f"""FUNCTION_BLOCK B VAR_INPUT amount : INT; END_VAR
VAR_IN_OUT shared : INT; END_VAR VAR_OUTPUT n : INT; END_VAR
ACTION Add: shared := shared + amount; n := shared; END_ACTION END_FUNCTION_BLOCK
PROGRAM P VAR fb : B; value : INT; END_VAR {body} END_PROGRAM""")


def test_local_action_inout_alias_is_reused_and_unused_actions_are_checked():
    check("""FUNCTION_BLOCK B VAR_IN_OUT shared : INT; END_VAR
Add(); THIS^.Add();
ACTION Add: shared := shared + 1; END_ACTION END_FUNCTION_BLOCK""")
    with pytest.raises(ValidationError, match="Unknown reference"):
        check("FUNCTION_BLOCK B ACTION Unused: missing := 1; END_ACTION END_FUNCTION_BLOCK")


@pytest.mark.parametrize(
    "source",
    [
        "FUNCTION_BLOCK B ACTION A: A(); END_ACTION END_FUNCTION_BLOCK",
        "PROGRAM P Run(); ACTION Run: P(); END_ACTION END_PROGRAM",
        "FUNCTION_BLOCK B METHOD M A(); END_METHOD ACTION A: M(); END_ACTION END_FUNCTION_BLOCK",
        "FUNCTION_BLOCK B VAR x : INT; END_VAR PROPERTY V : INT GET A(); V := 1; END_GET END_PROPERTY ACTION A: x := V; END_ACTION END_FUNCTION_BLOCK",
        "FUNCTION_BLOCK A ACTION Outer: Hook(); END_ACTION ACTION Hook: END_ACTION END_FUNCTION_BLOCK FUNCTION_BLOCK B EXTENDS A ACTION Hook: Outer(); END_ACTION END_FUNCTION_BLOCK",
    ],
)
def test_cycles_across_actions_body_methods_properties_and_virtual_calls_are_rejected(source):
    with pytest.raises(ValidationError, match="Recursive call"):
        check(source)


def test_temporary_child_initialization_cycle_through_an_action_is_rejected():
    with pytest.raises(ValidationError, match="Recursive call"):
        check("""FUNCTION_BLOCK B VAR_TEMP child : C; END_VAR
ACTION A: END_ACTION END_FUNCTION_BLOCK
FUNCTION_BLOCK C METHOD FB_init : BOOL
VAR_INPUT bInitRetains : BOOL; bInCopyCode : BOOL; END_VAR
MAIN.fb.A(); FB_init := TRUE; END_METHOD END_FUNCTION_BLOCK
PROGRAM Main VAR fb : B; END_VAR END_PROGRAM""")


def test_external_inherited_action_requires_derived_receiver_inout_parameters():
    with pytest.raises(ValidationError, match="Missing required parameter EXTRA"):
        check("""FUNCTION_BLOCK A ACTION Add: END_ACTION END_FUNCTION_BLOCK
FUNCTION_BLOCK B EXTENDS A VAR_IN_OUT extra : INT; END_VAR END_FUNCTION_BLOCK
PROGRAM P VAR fb : B; END_VAR fb.Add(); END_PROGRAM""")


@pytest.mark.parametrize(
    "source",
    [
        "PROGRAM P THIS^.Add(); ACTION Add: END_ACTION END_PROGRAM",
        "PROGRAM P ACTION Add: THIS^.Add(); END_ACTION END_PROGRAM",
        "PROGRAM P ACTION Add: END_ACTION END_PROGRAM FUNCTION F : INT P.Add(); F := 1; END_FUNCTION",
    ],
)
def test_actions_preserve_fb_only_this_and_function_to_program_restrictions(source):
    with pytest.raises(ValidationError, match="FUNCTION_BLOCK|FUNCTION cannot.*PROGRAM"):
        check(source)
