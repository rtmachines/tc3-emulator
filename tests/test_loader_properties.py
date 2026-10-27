"""Strict XML property object import and source-section diagnostics."""

import pytest

from tc_emulator.errors import ParseError
from tc_emulator.loader import load_files


def accessor(kind="Get", declaration="", body="P := THIS^.value;", metadata=""):
    return (
        f"<{kind}{metadata}><Declaration><![CDATA[{declaration}]]></Declaration>"
        f"<Implementation><ST><![CDATA[{body}]]></ST></Implementation></{kind}>"
    )


def property_xml(declaration="PROPERTY P : INT", children=None, name="P"):
    if children is None:
        children = accessor()
    return (
        f'<Property Name="{name}" Id="property-id"><Declaration><![CDATA[{declaration}]]>'
        f"</Declaration>{children}</Property>"
    )


def owner_xml(children, declaration="FUNCTION_BLOCK Drive", body=""):
    return (
        f'<TcPlcObject><POU Name="Drive"><Declaration><![CDATA[{declaration}]]>'
        f"</Declaration><Implementation><ST><![CDATA[{body}]]></ST></Implementation>"
        f"{children}</POU></TcPlcObject>"
    )


def load_xml(tmp_path, text):
    path = tmp_path / "Drive.TcPOU"
    path.write_text(text, encoding="utf-8")
    return load_files([path])


def test_xml_property_maps_header_accessor_declarations_and_bodies(tmp_path):
    owner = load_xml(
        tmp_path,
        owner_xml(
            property_xml(
                "PROPERTY PUBLIC P : INT\nVAR shared : INT; END_VAR",
                accessor(
                    declaration="GET PRIVATE\nVAR scratch : INT; END_VAR",
                    body="\nP := shared;",
                    metadata=' Name="Get" Id="get-id"',
                )
                + accessor("Set", "VAR value : INT; END_VAR", "THIS^.value := P;"),
            )
        ),
    ).pous[0]
    prop = owner.properties[0]
    assert prop.name == "P" and prop.getter.kind == "PROPERTY_GET"
    assert prop.setter.kind == "PROPERTY_SET" and prop.setter.result_name == "P"
    assert [v.name for v in prop.getter.variables] == ["SHARED", "SCRATCH"]
    assert prop.loc.source.endswith(":Property:P:Declaration") and prop.loc.line == 1
    assert prop.variables[0].loc.source.endswith(":Property:P:Declaration")
    assert prop.variables[0].loc.line == 2
    assert prop.getter.loc.source.endswith(":Property:P:Get:Declaration")
    assert prop.getter.variables[1].loc.line == 2
    assert prop.getter.body[0].loc.source.endswith(":Property:P:Get:Implementation")
    assert prop.getter.body[0].loc.line == 2
    assert prop.setter.variables[1].loc.line == 1


@pytest.mark.parametrize(
    "fragment",
    [
        '<Property Name="P"/>',
        property_xml(name="Other"),
        property_xml(name="P "),
        property_xml(name="P.X"),
        property_xml(declaration="PROPERTY P : INT P := 1;"),
        property_xml(declaration="PROPERTY P : INT GET END_GET"),
        property_xml(children=""),
        property_xml(children=accessor() + accessor()),
        property_xml(children=accessor("Set", body="") + accessor("Set", body="")),
        property_xml(children=accessor(declaration="SET")),
        property_xml(children=accessor(declaration="GET P := 1;")),
        property_xml(children=accessor(body="VAR hidden : INT; END_VAR P := 1;")),
        property_xml(children=accessor(body="END_GET SET END_SET")),
        property_xml(children=accessor(metadata=' Name="Other"')),
        property_xml(children=accessor(metadata=' Name="Get "')),
        property_xml(children=accessor(metadata=' Extra="yes"')),
        property_xml(children=accessor().replace("<Get>", "<Get><Method/>")),
        property_xml().replace("<Property Name=", '<Property Extra="yes" Name='),
        property_xml().replace("</Property>", "<Method/></Property>"),
        property_xml().replace("<Get>", "<Get><Declaration/>"),
        property_xml().replace("<ST>", "<ST Extra='yes'>"),
        property_xml().replace("<ST>", "<ST><Unexpected/>"),
        property_xml().replace("<Get>", "<Get>hidden"),
        property_xml().replace("</Get>", "</Get>hidden"),
    ],
)
def test_xml_rejects_malformed_properties_metadata_duplicates_and_injection(tmp_path, fragment):
    with pytest.raises(ParseError):
        load_xml(tmp_path, owner_xml(fragment))


