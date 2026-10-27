"""TcPOU method import must preserve each source section and reject injection."""

import pytest

from tc_emulator.errors import ParseError
from tc_emulator.loader import load_files


def method_xml(
    name="Read", declaration="METHOD PUBLIC Read : INT", body="Read := total;", extra=""
):
    return (
        f'<Method Name="{name}" Id="method-id"><Declaration><![CDATA[{declaration}]]>'
        f"</Declaration><Implementation><ST><![CDATA[{body}]]></ST></Implementation>{extra}</Method>"
    )


def owner_xml(
    methods, declaration="FUNCTION_BLOCK Motor\nVAR total : INT; END_VAR", body="total := 1;"
):
    return (
        '<TcPlcObject><POU Name="Motor" Id="owner-id"><Declaration><![CDATA['
        f"{declaration}]]></Declaration><Implementation><ST><![CDATA[{body}]]></ST>"
        f"</Implementation>{methods}</POU></TcPlcObject>"
    )


def load_xml(tmp_path, text):
    path = tmp_path / "Motor.TcPOU"
    path.write_text(text, encoding="utf-8")
    return load_files([path])


def test_tcpou_imports_nested_methods_with_separate_owner_and_method_bodies(tmp_path):
    text = owner_xml(
        method_xml(
            declaration="METHOD Read : INT\nVAR_INPUT amount : INT := 3; END_VAR",
            body="\nRead := total + amount;",
        )
        + method_xml("Clear", "METHOD PRIVATE Clear", "total := 0;")
    )
    owner = load_xml(tmp_path, text).pous[0]
    assert len(owner.body) == 1
    assert [m.name for m in owner.methods] == ["MOTOR.READ", "MOTOR.CLEAR"]
    method = owner.methods[0]
    assert method.owner == "MOTOR" and method.access == "PUBLIC"
    assert method.return_type == "INT" and method.variables[0].initial.value == 3
    assert method.loc.source.endswith(":Method:Read:Declaration") and method.loc.line == 1
    assert method.variables[0].loc.line == 2
    assert method.body[0].loc.source.endswith(":Method:Read:Implementation")
    assert (method.body[0].loc.line, method.body[0].loc.column) == (2, 1)
    assert owner.methods[1].access == "PRIVATE"


@pytest.mark.parametrize(
    "declaration,body,section,line,column",
    [
        ("METHOD Read : INT\nVAR x : @; END_VAR", "Read := 1;", "Declaration", 2, 9),
        ("METHOD Read : INT", "\nRead := @;", "Implementation", 2, 9),
    ],
)
def test_tcpou_method_syntax_errors_preserve_method_section_positions(
    tmp_path, declaration, body, section, line, column
):
    with pytest.raises(ParseError) as caught:
        load_xml(tmp_path, owner_xml(method_xml(declaration=declaration, body=body)))
    assert caught.value.loc.source.endswith(f":Method:Read:{section}")
    assert (caught.value.loc.line, caught.value.loc.column) == (line, column)


@pytest.mark.parametrize(
    "method",
    [
        '<Method Name="Read"/>',
        method_xml(name="Other"),
        method_xml(name="Read.Extra"),
        method_xml(name="Read "),
        method_xml(declaration="FUNCTION Read : INT"),
        method_xml(declaration="METHOD Read : INT Read := 7;"),
        method_xml(declaration="METHOD Read : INT END_METHOD METHOD Hidden"),
        method_xml(body="VAR hidden : INT; END_VAR Read := 1;"),
        method_xml(body="Read := 1; END_METHOD METHOD Hidden"),
        method_xml(body="Read := 1; END_METHOD END_FUNCTION_BLOCK PROGRAM Injected"),
        method_xml(extra='<Method Name="Nested"/>'),
        method_xml(extra="<Property/>"),
        method_xml().replace("<Method Name=", '<Method Unsupported="yes" Name='),
        method_xml().replace("<Declaration>", '<Declaration Extra="yes">'),
        method_xml().replace("<Implementation>", '<Implementation Extra="yes">'),
        method_xml().replace("<ST>", '<ST Extra="yes">'),
        method_xml().replace("<ST>", "<FBD>").replace("</ST>", "</FBD>"),
        method_xml().replace("</Declaration>", "</Declaration><Declaration/>"),
        method_xml().replace(
            "</Implementation>", "</Implementation><Implementation><ST/></Implementation>"
        ),
        method_xml()
        .replace("<Method Name=", "<Method Name=")
        .replace("<Declaration>", "hidden<Declaration>"),
        method_xml().replace("</Declaration>", "</Declaration>hidden"),
        method_xml().replace("<ST>", "hidden<ST>"),
        method_xml().replace("</ST>", "</ST>hidden"),
        method_xml().replace("<Declaration>", "<Declaration><Unexpected/>"),
        method_xml().replace("<ST>", "<ST><Unexpected/>"),
    ],
)
def test_malformed_method_xml_metadata_sections_and_injection_are_rejected(tmp_path, method):
    with pytest.raises(ParseError):
        load_xml(tmp_path, owner_xml(method))


@pytest.mark.parametrize("declaration", ["PROGRAM Motor", "FUNCTION Motor : INT"])
def test_tcpou_methods_require_a_function_block_owner(tmp_path, declaration):
    with pytest.raises(ParseError):
        load_xml(tmp_path, owner_xml(method_xml(), declaration=declaration, body=""))


@pytest.mark.parametrize(
    "declaration,body",
    [
        ("FUNCTION_BLOCK Motor METHOD Hidden END_METHOD", ""),
        ("FUNCTION_BLOCK Motor", "METHOD Hidden END_METHOD"),
    ],
)
def test_owner_text_sections_cannot_smuggle_methods_outside_xml_metadata(
    tmp_path, declaration, body
):
    with pytest.raises(ParseError):
        load_xml(tmp_path, owner_xml("", declaration=declaration, body=body))


def test_incomplete_method_declaration_error_stays_in_declaration_section(tmp_path):
    with pytest.raises(ParseError) as caught:
        load_xml(tmp_path, owner_xml(method_xml(declaration="METHOD Read :", body="")))
    assert caught.value.loc.source.endswith(":Method:Read:Declaration")
    assert caught.value.loc.line == 2
