"""Native inheritance import preserves source sections and strict XML boundaries."""

import pytest

from tc_emulator import syntax
from tc_emulator.errors import ParseError
from tc_emulator.loader import load_files


def owner_xml(
    declaration="FUNCTION_BLOCK Child EXTENDS Base IMPLEMENTS I_Run", body="", members=""
):
    return (
        '<TcPlcObject><POU Name="Child"><Declaration><![CDATA['
        f"{declaration}]]></Declaration><Implementation><ST><![CDATA[{body}]]></ST>"
        f"</Implementation>{members}</POU></TcPlcObject>"
    )


def method_xml(declaration="METHOD PROTECTED Run", body="SUPER^.Run();"):
    return (
        '<Method Name="Run"><Declaration><![CDATA['
        f"{declaration}]]></Declaration><Implementation><ST><![CDATA[{body}]]></ST>"
        "</Implementation></Method>"
    )


def property_xml(
    declaration="PROPERTY PROTECTED Value : INT",
    getter="GET PROTECTED",
    get_body="Value := SUPER^.Value;",
    setter="SET PRIVATE",
):
    return (
        '<Property Name="Value"><Declaration><![CDATA['
        f"{declaration}]]></Declaration><Get><Declaration><![CDATA[{getter}]]></Declaration>"
        f"<Implementation><ST><![CDATA[{get_body}]]></ST></Implementation></Get>"
        f"<Set><Declaration><![CDATA[{setter}]]></Declaration>"
        "<Implementation><ST><![CDATA[SUPER^.Value := Value;]]></ST></Implementation></Set>"
        "</Property>"
    )


def load_xml(tmp_path, text, extension="TcPOU"):
    path = tmp_path / f"Child.{extension}"
    path.write_text(text, encoding="utf-8")
    return load_files([path])


def test_tcpou_inheritance_members_and_super_preserve_local_source_sections(tmp_path):
    owner = load_xml(
        tmp_path,
        owner_xml(
            declaration="\nFUNCTION_BLOCK Child EXTENDS Base IMPLEMENTS I_Run",
            body="\n  SUPER^();",
            members=method_xml("\nMETHOD PROTECTED Run", "\n SUPER^.Run();")
            + property_xml(
                "\nPROPERTY PROTECTED Value : INT", "\nGET PROTECTED", "\nValue := SUPER^.Value;"
            ),
        ),
    ).pous[0]
    assert owner.extends == "BASE" and owner.implements == ("I_RUN",)
    assert owner.loc.source.endswith("Child.TcPOU:Declaration") and owner.loc.line == 2
    assert isinstance(owner.body[0].call.target, syntax.Super)
    assert owner.body[0].call.loc.source.endswith("Child.TcPOU:Implementation")
    assert (owner.body[0].call.loc.line, owner.body[0].call.loc.column) == (2, 3)
    method = owner.methods[0]
    assert method.name == "CHILD.RUN" and method.owner == "CHILD" and method.access == "PROTECTED"
    assert method.loc.source.endswith(":Method:Run:Declaration") and method.loc.line == 2
    assert method.body[0].call.target.base.loc.source.endswith(":Method:Run:Implementation")
    assert (method.body[0].call.loc.line, method.body[0].call.loc.column) == (2, 2)
    prop = owner.properties[0]
    assert prop.access == prop.getter.access == "PROTECTED" and prop.setter.access == "PRIVATE"
    assert prop.getter.name == "CHILD.VALUE.GET" and prop.setter.owner == "CHILD"
    assert prop.loc.source.endswith(":Property:Value:Declaration") and prop.loc.line == 2
    assert prop.getter.loc.source.endswith(":Property:Value:Get:Declaration")
    assert prop.getter.loc.line == 2
    assert prop.getter.body[0].value.base.loc.source.endswith(":Property:Value:Get:Implementation")
    assert (prop.getter.body[0].value.loc.line, prop.getter.body[0].value.loc.column) == (2, 10)
    assert isinstance(prop.setter.body[0].target.base, syntax.Super)


