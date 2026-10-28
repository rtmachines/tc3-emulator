"""Strict imports of standalone ST and narrow TwinCAT declaration objects."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Iterable
from dataclasses import replace
from pathlib import Path

from .errors import ParseError
from .parser import _lex, parse
from .syntax import InterfaceDecl, Location, Pou, Program, Property


def _xml_program(text: str, source: str) -> Program:
    location = Location(source, 1, 1)
    if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
        raise ParseError("DTD and entity declarations are unsupported", location)
    try:
        root = ET.fromstring(text)
    except ET.ParseError as error:
        line, column = error.position
        raise ParseError(
            f"Malformed TcPOU XML: {error}", Location(source, line, column + 1)
        ) from error

    def check(element: ET.Element, tag: str, attributes: set[str]) -> None:
        if element.tag != tag or set(element.attrib) - attributes:
            raise ParseError(f"Unsupported TcPOU element or attributes: {element.tag}", location)

    check(root, "TcPlcObject", {"Version", "ProductVersion"})
    if len(root) != 1:
        raise ParseError("TcPOU must contain exactly one POU", location)
    pou = root[0]
    check(pou, "POU", {"Name", "Id"})
    if not pou.get("Name"):
        raise ParseError("TcPOU POU requires Name metadata", location)
    if (
        sum(child.tag == "Declaration" for child in pou) != 1
        or sum(child.tag == "Implementation" for child in pou) != 1
        or any(
            child.tag not in {"Declaration", "Implementation", "Method", "Property"}
            for child in pou
        )
    ):
        raise ParseError(
            "TcPOU requires Declaration and Implementation; other semantic objects are unsupported",
            location,
        )
    for element in root.iter():
        if element.tag not in {"Declaration", "ST"} and element.text and element.text.strip():
            raise ParseError("Unexpected text outside TcPOU ST sections", location)
        if element.tail and element.tail.strip():
            raise ParseError("Unexpected text outside TcPOU ST sections", location)

    def sections(element: ET.Element, section_source: str, owner: str | None = None) -> Pou:
        declaration = element.find("Declaration")
        implementation = element.find("Implementation")
        if (
            declaration is None
            or implementation is None
            or sum(child.tag == "Declaration" for child in element) != 1
            or sum(child.tag == "Implementation" for child in element) != 1
        ):
            raise ParseError("TcPOU requires exactly one Declaration and Implementation", location)
        check(declaration, "Declaration", set())
        check(implementation, "Implementation", set())
        if len(declaration) or len(implementation) != 1:
            raise ParseError("Unsupported TcPOU declaration or implementation", location)
        st = implementation[0]
        check(st, "ST", set())
        if len(st):
            raise ParseError("ST implementation must contain text only", location)
        name = element.get("Name", "")
        name_tokens = _lex(name, section_source, None)
        if (
            len(name_tokens) != 2
            or name_tokens[0].kind != "ID"
            or name_tokens[0].text != name.upper()
        ):
            raise ParseError("POU/Method Name metadata must be a valid ST identifier", location)
        declaration_text = declaration.text or ""
        implementation_text = st.text or ""
        declaration_source = f"{section_source}:Declaration"
        declaration_tokens = _lex(declaration_text, declaration_source, None)
        first = declaration_tokens[0]
        if first.kind == "CALL_AFTER_INIT":
            first = declaration_tokens[1]
        expected = {"METHOD"} if owner else {"FUNCTION", "FUNCTION_BLOCK", "PROGRAM"}
        if first.kind not in expected:
            raise ParseError("Unsupported TcPOU declaration kind", first.loc)
        prefix = f"FUNCTION_BLOCK {owner}\n" if owner else ""
        ending = "END_METHOD\nEND_FUNCTION_BLOCK" if owner else "END_" + first.kind
        offset = 1 if owner else 0
        declaration_count = len(declaration_text.split("\n"))
        locations = {
            line + offset: Location(declaration_source, line, 1)
            for line in range(1, declaration_count + len(ending.split("\n")) + 1)
        }

        def extract(program: Program, loc: Location) -> Pou:
            if (
                not program.types
                and not program.gvls
                and not program.interfaces
                and len(program.pous) == 1
            ):
                parsed = program.pous[0]
                if owner:
                    if (
                        not parsed.variables
                        and not parsed.body
                        and not parsed.properties
                        and len(parsed.methods) == 1
                    ):
                        return parsed.methods[0]
                elif not parsed.methods and not parsed.properties:
                    return parsed
            raise ParseError("Unexpected declarations outside the declared POU or method", loc)

        # Parse the declaration alone before admitting implementation text.
        declared = extract(
            parse(prefix + declaration_text + "\n" + ending, section_source, locations=locations),
            first.loc,
        )
        if declared.body:
            raise ParseError(
                "Declaration must contain only a header and variable declarations", first.loc
            )
        if declared.result_name != name.upper():
            raise ParseError("POU/Method Name metadata does not match its declaration", first.loc)
        body_count = len(implementation_text.split("\n"))
        for line in range(1, body_count + 2):
            locations[offset + declaration_count + line] = Location(
                f"{section_source}:Implementation", line, 1
            )
        implementation_location = Location(f"{section_source}:Implementation", 1, 1)
        parsed = extract(
            parse(
                prefix + declaration_text + "\n" + implementation_text + "\n" + ending,
                section_source,
                locations=locations,
            ),
            implementation_location,
        )
        if replace(parsed, body=()) != declared:
            raise ParseError(
                "Implementation must contain only statements for its declaration",
                implementation_location,
            )
        return parsed

    def property_object(element: ET.Element, owner: str) -> Property:
        check(element, "Property", {"Name", "Id"})
        name = element.get("Name", "")
        section_source = f"{source}:Property:{name}"
        name_tokens = _lex(name, section_source, None)
        if (
            len(name_tokens) != 2
            or name_tokens[0].kind != "ID"
            or name_tokens[0].text != name.upper()
        ):
            raise ParseError("Property Name metadata must be a valid ST identifier", location)
        if sum(child.tag == "Declaration" for child in element) != 1 or any(
            child.tag not in {"Declaration", "Get", "Set"} for child in element
        ):
            raise ParseError("Property requires Declaration and Get and/or Set", location)
        declaration = element.find("Declaration")
        check(declaration, "Declaration", set())
        if len(declaration):
            raise ParseError("Property declaration must contain text only", location)
        header = declaration.text or ""
        header_source = f"{section_source}:Declaration"

        def parse_parts(parts: list[tuple[str, str]]) -> Property:
            chunks = []
            locations = {}
            line = 1
            for chunk, chunk_source in parts:
                chunks.append(chunk + "\n")
                for original_line in range(1, len(chunk.split("\n")) + 1):
                    locations[line] = Location(chunk_source, original_line, 1)
                    line += 1
            program = parse("".join(chunks), section_source, locations=locations)
            if (
                not program.types
                and not program.gvls
                and not program.interfaces
                and len(program.pous) == 1
            ):
                parsed = program.pous[0]
                if (
                    parsed.name == owner
                    and not parsed.variables
                    and not parsed.body
                    and not parsed.methods
                    and len(parsed.properties) == 1
                ):
                    return parsed.properties[0]
            raise ParseError("Unexpected objects outside the declared property", location)

        prefix = [(f"FUNCTION_BLOCK {owner}", header_source), (header, header_source)]
        ending = [("END_PROPERTY\nEND_FUNCTION_BLOCK", header_source)]
        declared = parse_parts(prefix + [("GET\nEND_GET", header_source)] + ending)
        if declared.name != name.upper():
            raise ParseError("Property Name metadata does not match its declaration", declared.loc)
        accessors = {}
        for child in element:
            if child.tag == "Declaration":
                continue
            kind = child.tag.upper()
            if kind in accessors:
                raise ParseError(f"Duplicate property {kind} accessor", location)
            check(child, child.tag, {"Name", "Id"})
            if "Name" in child.attrib and child.attrib["Name"].upper() != kind:
                raise ParseError("Accessor Name metadata must match Get/Set", location)
            if len(child) != 2 or {part.tag for part in child} != {"Declaration", "Implementation"}:
                raise ParseError("Accessor requires Declaration and Implementation", location)
            local = child.find("Declaration")
            implementation = child.find("Implementation")
            check(local, "Declaration", set())
            check(implementation, "Implementation", set())
            if len(local) or len(implementation) != 1:
                raise ParseError("Unsupported accessor declaration or implementation", location)
            st = implementation[0]
            check(st, "ST", set())
            if len(st):
                raise ParseError("Accessor ST implementation must contain text only", location)
            accessor_source = f"{section_source}:{child.tag}"
            local_source = f"{accessor_source}:Declaration"
            body_source = f"{accessor_source}:Implementation"
            local_text = local.text or ""
            first = _lex(local_text, local_source, None)[0]
            accessor_parts = []
            if first.text not in {"GET", "SET"}:
                accessor_parts.append((kind, local_source))
            elif first.text != kind:
                raise ParseError("Accessor declaration must match Get/Set", first.loc)
            accessor_parts.append((local_text, local_source))
            suffix = [("END_" + kind, local_source)] + ending

            def extract(parsed: Property) -> Pou:
                accessor = parsed.getter if kind == "GET" else parsed.setter
                other = parsed.setter if kind == "GET" else parsed.getter
                if accessor is None or other is not None:
                    raise ParseError("Unexpected nested accessor objects", first.loc)
                if replace(parsed, getter=declared.getter, setter=None) != declared:
                    raise ParseError("Unexpected declarations outside accessor", first.loc)
                return accessor

            local_declared = extract(parse_parts(prefix + accessor_parts + suffix))
            if local_declared.body:
                raise ParseError("Accessor Declaration must not contain statements", first.loc)
            parsed = extract(
                parse_parts(prefix + accessor_parts + [(st.text or "", body_source)] + suffix)
            )
            if replace(parsed, body=()) != local_declared:
                raise ParseError(
                    "Accessor Implementation must contain only statements",
                    Location(body_source, 1, 1),
                )
            accessors[kind] = parsed
        if not accessors:
            raise ParseError("Property requires Get and/or Set", declared.loc)
        return replace(declared, getter=accessors.get("GET"), setter=accessors.get("SET"))

    parsed_owner = sections(pou, source)
    methods = []
    properties = []
    for method in pou:
        if method.tag == "Property":
            if parsed_owner.kind != "FUNCTION_BLOCK":
                raise ParseError("Properties require a FUNCTION_BLOCK owner", location)
            properties.append(property_object(method, parsed_owner.name))
            continue
        if method.tag != "Method":
            continue
        check(method, "Method", {"Name", "Id"})
        if parsed_owner.kind != "FUNCTION_BLOCK":
            raise ParseError("Methods require a FUNCTION_BLOCK owner", location)
        if len(method) != 2 or {child.tag for child in method} != {"Declaration", "Implementation"}:
            raise ParseError("Method requires exactly Declaration and Implementation", location)
        methods.append(
            sections(method, f"{source}:Method:{method.get('Name', '')}", parsed_owner.name)
        )
    return Program((replace(parsed_owner, methods=tuple(methods), properties=tuple(properties)),))


def _xml_interface(text: str, source: str) -> Program:
    """Import the native Itf/Method/Property declaration-only TcIO shape."""
    location = Location(source, 1, 1)
    if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
        raise ParseError("DTD and entity declarations are unsupported", location)
    try:
        root = ET.fromstring(text)
    except ET.ParseError as error:
        line, column = error.position
        raise ParseError(
            f"Malformed TcIO XML: {error}", Location(source, line, column + 1)
        ) from error

    def check(element: ET.Element, tag: str, attributes: set[str]) -> None:
        if element.tag != tag or set(element.attrib) - attributes:
            raise ParseError(f"Unsupported TcIO element or attributes: {element.tag}", location)

    def metadata(element: ET.Element) -> str:
        name = element.get("Name", "")
        tokens = _lex(name, source, None)
        if len(tokens) != 2 or tokens[0].kind != "ID" or tokens[0].text != name.upper():
            raise ParseError(f"{element.tag} Name metadata must be a valid ST identifier", location)
        return name.upper()

    def declaration(element: ET.Element, allowed: set[str]) -> str:
        if sum(child.tag == "Declaration" for child in element) != 1 or any(
            child.tag not in allowed | {"Declaration"} for child in element
        ):
            raise ParseError(f"{element.tag} requires exactly one Declaration", location)
        child = element.find("Declaration")
        check(child, "Declaration", set())
        if len(child):
            raise ParseError("TcIO Declaration must contain text only", location)
        return child.text or ""

    def parse_parts(parts: list[tuple[str, str]]) -> InterfaceDecl:
        chunks = []
        locations = {}
        line = 1
        for chunk, chunk_source in parts:
            chunks.append(chunk + "\n")
            for original_line in range(1, len(chunk.split("\n")) + 1):
                locations[line] = Location(chunk_source, original_line, 1)
                line += 1
        program = parse("".join(chunks), source, locations=locations)
        if program.pous or program.types or program.gvls or len(program.interfaces) != 1:
            raise ParseError("Unexpected objects outside the declared interface member", location)
        return program.interfaces[0]

    check(root, "TcPlcObject", {"Version", "ProductVersion"})
    if len(root) != 1:
        raise ParseError("TcIO must contain exactly one Itf", location)
    interface = root[0]
    check(interface, "Itf", {"Name", "Id"})
    name = metadata(interface)
    header = declaration(interface, {"Method", "Property"})
    for element in root.iter():
        if element.tag != "Declaration" and element.text and element.text.strip():
            raise ParseError("Unexpected text outside TcIO Declaration", location)
        if element.tail and element.tail.strip():
            raise ParseError("Unexpected text outside TcIO Declaration", location)
    header_source = f"{source}:Declaration"
    ending = [("END_INTERFACE", header_source)]
    declared = parse_parts([(header, header_source)] + ending)
    if declared.name != name:
        raise ParseError("Itf Name metadata does not match its declaration", declared.loc)
    if declared.methods or declared.properties:
        raise ParseError("Itf Declaration must contain only the interface header", declared.loc)
    prefix = [(f"INTERFACE {name}", header_source)]

    def property_object(element: ET.Element) -> Property:
        check(element, "Property", {"Name", "Id"})
        property_name = metadata(element)
        section_source = f"{source}:Property:{element.get('Name', '')}"
        property_source = f"{section_source}:Declaration"
        header = declaration(element, {"Get", "Set"})
        property_prefix = prefix + [(header, property_source)]
        property_ending = [("END_PROPERTY", property_source)] + ending

        def extract(parts: list[tuple[str, str]]) -> Property:
            parsed = parse_parts(parts)
            if parsed.name != name or parsed.methods or len(parsed.properties) != 1:
                raise ParseError("Unexpected objects outside the declared property", location)
            prop = parsed.properties[0]
            if prop.name != property_name:
                raise ParseError("Property Name metadata does not match its declaration", prop.loc)
            return prop

        prop = extract(property_prefix + [("GET\nEND_GET", property_source)] + property_ending)
        accessors = {}
        for child in element:
            if child.tag == "Declaration":
                continue
            kind = child.tag.upper()
            if kind in accessors:
                raise ParseError(f"Duplicate property {kind} accessor", location)
            check(child, child.tag, {"Name", "Id"})
            if "Name" in child.attrib and child.attrib["Name"].upper() != kind:
                raise ParseError("Accessor Name metadata must match Get/Set", location)
            local_text = declaration(child, set())
            local_source = f"{section_source}:{child.tag}:Declaration"
            first = _lex(local_text, local_source, None)[0]
            accessor_parts = []
            if first.text not in {"GET", "SET"}:
                accessor_parts.append((kind, local_source))
            elif first.text != kind:
                raise ParseError("Accessor declaration must match Get/Set", first.loc)
            accessor_parts.extend([(local_text, local_source), ("END_" + kind, local_source)])
            parsed = extract(property_prefix + accessor_parts + property_ending)
            accessor = parsed.getter if kind == "GET" else parsed.setter
            other = parsed.setter if kind == "GET" else parsed.getter
            if (
                accessor is None
                or other is not None
                or replace(parsed, getter=prop.getter, setter=None) != prop
            ):
                raise ParseError("Unexpected nested accessor objects", first.loc)
            accessors[kind] = accessor
        if not accessors:
            raise ParseError("Property requires Get and/or Set", prop.loc)
        return replace(prop, getter=accessors.get("GET"), setter=accessors.get("SET"))

    methods = []
    properties = []
    for child in interface:
        if child.tag == "Declaration":
            continue
        if child.tag == "Property":
            properties.append(property_object(child))
            continue
        check(child, "Method", {"Name", "Id"})
        method_name = metadata(child)
        section_source = f"{source}:Method:{child.get('Name', '')}:Declaration"
        method_text = declaration(child, set())
        parsed = parse_parts(
            prefix + [(method_text, section_source), ("END_METHOD", section_source)] + ending
        )
        if parsed.name != name or parsed.properties or len(parsed.methods) != 1:
            raise ParseError("Unexpected objects outside the declared method", location)
        method = parsed.methods[0]
        if method.result_name != method_name:
            raise ParseError("Method Name metadata does not match its declaration", method.loc)
        methods.append(method)
    return Program(
        (), interfaces=(replace(declared, methods=tuple(methods), properties=tuple(properties)),)
    )


def _xml_dut(text: str, source: str) -> Program:
    location = Location(source, 1, 1)
    if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
        raise ParseError("DTD and entity declarations are unsupported", location)
    try:
        root = ET.fromstring(text)
    except ET.ParseError as error:
        line, column = error.position
        raise ParseError(
            f"Malformed TcDUT XML: {error}", Location(source, line, column + 1)
        ) from error

    def check(element: ET.Element, tag: str, attributes: set[str]) -> None:
        if element.tag != tag or set(element.attrib) - attributes:
            raise ParseError(f"Unsupported TcDUT element or attributes: {element.tag}", location)

    check(root, "TcPlcObject", {"Version", "ProductVersion"})
    if len(root) != 1:
        raise ParseError("TcDUT must contain exactly one DUT", location)
    dut = root[0]
    check(dut, "DUT", {"Name", "Id"})
    if not dut.get("Name"):
        raise ParseError("TcDUT DUT requires Name metadata", location)
    if len(dut) != 1:
        raise ParseError("TcDUT requires exactly one Declaration", location)
    declaration = dut[0]
    check(declaration, "Declaration", set())
    if len(declaration):
        raise ParseError("TcDUT declaration must contain text only", location)
    for element in (root, dut):
        if element.text and element.text.strip():
            raise ParseError("Unexpected text outside TcDUT Declaration", location)
    for element in root.iter():
        if element.tail and element.tail.strip():
            raise ParseError("Unexpected text outside TcDUT Declaration", location)
    program = parse(declaration.text or "", f"{source}:Declaration")
    if program.pous or program.gvls or program.interfaces or len(program.types) != 1:
        raise ParseError("TcDUT must declare exactly one TYPE and no POUs", location)
    if program.types[0].name != dut.attrib["Name"].upper():
        raise ParseError("DUT Name metadata does not match its declaration", program.types[0].loc)
    return program


def _xml_gvl(text: str, source: str) -> Program:
    location = Location(source, 1, 1)
    if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
        raise ParseError("DTD and entity declarations are unsupported", location)
    try:
        root = ET.fromstring(text)
    except ET.ParseError as error:
        line, column = error.position
        raise ParseError(
            f"Malformed TcGVL XML: {error}", Location(source, line, column + 1)
        ) from error

    def check(element: ET.Element, tag: str, attributes: set[str]) -> None:
        if element.tag != tag or set(element.attrib) - attributes:
            raise ParseError(f"Unsupported TcGVL element or attributes: {element.tag}", location)

    check(root, "TcPlcObject", {"Version", "ProductVersion"})
    if len(root) != 1:
        raise ParseError("TcGVL must contain exactly one GVL", location)
    gvl = root[0]
    check(gvl, "GVL", {"Name", "Id"})
    name = gvl.get("Name")
    if not name:
        raise ParseError("TcGVL GVL requires Name metadata", location)
    # Validate metadata independently, including when the declaration is malformed or empty.
    name_tokens = _lex(name, source, None)
    if len(name_tokens) != 2 or name_tokens[0].kind != "ID" or name_tokens[0].text != name.upper():
        raise ParseError("GVL Name metadata must be a valid ST identifier", location)
    if len(gvl) != 1:
        raise ParseError("TcGVL requires exactly one Declaration", location)
    declaration = gvl[0]
    check(declaration, "Declaration", set())
    if len(declaration):
        raise ParseError("TcGVL declaration must contain text only", location)
    for element in (root, gvl):
        if element.text and element.text.strip():
            raise ParseError("Unexpected text outside TcGVL Declaration", location)
    for element in root.iter():
        if element.tail and element.tail.strip():
            raise ParseError("Unexpected text outside TcGVL Declaration", location)
    program = parse(declaration.text or "", f"{source}:Declaration", gvl_name=name)
    if program.pous or program.types or program.interfaces or len(program.gvls) != 1:
        raise ParseError("TcGVL must contain only VAR_GLOBAL declarations", location)
    return program


def load_files(paths: Iterable[str | Path]) -> Program:
    """Load all requested files in order, leaving whole-program validation to the caller."""
    pous = []
    types = []
    gvls = []
    interfaces = []
    for path in paths:
        path = Path(path)
        source = str(path)
        extension = path.suffix.lower()
        if extension not in {".st", ".tcpou", ".tcdut", ".tcgvl", ".tcio"}:
            raise ParseError(
                f"Unsupported source extension {path.suffix!r}", Location(source, 1, 1)
            )
        try:
            text = path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError) as error:
            raise ParseError(f"Cannot read source: {error}", Location(source, 1, 1)) from error
        if extension == ".st":
            program = parse(text, source, gvl_name=path.stem)
        elif extension == ".tcpou":
            program = _xml_program(text, source)
        elif extension == ".tcdut":
            program = _xml_dut(text, source)
        elif extension == ".tcio":
            program = _xml_interface(text, source)
        else:
            program = _xml_gvl(text, source)
        pous.extend(program.pous)
        types.extend(program.types)
        gvls.extend(program.gvls)
        interfaces.extend(program.interfaces)
    return Program(tuple(pous), tuple(types), tuple(gvls), tuple(interfaces))
