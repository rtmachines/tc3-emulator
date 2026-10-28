"""Native enum declarations preserve flags and Declaration-relative locations."""

import pytest

from tc_emulator import Runtime
from tc_emulator.errors import ParseError, ValidationError
from tc_emulator.loader import load_files
from tc_emulator.validation import validate


def dut(text):
    return (
        '<TcPlcObject><DUT Name="E"><Declaration><![CDATA['
        + text
        + "]]></Declaration></DUT></TcPlcObject>"
    )


@pytest.mark.parametrize("order", [("strict", "qualified_only"), ("qualified_only", "strict")])
def test_native_enum_pragmas_keep_metadata_locations_and_cross_file_values(tmp_path, order):
    declaration = "\n" + "\n".join("{attribute '" + name + "'}" for name in order)
    declaration += "\nTYPE E : (Stop, Run := 2) := Run; END_TYPE"
    path = tmp_path / "E.TcDUT"
    path.write_text(dut(declaration))
    code = tmp_path / "code.st"
    code.write_text("FUNCTION F : E F := 1 + 1; END_FUNCTION")
    program = load_files([path, code])
    enum = program.types[0]
    assert (enum.loc.source, enum.loc.line, enum.loc.column) == (f"{path}:Declaration", 4, 6)
    kind = validate(program).types["E"]
    assert (kind.strict, kind.qualified_only, kind.default_member) == (True, True, "RUN")
    result = Runtime(program).call("F").value
    assert (result.type_name, result.name, result.value) == ("E", "RUN", 2)


def test_native_pragma_failure_keeps_original_declaration_line(tmp_path):
    path = tmp_path / "E.TcDUT"
    path.write_text(dut("\n{attribute 'strict'}\n{attribute 'strict'}\nTYPE E : (Stop); END_TYPE"))
    with pytest.raises(ParseError) as caught:
        load_files([path])
    assert (caught.value.loc.source, caught.value.loc.line, caught.value.loc.column) == (
        f"{path}:Declaration",
        3,
        1,
    )


def test_native_qualified_enum_does_not_export_short_labels(tmp_path):
    path = tmp_path / "E.TcDUT"
    path.write_text(dut("{attribute 'qualified_only'} TYPE E : (Stop, Run); END_TYPE"))
    code = tmp_path / "bad.st"
    code.write_text("FUNCTION F : E F := Run; END_FUNCTION")
    with pytest.raises(ValidationError):
        validate(load_files([path, code]))
