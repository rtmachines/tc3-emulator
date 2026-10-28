"""Native TcPOU initialization declarations preserve section locations."""

import pytest

from tc_emulator.errors import ParseError
from tc_emulator.loader import load_files
from tc_emulator.syntax import ArrayInitializer, Location, StructInitializer

ATTRIBUTE = "{attribute 'call_after_init'}"


def tcpou(declaration, methods="", body=""):
    return (
        '<TcPlcObject><POU Name="Motor"><Declaration><![CDATA['
        f"{declaration}]]></Declaration><Implementation><ST><![CDATA[{body}]]></ST>"
        f"</Implementation>{methods}</POU></TcPlcObject>"
    )


def method(declaration, body=""):
    return (
        '<Method Name="Ready"><Declaration><![CDATA['
        f"{declaration}]]></Declaration><Implementation><ST><![CDATA[{body}]]></ST>"
        "</Implementation></Method>"
    )


def load_native(tmp_path, text):
    path = tmp_path / "Motor.TcPOU"
    path.write_text(text, encoding="utf-8")
    return path, load_files([path]).pous[0]


def test_tcpou_preserves_fb_and_method_attributes_and_original_section_locations(tmp_path):
    path, owner = load_native(
        tmp_path,
        tcpou(
            ATTRIBUTE + "\nFUNCTION_BLOCK Motor\nVAR count : INT; END_VAR",
            method(ATTRIBUTE + "\nMETHOD Ready : BOOL", "\nReady := TRUE;"),
            "\ncount := 1;",
        ),
    )
    assert owner.call_after_init is True
    assert owner.loc == Location(f"{path}:Declaration", 2, 1)
    assert owner.variables[0].loc == Location(f"{path}:Declaration", 3, 5)
    assert owner.body[0].loc == Location(f"{path}:Implementation", 2, 1)
    ready = owner.methods[0]
    assert ready.call_after_init is True
    assert ready.loc == Location(f"{path}:Method:Ready:Declaration", 2, 1)
    assert ready.body[0].loc == Location(f"{path}:Method:Ready:Implementation", 2, 1)


def test_tcpou_marked_method_in_plain_owner_is_retained_for_semantic_validation(tmp_path):
    _, owner = load_native(
        tmp_path,
        tcpou("FUNCTION_BLOCK Motor", method(ATTRIBUTE + "\nMETHOD Ready")),
    )
    assert owner.call_after_init is False
    assert owner.methods[0].call_after_init is True


def test_tcpou_argument_and_post_init_locations_stay_in_declaration_section(tmp_path):
    path, owner = load_native(
        tmp_path,
        tcpou(
            ATTRIBUTE + "\nFUNCTION_BLOCK Motor\nVAR\n"
            "  child : Child(id := config.axis) := (enabled := TRUE);\n"
            "  children : ARRAY[1..2] OF Child[(id := 1), (id := 2)] := [(enabled := FALSE)];\n"
            "END_VAR"
        ),
    )
    child, children = owner.variables
    assert child.init_arguments[0].loc == Location(f"{path}:Declaration", 4, 17)
    assert child.init_arguments[0].value.loc == Location(f"{path}:Declaration", 4, 23)
    assert isinstance(child.initial, StructInitializer)
    assert child.initial.loc == Location(f"{path}:Declaration", 4, 39)
    assert [args[0].value.value for args in children.element_init_arguments] == [1, 2]
    assert children.element_init_arguments[1][0].loc == Location(f"{path}:Declaration", 5, 47)
    assert isinstance(children.initial, ArrayInitializer)


@pytest.mark.parametrize(
    "declaration,body,section,line,column",
    [
        (
            ATTRIBUTE + "\nMETHOD Ready\nVAR child : Child(id := ); END_VAR",
            "",
            "Declaration",
            3,
            25,
        ),
        (ATTRIBUTE + "\nMETHOD Ready", "\nReady := @;", "Implementation", 2, 10),
    ],
)
def test_tcpou_marked_method_errors_keep_section_positions(
    tmp_path, declaration, body, section, line, column
):
    path = tmp_path / "Motor.TcPOU"
    path.write_text(tcpou("FUNCTION_BLOCK Motor", method(declaration, body)), encoding="utf-8")
    with pytest.raises(ParseError) as caught:
        load_files([path])
    assert caught.value.loc == Location(f"{path}:Method:Ready:{section}", line, column)


@pytest.mark.parametrize(
    "declaration,methods,body",
    [
        (ATTRIBUTE + "\nPROGRAM Motor", "", ""),
        (ATTRIBUTE + "\nFUNCTION Motor : BOOL", "", ""),
        ("{attribute 'unknown'}\nFUNCTION_BLOCK Motor", "", ""),
        (ATTRIBUTE + "\n" + ATTRIBUTE + "\nFUNCTION_BLOCK Motor", "", ""),
        ("FUNCTION_BLOCK Motor", method(ATTRIBUTE + "\nPROPERTY Ready : BOOL"), ""),
        ("FUNCTION_BLOCK Motor", method("METHOD Ready", ATTRIBUTE), ""),
        (ATTRIBUTE + "\nFUNCTION_BLOCK Motor", "", ATTRIBUTE + "\nMETHOD Ready END_METHOD"),
        (ATTRIBUTE + "\nFUNCTION_BLOCK Motor", method(ATTRIBUTE + "\nMETHOD Wrong"), ""),
        (ATTRIBUTE + "\nFUNCTION_BLOCK Motor\nMETHOD Hidden END_METHOD", "", ""),
    ],
)
def test_tcpou_attributes_do_not_bypass_declaration_or_metadata_boundaries(
    tmp_path, declaration, methods, body
):
    path = tmp_path / "Motor.TcPOU"
    path.write_text(tcpou(declaration, methods, body), encoding="utf-8")
    with pytest.raises(ParseError):
        load_files([path])
