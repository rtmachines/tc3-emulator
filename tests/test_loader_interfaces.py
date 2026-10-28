"""Native declaration-only TcIO objects preserve source and import boundaries."""

import pytest

from tc_emulator.errors import ParseError
from tc_emulator.loader import load_files


def method_xml(declaration="METHOD Run\nVAR_INPUT speed : INT := 2; END_VAR", name="Run"):
    return f'<Method Name="{name}" Id="m"><Declaration><![CDATA[{declaration}]]></Declaration></Method>'


def accessor_xml(kind="Get", declaration="", metadata=""):
    return f"<{kind}{metadata}><Declaration><![CDATA[{declaration}]]></Declaration></{kind}>"


def property_xml(declaration="PROPERTY Speed : INT", children=None, name="Speed"):
    if children is None:
        children = accessor_xml()
    return (
        f'<Property Name="{name}" Id="p"><Declaration><![CDATA[{declaration}]]></Declaration>'
        f"{children}</Property>"
    )


def interface_xml(children="", declaration="INTERFACE I_Motor", name="I_Motor"):
    return (
        '<TcPlcObject Version="1" ProductVersion="3.1">'
        f'<Itf Name="{name}" Id="i"><Declaration><![CDATA[{declaration}]]></Declaration>'
        f"{children}</Itf></TcPlcObject>"
    )


def load_xml(tmp_path, text):
    path = tmp_path / "I_Motor.TcIO"
    path.write_text(text, encoding="utf-8")
    return load_files([path])


def test_tcio_merges_interfaces_across_bom_and_mixed_case_source_extensions(tmp_path):
    first = tmp_path / "one.tCiO"
    first.write_text("\ufeff" + interface_xml(method_xml() + property_xml()), encoding="utf-8")
    second = tmp_path / "two.ST"
    second.write_text("INTERFACE I_Status END_INTERFACE", encoding="utf-8")
    fb = tmp_path / "Motor.TcPOU"
    fb.write_text(
        '<TcPlcObject><POU Name="Motor"><Declaration>'
        "FUNCTION_BLOCK Motor IMPLEMENTS I_Motor, I_Status</Declaration>"
        "<Implementation><ST/></Implementation></POU></TcPlcObject>",
        encoding="utf-8",
    )
    program = load_files([fb, first, second])
    assert [i.name for i in program.interfaces] == ["I_MOTOR", "I_STATUS"]
    assert program.pous[0].implements == ("I_MOTOR", "I_STATUS")
    assert program.interfaces[0].methods[0].name == "I_MOTOR.RUN"
    assert program.interfaces[0].properties[0].getter.name == "I_MOTOR.SPEED.GET"


def test_tcio_preserves_interface_method_property_and_accessor_declaration_locations(tmp_path):
    interface = load_xml(
        tmp_path,
        interface_xml(
            method_xml("\nMETHOD Run\nVAR_INPUT speed : INT := 2; END_VAR")
            + property_xml(
                "\nPROPERTY Speed : INT",
                accessor_xml("Get", "\nGET PUBLIC")
                + accessor_xml("Set", "SET", ' Name="Set" Id="s"'),
            ),
            declaration="\nINTERFACE I_Motor",
        ),
    ).interfaces[0]
    assert interface.loc.source.endswith("I_Motor.TcIO:Declaration")
    assert interface.loc.line == 2
    method = interface.methods[0]
    assert method.loc.source.endswith(":Method:Run:Declaration") and method.loc.line == 2
    assert method.variables[0].loc.line == 3
    prop = interface.properties[0]
    assert prop.loc.source.endswith(":Property:Speed:Declaration") and prop.loc.line == 2
    assert prop.getter.loc.source.endswith(":Property:Speed:Get:Declaration")
    assert prop.getter.loc.line == 2
    assert prop.setter.loc.source.endswith(":Property:Speed:Set:Declaration")
    assert prop.setter.loc.line == 1


