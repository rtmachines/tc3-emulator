"""Strict TwinCAT global-list and program import contracts."""

import pytest

from tc_emulator.errors import ParseError
from tc_emulator.loader import load_files


def gvl_xml(declaration="VAR_GLOBAL count : INT := 3; END_VAR", name="Plant"):
    return (
        '<TcPlcObject Version="1.1" ProductVersion="3.1">'
        f'<GVL Name="{name}" Id="abc"><Declaration><![CDATA[{declaration}]]>'
        "</Declaration></GVL></TcPlcObject>"
    )


def test_load_gvl_uses_xml_metadata_and_maps_declaration_location(tmp_path):
    path = tmp_path / "other.TcGVL"
    path.write_text(gvl_xml("{attribute 'qualified_only'}\nVAR_GLOBAL count : INT := 3; END_VAR"))
    program = load_files([path])
    assert program.pous == ()
    assert program.types == ()
    (gvl,) = program.gvls
    assert (gvl.name, gvl.qualified_only) == ("PLANT", True)
    assert gvl.variables[0].initial.value == 3
    assert gvl.variables[0].loc.source == f"{path}:Declaration"
    assert gvl.variables[0].loc.line == 2


def test_st_filenames_name_global_lists_and_merged_order_is_preserved(tmp_path):
    files = []
    for name, declaration in [
        ("Sensors.st", "VAR_GLOBAL signal : BOOL; END_VAR"),
        ("Limits.TcGVL", gvl_xml(name="Bounds")),
        ("Main.st", "PROGRAM Main END_PROGRAM"),
    ]:
        path = tmp_path / name
        path.write_text(declaration)
        files.append(path)
    program = load_files(files)
    assert [gvl.name for gvl in program.gvls] == ["SENSORS", "BOUNDS"]
    assert [pou.name for pou in program.pous] == ["MAIN"]


def test_tcpou_accepts_program_and_preserves_both_section_locations(tmp_path):
    path = tmp_path / "Main.TcPOU"
    path.write_text(
        '<TcPlcObject><POU Name="Main"><Declaration><![CDATA[PROGRAM Main\n'
        "VAR count : INT; END_VAR]]></Declaration><Implementation><ST><![CDATA["
        "\ncount := count + 1;]]></ST></Implementation></POU></TcPlcObject>"
    )
    (pou,) = load_files([path]).pous
    assert (pou.kind, pou.name) == ("PROGRAM", "MAIN")
    assert pou.variables[0].loc.source == f"{path}:Declaration"
    assert pou.body[0].loc.source == f"{path}:Implementation"
    assert pou.body[0].loc.line == 2


@pytest.mark.parametrize(
    "contents",
    [
        "<broken",
        gvl_xml().replace('<GVL Name="Plant"', '<GVL Unknown="1" Name="Plant"'),
        gvl_xml().replace(' Id="abc"', "").replace(' Name="Plant"', ""),
        gvl_xml(name="bad-name"),
        gvl_xml(name="PROGRAM"),
        gvl_xml().replace("<Declaration>", '<Declaration Extra="1">'),
        gvl_xml().replace("<Declaration>", "<Declaration><Nested/>"),
        gvl_xml().replace("</GVL>", "<Implementation><ST/></Implementation></GVL>"),
        gvl_xml().replace("</GVL>", "<Declaration/></GVL>"),
        gvl_xml().replace(
            "</TcPlcObject>", '<GVL Name="Second"><Declaration/></GVL></TcPlcObject>'
        ),
        gvl_xml().replace("<GVL ", "<POU ").replace("</GVL>", "</POU>"),
        gvl_xml().replace("<GVL ", "outside<GVL "),
        gvl_xml().replace("</Declaration>", "</Declaration>outside"),
        gvl_xml().replace('Version="1.1"', 'Unknown="1.1"'),
        "<!DOCTYPE TcPlcObject []>" + gvl_xml(),
        '<!DOCTYPE TcPlcObject [<!ENTITY x "1">]>' + gvl_xml(),
        gvl_xml(""),
        gvl_xml("PROGRAM Main END_PROGRAM"),
        gvl_xml("VAR_GLOBAL x:INT; END_VAR PROGRAM Main END_PROGRAM"),
        gvl_xml("VAR_GLOBAL x:INT; END_VAR TYPE Alias:INT; END_TYPE"),
        gvl_xml("VAR_GLOBAL x:INT; END_VAR x := 3;"),
        gvl_xml("{attribute 'unknown'} VAR_GLOBAL x:INT; END_VAR"),
    ],
)
def test_rejects_malformed_or_executable_gvl_xml(tmp_path, contents):
    path = tmp_path / "bad.TcGVL"
    path.write_text(contents)
    with pytest.raises(ParseError):
        load_files([path])


def test_gvl_syntax_errors_preserve_declaration_line_and_column(tmp_path):
    path = tmp_path / "bad.TcGVL"
    path.write_text(gvl_xml("VAR_GLOBAL\n x : INT := @;\nEND_VAR"))
    with pytest.raises(ParseError) as caught:
        load_files([path])
    assert caught.value.loc.source == f"{path}:Declaration"
    assert (caught.value.loc.line, caught.value.loc.column) == (2, 13)


def test_gvl_cannot_be_hidden_in_tcdut(tmp_path):
    path = tmp_path / "Alias.TcDUT"
    path.write_text(
        '<TcPlcObject><DUT Name="Alias"><Declaration><![CDATA['
        "TYPE Alias:INT; END_TYPE VAR_GLOBAL x:INT; END_VAR"
        "]]></Declaration></DUT></TcPlcObject>"
    )
    with pytest.raises(ParseError):
        load_files([path])


def test_gvl_allows_optional_metadata_and_multiple_global_sections(tmp_path):
    path = tmp_path / "Plant.TcGVL"
    path.write_text(
        '<TcPlcObject><GVL Name="Plant"><Declaration><![CDATA['
        "VAR_GLOBAL END_VAR VAR_GLOBAL CONSTANT limit:INT:=5; END_VAR"
        "]]></Declaration></GVL></TcPlcObject>"
    )
    (gvl,) = load_files([path]).gvls
    assert gvl.name == "PLANT"
    assert [(var.name, var.constant) for var in gvl.variables] == [("LIMIT", True)]


def test_st_global_list_requires_identifier_filename_stem(tmp_path):
    path = tmp_path / "not-valid.st"
    path.write_text("VAR_GLOBAL x:INT; END_VAR")
    with pytest.raises(ParseError):
        load_files([path])
