"""Native interface inheritance keeps declaration coordinates and member boundaries."""

import pytest

from tc_emulator import ParseError
from tc_emulator.loader import load_files


def native_interface(header):
    return f"""<TcPlcObject><Itf Name="I_Derived"><Declaration><![CDATA[{header}]]></Declaration>
<Method Name="Run"><Declaration><![CDATA[
METHOD Run : INT]]></Declaration></Method>
<Property Name="Value"><Declaration><![CDATA[
PROPERTY Value : INT]]></Declaration><Get><Declaration>GET</Declaration></Get></Property>
</Itf></TcPlcObject>"""


def test_tcio_preserves_multiple_bases_and_member_locations(tmp_path):
    path = tmp_path / "derived.TcIO"
    path.write_text(native_interface("\nINTERFACE I_Derived EXTENDS i_a, I_b"))
    interface = load_files([path]).interfaces[0]
    assert interface.extends == ("I_A", "I_B")
    assert interface.loc.source.endswith(":Declaration") and interface.loc.line == 2
    method = interface.methods[0]
    assert method.loc.source.endswith(":Method:Run:Declaration") and method.loc.line == 2
    prop = interface.properties[0]
    assert prop.loc.source.endswith(":Property:Value:Declaration") and prop.loc.line == 2
    assert prop.getter.loc.source.endswith(":Property:Value:Get:Declaration")


@pytest.mark.parametrize("extra", ["METHOD Hidden END_METHOD", "END_INTERFACE INTERFACE Hidden"])
def test_tcio_inherited_header_rejects_nested_declaration_injection(tmp_path, extra):
    path = tmp_path / "derived.TcIO"
    path.write_text(native_interface(f"INTERFACE I_Derived EXTENDS I_Base {extra}"))
    with pytest.raises(ParseError):
        load_files([path])


@pytest.mark.parametrize("reverse", [False, True])
def test_native_bases_resolve_independent_of_file_order(tmp_path, reverse):
    from tc_emulator import Runtime

    derived = tmp_path / "derived.TcIO"
    derived.write_text(native_interface("INTERFACE I_Derived EXTENDS I_A, I_B"))
    bases = tmp_path / "bases.st"
    bases.write_text("INTERFACE I_A END_INTERFACE INTERFACE I_B END_INTERFACE")
    paths = [derived, bases]
    if reverse:
        paths.reverse()
    rt = Runtime(load_files(paths))
    assert rt._registry.interface_ancestors["I_DERIVED"] == {"I_DERIVED", "I_A", "I_B"}


def test_invalid_native_base_reports_interface_declaration_location(tmp_path):
    from tc_emulator import Runtime, ValidationError

    path = tmp_path / "derived.TcIO"
    path.write_text(native_interface("\nINTERFACE I_Derived EXTENDS Missing"))
    with pytest.raises(ValidationError) as caught:
        Runtime(load_files([path]))
    assert caught.value.loc.source.endswith("derived.TcIO:Declaration")
    assert caught.value.loc.line == 2
