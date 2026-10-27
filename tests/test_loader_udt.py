"""Narrow TcDUT wrappers and cross-file TYPE/POU merging."""

import pytest

from tc_emulator.errors import ParseError
from tc_emulator.loader import load_files


def dut(declaration="TYPE Config : STRUCT speed : INT; END_STRUCT; END_TYPE", name="Config"):
    return (
        '<TcPlcObject Version="1.1.0.1" ProductVersion="3.1">'
        f'<DUT Name="{name}" Id="abc"><Declaration><![CDATA[{declaration}]]>'
        "</Declaration></DUT></TcPlcObject>"
    )


def test_merges_types_and_pous_from_st_and_tcdut_with_source_locations(tmp_path):
    types = tmp_path / "config.TcDUT"
    types.write_text(dut("\nTYPE Config : STRUCT\n speed : INT := 3;\nEND_STRUCT; END_TYPE"))
    st = tmp_path / "code.st"
    st.write_text("FUNCTION F : Config END_FUNCTION TYPE Alias : Config; END_TYPE")
    program = load_files([types, st])
    assert [decl.name for decl in program.types] == ["CONFIG", "ALIAS"]
    assert [pou.name for pou in program.pous] == ["F"]
    assert program.types[0].loc.source == f"{types}:Declaration"
    assert program.types[0].loc.line == 2
    assert program.types[0].definition.fields[0].loc.line == 3


@pytest.mark.parametrize(
    "contents",
    [
        "<broken",
        dut(name="Mismatch"),
        dut().replace(' Name="Config"', ""),
        dut().replace("<DUT Name=", '<DUT Extra="1" Name='),
        dut().replace("<Declaration>", '<Declaration Extra="1">'),
        dut().replace("</DUT>", "<Implementation><ST/></Implementation></DUT>"),
        dut().replace("</DUT>", "<Method/></DUT>"),
        dut().replace("</TcPlcObject>", '<DUT Name="Other"/></TcPlcObject>'),
        dut().replace("</Declaration>", "<Nested/></Declaration>"),
        dut().replace("<DUT Name=", "junk<DUT Name="),
        dut().replace("</Declaration>", "</Declaration>junk"),
        dut("TYPE Config : INT; Other : INT; END_TYPE"),
        dut("TYPE Config : INT; END_TYPE TYPE Other : INT; END_TYPE"),
        dut("TYPE Config : INT; END_TYPE FUNCTION F : INT END_FUNCTION"),
        dut("FUNCTION Config : INT END_FUNCTION"),
        '<!DOCTYPE TcPlcObject [<!ENTITY x "junk">]>' + dut(),
        dut().replace("<TcPlcObject ", '<TcPlcObject xmlns="urn:other" '),
    ],
)
def test_tcdut_rejects_extra_objects_metadata_and_xml_semantics(tmp_path, contents):
    path = tmp_path / "bad.TcDUT"
    path.write_text(contents)
    with pytest.raises(ParseError):
        load_files([path])


def test_tcdut_parse_errors_keep_declaration_source_position(tmp_path):
    path = tmp_path / "bad.TcDUT"
    path.write_text(dut("\nTYPE Config : STRUCT\n speed : @;\nEND_STRUCT; END_TYPE"))
    with pytest.raises(ParseError) as caught:
        load_files([path])
    assert caught.value.loc.source == f"{path}:Declaration"
    assert (caught.value.loc.line, caught.value.loc.column) == (3, 10)


@pytest.mark.parametrize("section", ["Declaration", "Implementation"])
def test_tcpou_cannot_hide_types_even_when_only_one_pou_remains(tmp_path, section):
    declaration = "FUNCTION F : INT"
    body = "F := 1;"
    if section == "Declaration":
        declaration += " END_FUNCTION TYPE Hidden : INT; END_TYPE FUNCTION F : INT"
    else:
        body += " END_FUNCTION TYPE Hidden : INT; END_TYPE FUNCTION HiddenF : INT"
    contents = (
        '<TcPlcObject><POU Name="F"><Declaration><![CDATA['
        + declaration
        + "]]></Declaration><Implementation><ST><![CDATA["
        + body
        + "]]></ST></Implementation></POU></TcPlcObject>"
    )
    path = tmp_path / "hidden.TcPOU"
    path.write_text(contents)
    with pytest.raises(ParseError):
        load_files([path])
