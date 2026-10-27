"""Native XML imports preserve references and their original source sections."""

import pytest

from tc_emulator import Runtime
from tc_emulator import syntax as st
from tc_emulator.errors import ExecutionError, ParseError, ValidationError
from tc_emulator.loader import load_files


def test_tcpou_preserves_reference_declaration_binding_and_validity_call_locations(tmp_path):
    path = tmp_path / "Consumer.TcPOU"
    path.write_text(
        '<TcPlcObject><POU Name="Consumer"><Declaration><![CDATA['
        "\nFUNCTION_BLOCK Consumer\nVAR_INPUT\n  cfg : REFERENCE TO Config := 0;\nEND_VAR"
        "]]></Declaration><Implementation><ST><![CDATA["
        "\n  cfg ref= Shared.config;\n  ok := __ISVALIDREF(cfg);"
        "]]></ST></Implementation></POU></TcPlcObject>",
        encoding="utf-8",
    )
    pou = load_files([path]).pous[0]
    declaration = pou.variables[0]
    assert isinstance(declaration.type_name, st.ReferenceSpec)
    assert declaration.type_name.target == "CONFIG" and declaration.initial.value == 0
    assert declaration.type_name.loc == st.Location(f"{path}:Declaration", 4, 9)
    binding = pou.body[0]
    assert isinstance(binding, st.RefAssign) and binding.value.parts == ("SHARED", "CONFIG")
    assert binding.loc == st.Location(f"{path}:Implementation", 2, 3)
    assert binding.value.loc == st.Location(f"{path}:Implementation", 2, 12)
    call = pou.body[1].value
    assert isinstance(call, st.Call) and call.target.parts == ("__ISVALIDREF",)
    assert call.loc == st.Location(f"{path}:Implementation", 3, 9)


def test_tcgvl_preserves_both_reference_initializer_spellings_and_source_labels(tmp_path):
    path = tmp_path / "Shared.TcGVL"
    path.write_text(
        '<TcPlcObject><GVL Name="Shared"><Declaration><![CDATA['
        "\nVAR_GLOBAL\n  a : REFERENCE TO INT REF= number;\n"
        "  b : REFERENCE TO INT := number;\n  number : INT := 7;\nEND_VAR"
        "]]></Declaration></GVL></TcPlcObject>",
        encoding="utf-8",
    )
    gvl = load_files([path]).gvls[0]
    assert gvl.name == "SHARED"
    first, second, number = gvl.variables
    for line, declaration in ((3, first), (4, second)):
        assert isinstance(declaration.type_name, st.ReferenceSpec)
        assert declaration.type_name.target == "INT"
        assert declaration.type_name.loc == st.Location(f"{path}:Declaration", line, 7)
        assert declaration.initial.parts == ("NUMBER",)
    assert first.initial.loc == st.Location(f"{path}:Declaration", 3, 29)
    assert second.initial.loc == st.Location(f"{path}:Declaration", 4, 27)
    assert number.initial.value == 7


@pytest.mark.parametrize(
    "extension,xml,suffix,line,column",
    [
        (
            "TcPOU",
            '<TcPlcObject><POU Name="P"><Declaration>FUNCTION_BLOCK P</Declaration>'
            "<Implementation><ST>\n  r REF=;</ST></Implementation></POU></TcPlcObject>",
            "Implementation",
            2,
            9,
        ),
        (
            "TcGVL",
            '<TcPlcObject><GVL Name="P"><Declaration>VAR_GLOBAL\n'
            "  r : REFERENCE INT;\nEND_VAR</Declaration></GVL></TcPlcObject>",
            "Declaration",
            2,
            17,
        ),
    ],
)
def test_reference_parse_errors_keep_xml_section_coordinates(
    tmp_path, extension, xml, suffix, line, column
):
    path = tmp_path / f"P.{extension}"
    path.write_text(xml, encoding="utf-8")
    with pytest.raises(ParseError) as caught:
        load_files([path])
    assert caught.value.loc == st.Location(f"{path}:{suffix}", line, column)


def test_native_reference_initializers_and_execution_error_locations(tmp_path):
    globals_path = tmp_path / "Shared.TcGVL"
    globals_path.write_text(
        '<TcPlcObject><GVL Name="Shared"><Declaration><![CDATA['
        "VAR_GLOBAL ref : REFERENCE TO INT := data; data : INT := 7; END_VAR"
        "]]></Declaration></GVL></TcPlcObject>",
        encoding="utf-8",
    )
    path = tmp_path / "Consumer.TcPOU"
    path.write_text(
        '<TcPlcObject><POU Name="Consumer"><Declaration><![CDATA['
        "FUNCTION_BLOCK Consumer\nVAR_OUTPUT value : INT; END_VAR"
        "]]></Declaration><Implementation><ST><![CDATA["
        "value := Shared.ref;\nShared.ref REF= 0;\nvalue := Shared.ref;"
        "]]></ST></Implementation></POU></TcPlcObject>",
        encoding="utf-8",
    )
    rt = Runtime.from_files([path, globals_path])
    fb = rt.instantiate("Consumer")
    with pytest.raises(ExecutionError, match="Null") as caught:
        fb.call()
    assert fb.output("value") == 7
    assert caught.value.loc.source == f"{path}:Implementation"
    assert caught.value.loc.line == 3
    assert caught.value.stack == ("CONSUMER",)


def test_native_reference_binding_validation_error_coordinates(tmp_path):
    path = tmp_path / "Bad.TcPOU"
    path.write_text(
        '<TcPlcObject><POU Name="Bad"><Declaration><![CDATA['
        "FUNCTION_BLOCK Bad\nVAR r : REFERENCE TO INT; x : DINT; END_VAR"
        "]]></Declaration><Implementation><ST><![CDATA[\nr REF= x;"
        "]]></ST></Implementation></POU></TcPlcObject>",
        encoding="utf-8",
    )
    with pytest.raises(ValidationError, match="exact type") as caught:
        Runtime.from_files([path])
    assert caught.value.loc == st.Location(f"{path}:Implementation", 2, 8)
