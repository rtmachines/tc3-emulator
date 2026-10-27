import pytest

from tc_emulator.errors import ParseError
from tc_emulator.loader import load_files


def xml(
    declaration="FUNCTION_BLOCK Counter\nVAR_OUTPUT count : DINT; END_VAR",
    body="count := count + 1;",
    extra="",
    implementation=None,
):
    implementation = f"<ST><![CDATA[{body}]]></ST>" if implementation is None else implementation
    return f'<TcPlcObject Version="1.1.0.1" ProductVersion="3.1"><POU Name="Counter" Id="abc"><Declaration><![CDATA[{declaration}]]></Declaration><Implementation>{implementation}</Implementation>{extra}</POU></TcPlcObject>'


def test_load_st_and_tcpou_with_section_locations(tmp_path):
    first = tmp_path / "a.st"
    first.write_text("FUNCTION f : INT f := 1; END_FUNCTION", encoding="utf-8")
    second = tmp_path / "Counter.TcPOU"
    second.write_text(xml(body="\ncount := count + 1;"), encoding="utf-8")
    program = load_files([first, str(second)])
    assert [p.name for p in program.pous] == ["F", "COUNTER"]
    assert program.pous[1].variables[0].loc.source.endswith(":Declaration")
    assert program.pous[1].body[0].loc.source.endswith(":Implementation")
    assert program.pous[1].body[0].loc.line == 2


@pytest.mark.parametrize(
    "contents",
    [
        "<broken",
        xml(extra='<Method Name="M"/>'),
        xml(extra='<Action Name="A"/>'),
        xml(extra='<Property Name="P"/>'),
        xml(implementation="<FBD/>"),
        xml(implementation="<ST/><SFC/>"),
        xml(extra="<UnknownSemantic/>"),
        xml(declaration="PROGRAM Counter : INT"),
        '<TcPlcObject><POU Name="Counter"><Declaration>FUNCTION_BLOCK Counter</Declaration></POU></TcPlcObject>',
        xml().replace("<ST>", "<ST><Unknown/>").replace("</ST>", "</ST>"),
        xml().replace('Name="Counter"', 'Name="Mismatch"'),
    ],
)
def test_rejects_malformed_xml_and_unsupported_semantics(tmp_path, contents):
    path = tmp_path / "bad.TcPOU"
    path.write_text(contents, encoding="utf-8")
    with pytest.raises(ParseError):
        load_files([path])


def test_tcpou_syntax_error_maps_to_original_section(tmp_path):
    path = tmp_path / "bad.TcPOU"
    path.write_text(xml(body="\ncount := @;"), encoding="utf-8")
    with pytest.raises(ParseError) as caught:
        load_files([path])
    assert caught.value.loc.source == f"{path}:Implementation"
    assert (caught.value.loc.line, caught.value.loc.column) == (2, 10)


def test_unknown_extension_and_read_error_are_source_aware(tmp_path):
    path = tmp_path / "missing.st"
    with pytest.raises(ParseError, match="missing.st"):
        load_files([path])
    path = tmp_path / "source.xml"
    path.write_text(xml(), encoding="utf-8")
    with pytest.raises(ParseError):
        load_files([path])


def test_tcpou_implementation_cannot_inject_another_pou(tmp_path):
    path = tmp_path / "injected.TcPOU"
    path.write_text(
        xml(
            declaration="FUNCTION Counter : INT",
            body="Counter := 1; END_FUNCTION FUNCTION Hidden : INT Hidden := 2;",
        ),
        encoding="utf-8",
    )
    with pytest.raises(ParseError) as caught:
        load_files([path])
    assert caught.value.loc.source == f"{path}:Implementation"


def test_tcpou_implementation_cannot_add_variable_declarations(tmp_path):
    path = tmp_path / "injected.TcPOU"
    path.write_text(
        xml(
            declaration="FUNCTION Counter : INT",
            body="VAR hidden : INT := 7; END_VAR Counter := hidden;",
        ),
        encoding="utf-8",
    )
    with pytest.raises(ParseError) as caught:
        load_files([path])
    assert caught.value.loc.source == f"{path}:Implementation"