def test_tcpou_can_load_before_its_base_without_changing_declaration_owners(tmp_path):
    child = tmp_path / "Child.TcPOU"
    child.write_text(owner_xml(members=method_xml()), encoding="utf-8")
    base = tmp_path / "Base.ST"
    base.write_text(
        "FUNCTION_BLOCK Base METHOD Run END_METHOD END_FUNCTION_BLOCK", encoding="utf-8"
    )
    program = load_files([child, base])
    assert [p.name for p in program.pous] == ["CHILD", "BASE"]
    assert program.pous[0].extends == "BASE" and program.pous[1].extends is None
    assert [p.methods[0].owner for p in program.pous] == ["CHILD", "BASE"]


@pytest.mark.parametrize(
    "text",
    [
        owner_xml("PROGRAM Child EXTENDS Base"),
        owner_xml("FUNCTION Child EXTENDS Base : INT"),
        owner_xml("FUNCTION_BLOCK Child EXTENDS Base, Other"),
        owner_xml("FUNCTION_BLOCK Child EXTENDS Base EXTENDS Other"),
        owner_xml("FUNCTION_BLOCK FINAL Child EXTENDS Base"),
        owner_xml(members=method_xml("METHOD PROTECTED PRIVATE Run")),
        owner_xml(members=property_xml("PROPERTY PROTECTED PRIVATE Value : INT")),
        owner_xml(members=property_xml(getter="GET PROTECTED PRIVATE")),
        owner_xml("FUNCTION_BLOCK Child EXTENDS Base\nSUPER^();"),
        owner_xml("FUNCTION_BLOCK Child EXTENDS Base METHOD Hidden END_METHOD"),
        owner_xml(body="SUPER^(); END_FUNCTION_BLOCK FUNCTION_BLOCK Injected"),
        owner_xml(body="VAR hidden : INT; END_VAR SUPER^();"),
        owner_xml(members=method_xml(body="END_METHOD METHOD Hidden")),
        owner_xml(members=property_xml(get_body="END_GET SET END_SET")),
        owner_xml().replace('Name="Child"', 'Name="Other"'),
        owner_xml().replace("<POU Name=", '<POU Extends="Base" Name='),
        owner_xml().replace("<ST>", "<ST><Unexpected/>"),
    ],
)
def test_tcpou_rejects_invalid_inheritance_and_declaration_injection(tmp_path, text):
    with pytest.raises(ParseError) as caught:
        load_xml(tmp_path, text)
    assert "Child.TcPOU" in caught.value.loc.source


@pytest.mark.parametrize(
    "header,member",
    [
        ("INTERFACE I EXTENDS I_Base", ""),
        (
            "INTERFACE I",
            '<Method Name="Run"><Declaration>METHOD PROTECTED Run</Declaration></Method>',
        ),
        (
            "INTERFACE I",
            '<Property Name="P"><Declaration>PROPERTY PROTECTED P : INT</Declaration>'
            "<Get><Declaration/></Get></Property>",
        ),
        (
            "INTERFACE I",
            '<Property Name="P"><Declaration>PROPERTY P : INT</Declaration>'
            "<Get><Declaration>GET PROTECTED</Declaration></Get></Property>",
        ),
    ],
)
def test_tcio_keeps_rejecting_inheritance_and_nonpublic_contracts(tmp_path, header, member):
    text = (
        f'<TcPlcObject><Itf Name="I"><Declaration>{header}</Declaration>'
        f"{member}</Itf></TcPlcObject>"
    )
    with pytest.raises(ParseError):
        load_xml(tmp_path, text, "TcIO")


@pytest.mark.parametrize(
    "declaration,body,members,suffix,line,column",
    [
        ("\nPROGRAM Child EXTENDS Base", "", "", ":Declaration", 2, 15),
        ("FUNCTION_BLOCK Child EXTENDS Base", "\nSUPER.Run();", "", ":Implementation", 2, 6),
        (
            "FUNCTION_BLOCK Child EXTENDS Base",
            "",
            method_xml("METHOD PROTECTED Run", "\nSUPER.Run();"),
            ":Method:Run:Implementation",
            2,
            6,
        ),
    ],
)
def test_inheritance_syntax_errors_keep_original_xml_section_coordinates(
    tmp_path, declaration, body, members, suffix, line, column
):
    with pytest.raises(ParseError) as caught:
        load_xml(tmp_path, owner_xml(declaration, body, members))
    assert caught.value.loc.source.endswith(suffix)
    assert (caught.value.loc.line, caught.value.loc.column) == (line, column)