@pytest.mark.parametrize(
    "text",
    [
        "<TcPlcObject>",
        '<!DOCTYPE TcPlcObject [<!ENTITY x "hello">]>' + interface_xml(),
        interface_xml().replace("<TcPlcObject ", '<TcPlcObject Extra="x" '),
        interface_xml().replace("<Itf Name=", '<Itf Extra="x" Name='),
        interface_xml().replace('<Itf Name="I_Motor" Id="i">', '<Itf Id="i">'),
        interface_xml().replace("<Itf ", "<Interface ").replace("</Itf>", "</Interface>"),
        interface_xml().replace("</Itf>", "<Implementation/></Itf>"),
        interface_xml().replace("</Itf>", "<Declaration/></Itf>"),
        interface_xml().replace("</Itf>", "<Unknown/></Itf>"),
        interface_xml().replace("<Declaration>", '<Declaration Extra="x">'),
        interface_xml().replace("<Declaration>", "<Declaration><Unknown/>"),
        interface_xml().replace("</Declaration>", "</Declaration>hidden"),
        interface_xml(name="Other"),
        interface_xml(name="I_Motor "),
        interface_xml(name="I.Motor"),
        interface_xml(declaration="INTERFACE I_Motor METHOD Hidden END_METHOD"),
        interface_xml(declaration="INTERFACE I_Motor PROPERTY P : INT GET END_GET END_PROPERTY"),
        interface_xml(declaration="INTERFACE I_Motor END_INTERFACE INTERFACE Hidden"),
        interface_xml(method_xml(name="Other")),
        interface_xml(method_xml(name="Run ")),
        interface_xml(method_xml().replace("<Method ", '<Method Extra="x" ')),
        interface_xml(method_xml().replace("</Method>", "<Implementation/></Method>")),
        interface_xml(method_xml().replace("</Method>", "<Declaration/></Method>")),
        interface_xml(method_xml("METHOD Run Run();")),
        interface_xml(method_xml("METHOD Run END_METHOD METHOD Hidden")),
        interface_xml(property_xml(name="Other")),
        interface_xml(property_xml(children="")),
        interface_xml(property_xml(children=accessor_xml() + accessor_xml())),
        interface_xml(property_xml(children=accessor_xml(declaration="SET"))),
        interface_xml(property_xml(children=accessor_xml(declaration="GET PRIVATE"))),
        interface_xml(property_xml(children=accessor_xml(declaration="GET VAR x : INT; END_VAR"))),
        interface_xml(property_xml(children=accessor_xml(declaration="GET Speed := 1;"))),
        interface_xml(property_xml(children=accessor_xml(declaration="GET END_GET SET"))),
        interface_xml(property_xml(children=accessor_xml(metadata=' Name="Set"'))),
        interface_xml(property_xml(children=accessor_xml(metadata=' Name="Get "'))),
        interface_xml(property_xml(children=accessor_xml(metadata=' Extra="x"'))),
        interface_xml(property_xml().replace("</Get>", "<Implementation/></Get>")),
        interface_xml(property_xml().replace("</Get>", "<Declaration/></Get>")),
        interface_xml(property_xml().replace("</Property>", "<Method/></Property>")),
        interface_xml(property_xml(declaration="PROPERTY Speed : INT GET END_GET")),
    ],
)
def test_tcio_rejects_malformed_metadata_sections_and_declaration_injection(tmp_path, text):
    with pytest.raises(ParseError):
        load_xml(tmp_path, text)


@pytest.mark.parametrize(
    "fragment,suffix,line,column",
    [
        (method_xml("METHOD Run\nVAR_INPUT x : @; END_VAR"), ":Method:Run:Declaration", 2, 15),
        (property_xml("PROPERTY Speed : @"), ":Property:Speed:Declaration", 1, 18),
        (
            property_xml(children=accessor_xml(declaration="GET\n@")),
            ":Property:Speed:Get:Declaration",
            2,
            1,
        ),
    ],
)
def test_tcio_member_error_positions_are_local_to_the_declaration(
    tmp_path, fragment, suffix, line, column
):
    with pytest.raises(ParseError) as caught:
        load_xml(tmp_path, interface_xml(fragment))
    assert caught.value.loc.source.endswith(suffix)
    assert (caught.value.loc.line, caught.value.loc.column) == (line, column)


@pytest.mark.parametrize(
    "extension,text",
    [
        (
            "TcDUT",
            '<TcPlcObject><DUT Name="D"><Declaration>TYPE D : INT; END_TYPE '
            "INTERFACE I END_INTERFACE</Declaration></DUT></TcPlcObject>",
        ),
        (
            "TcGVL",
            '<TcPlcObject><GVL Name="G"><Declaration>VAR_GLOBAL x : INT; END_VAR '
            "INTERFACE I END_INTERFACE</Declaration></GVL></TcPlcObject>",
        ),
        (
            "TcPOU",
            '<TcPlcObject><POU Name="F"><Declaration>FUNCTION_BLOCK F END_FUNCTION_BLOCK '
            "INTERFACE I END_INTERFACE FUNCTION_BLOCK Hidden</Declaration>"
            "<Implementation><ST/></Implementation></POU></TcPlcObject>",
        ),
    ],
)
def test_other_xml_importers_reject_leaked_interface_declarations(tmp_path, extension, text):
    path = tmp_path / f"object.{extension}"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ParseError):
        load_files([path])


def test_tcio_accepts_empty_interfaces_and_optional_id_metadata(tmp_path):
    program = load_xml(tmp_path, interface_xml().replace(' Id="i"', ""))
    assert program.pous == program.types == program.gvls == ()
    interface = program.interfaces[0]
    assert interface.name == "I_MOTOR" and interface.methods == interface.properties == ()


def test_tcio_accepts_setter_only_and_method_value_return_prototypes(tmp_path):
    interface = load_xml(
        tmp_path,
        interface_xml(
            property_xml(children=accessor_xml("Set", "SET PUBLIC"))
            + method_xml("METHOD Run : STRING(12)").replace(' Id="m"', "")
        ).replace(' Id="p"', ""),
    ).interfaces[0]
    assert interface.properties[0].getter is None
    assert interface.properties[0].setter.kind == "PROPERTY_SET"
    assert str(interface.methods[0].return_type) == "STRING(12)"


def test_tcio_interface_error_uses_declaration_source_coordinates(tmp_path):
    with pytest.raises(ParseError) as caught:
        load_xml(tmp_path, interface_xml(declaration="\nINTERFACE @"))
    assert caught.value.loc.source.endswith("I_Motor.TcIO:Declaration")
    assert (caught.value.loc.line, caught.value.loc.column) == (2, 11)