@pytest.mark.parametrize("declaration", ["PROGRAM Drive", "FUNCTION Drive : INT"])
def test_xml_properties_require_fb_owner(tmp_path, declaration):
    with pytest.raises(ParseError):
        load_xml(tmp_path, owner_xml(property_xml(), declaration=declaration))


@pytest.mark.parametrize(
    "declaration,body,section,line,column",
    [
        ("GET\nVAR x : @; END_VAR", "", "Declaration", 2, 9),
        ("", "\nP := @;", "Implementation", 2, 6),
    ],
)
def test_xml_accessor_error_positions(tmp_path, declaration, body, section, line, column):
    with pytest.raises(ParseError) as caught:
        load_xml(
            tmp_path, owner_xml(property_xml(children=accessor(declaration=declaration, body=body)))
        )
    assert caught.value.loc.source.endswith(f":Property:P:Get:{section}")
    assert (caught.value.loc.line, caught.value.loc.column) == (line, column)


@pytest.mark.parametrize(
    "declaration,body",
    [
        ("FUNCTION_BLOCK Drive PROPERTY Hidden : INT GET END_GET END_PROPERTY", ""),
        ("FUNCTION_BLOCK Drive", "PROPERTY Hidden : INT GET END_GET END_PROPERTY"),
    ],
)
def test_xml_owner_sections_cannot_smuggle_properties(tmp_path, declaration, body):
    with pytest.raises(ParseError):
        load_xml(tmp_path, owner_xml("", declaration=declaration, body=body))


def test_xml_interleaves_methods_and_read_write_only_properties(tmp_path):
    method = (
        '<Method Name="Step"><Declaration>METHOD Step\n'
        "VAR_INST count : INT; END_VAR</Declaration>"
        "<Implementation><ST>count := count + 1;</ST></Implementation></Method>"
    )
    children = (
        property_xml(children=accessor("Set", "SET PRIVATE", ""))
        + method
        + property_xml("PROPERTY Other : BOOL", accessor(body="Other := TRUE;"), "Other")
    )
    owner = load_xml(tmp_path, owner_xml(children)).pous[0]
    assert [p.name for p in owner.properties] == ["P", "OTHER"]
    assert owner.properties[0].getter is None
    assert owner.properties[0].setter.access == "PRIVATE"
    assert owner.properties[1].setter is None
    assert owner.methods[0].name == "DRIVE.STEP"
    assert owner.methods[0].variables[0].section == "VAR_INST"


def test_xml_property_header_error_has_original_source_location(tmp_path):
    with pytest.raises(ParseError) as caught:
        load_xml(tmp_path, owner_xml(property_xml("PROPERTY P : INT\nVAR x : @; END_VAR")))
    assert caught.value.loc.source.endswith(":Property:P:Declaration")
    assert (caught.value.loc.line, caught.value.loc.column) == (2, 9)


@pytest.mark.parametrize(
    "child",
    [
        accessor(metadata=' Name=""'),
        accessor().replace("<Declaration>", '<Declaration Extra="1">'),
        accessor().replace("<Implementation>", '<Implementation Extra="1">'),
        accessor().replace("<ST>", "<FBD>").replace("</ST>", "</FBD>"),
        accessor().replace("<Declaration>", "<Declaration><Property/>"),
        accessor().replace(
            "</Implementation>", "</Implementation><Implementation><ST/></Implementation>"
        ),
        accessor().replace("</Implementation>", "</Implementation>hidden"),
    ],
)
def test_xml_accessor_boundaries_remain_strict(tmp_path, child):
    with pytest.raises(ParseError):
        load_xml(tmp_path, owner_xml(property_xml(children=child)))
