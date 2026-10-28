"""Native action bodies keep section locations and cannot inject ST objects."""

import pytest

from tc_emulator.errors import ParseError
from tc_emulator.loader import load_files


def action_xml(body="count := count + 1;", name="Add"):
    return (
        f'<Action Name="{name}" Id="action-id"><Implementation><ST><![CDATA[{body}]]>'
        "</ST></Implementation></Action>"
    )


def owner_xml(action, declaration="FUNCTION_BLOCK Motor", body=""):
    return (
        '<TcPlcObject><POU Name="Motor"><Declaration><![CDATA['
        f"{declaration}]]></Declaration><Implementation><ST><![CDATA[{body}]]></ST>"
        f"</Implementation>{action}</POU></TcPlcObject>"
    )


def load_xml(tmp_path, text):
    path = tmp_path / "Motor.TcPOU"
    path.write_text(text, encoding="utf-8")
    return load_files([path])


@pytest.mark.parametrize("kind", ["FUNCTION_BLOCK", "PROGRAM"])
def test_native_action_is_attached_to_owner_with_original_body_location(tmp_path, kind):
    owner = load_xml(
        tmp_path,
        owner_xml(action_xml("\ncount := 2;"), f"{kind} Motor\nVAR count : INT; END_VAR"),
    ).pous[0]
    assert owner.body == ()
    action = owner.actions[0]
    assert action.name == "MOTOR.ADD" and action.owner == "MOTOR"
    assert action.body[0].loc.source.endswith(":Action:Add:Implementation")
    assert (action.body[0].loc.line, action.body[0].loc.column) == (2, 1)


def test_native_action_error_keeps_original_section_position(tmp_path):
    with pytest.raises(ParseError) as caught:
        load_xml(tmp_path, owner_xml(action_xml("\ncount := @;")))
    assert caught.value.loc.source.endswith(":Action:Add:Implementation")
    assert (caught.value.loc.line, caught.value.loc.column) == (2, 10)


@pytest.mark.parametrize(
    "action",
    [
        '<Action Name="Add"/>',
        action_xml(name="Add.Extra"),
        action_xml(name="Add "),
        action_xml("VAR x : INT; END_VAR"),
        action_xml("END_ACTION ACTION Hidden: END_ACTION"),
        action_xml("END_ACTION END_FUNCTION_BLOCK PROGRAM Hidden"),
        action_xml().replace("</Action>", "<Declaration>hidden</Declaration></Action>"),
        action_xml().replace("</Action>", '<Action Name="Nested"/></Action>'),
        action_xml().replace("<Action Name=", '<Action Extra="x" Name='),
        action_xml().replace("<Implementation>", '<Implementation Extra="x">'),
        action_xml().replace("<ST>", '<ST Extra="x">'),
        action_xml().replace("<ST>", "<FBD>").replace("</ST>", "</FBD>"),
        action_xml().replace(
            "</Implementation>", "</Implementation><Implementation><ST/></Implementation>"
        ),
        action_xml().replace("<ST>", "hidden<ST>"),
        action_xml().replace("</ST>", "</ST>hidden"),
        action_xml().replace("<ST>", "<ST><Unexpected/>"),
    ],
)
def test_native_action_rejects_foreign_semantics_and_injection(tmp_path, action):
    with pytest.raises(ParseError):
        load_xml(tmp_path, owner_xml(action))


@pytest.mark.parametrize(
    "declaration,body,actions",
    [
        ("FUNCTION Motor : INT", "", action_xml("")),
        ("FUNCTION_BLOCK Motor ACTION Hidden: END_ACTION", "", ""),
        ("FUNCTION_BLOCK Motor", "ACTION Hidden: END_ACTION", ""),
    ],
)
def test_native_action_requires_owner_and_xml_metadata(tmp_path, declaration, body, actions):
    with pytest.raises(ParseError):
        load_xml(tmp_path, owner_xml(actions, declaration, body))
