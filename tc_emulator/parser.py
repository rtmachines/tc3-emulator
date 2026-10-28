"""Lexer and recursive descent parser; no source code is executed."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

from .errors import ParseError
from .syntax import (
    Argument,
    ArrayBounds,
    ArrayInitializer,
    ArrayItem,
    Assign,
    Binary,
    BitAccess,
    Call,
    CallStatement,
    Case,
    EnumDecl,
    EnumMember,
    Exit,
    Expr,
    For,
    GlobalVarList,
    If,
    Index,
    Initializer,
    InterfaceDecl,
    Literal,
    Location,
    LValue,
    Member,
    OpenArrayBounds,
    Pou,
    Program,
    Property,
    RefAssign,
    Reference,
    ReferenceSpec,
    Return,
    Statement,
    StringBounds,
    StructDecl,
    StructInitializer,
    Super,
    This,
    TypeDecl,
    Unary,
    VarDecl,
    While,
)
from .types import (
    FLOAT_TYPES,
    ArrayType,
    OpenArrayType,
    StringType,
    TypeSpec,
    check_value,
    parse_time_literal,
)

_INTEGER_PREFIXES = {"INT", "UINT", "DINT", "UDINT", "BYTE", "WORD", "DWORD"}
_INTEGER_TOKENS = {"INT", "INTEGER_LITERAL"}

_SECTIONS = {"VAR", "VAR_INPUT", "VAR_OUTPUT", "VAR_IN_OUT", "VAR_TEMP", "VAR_INST"}
_RESERVED = _SECTIONS | set(
    """FUNCTION FUNCTION_BLOCK END_FUNCTION END_FUNCTION_BLOCK
END_VAR IF THEN ELSIF ELSE END_IF CASE OF END_CASE FOR TO BY DO END_FOR WHILE
END_WHILE RETURN EXIT TRUE FALSE AND OR XOR NOT MOD PROGRAM END_PROGRAM
RETAIN PERSISTENT CONSTANT METHOD END_METHOD ACTION PROPERTY EXTENDS IMPLEMENTS INTERFACE
END_INTERFACE END_GET END_SET END_PROPERTY THIS SUPER REPEAT UNTIL END_REPEAT ARRAY STRUCT END_STRUCT TYPE END_TYPE AT POINTER REFERENCE
AND_THEN OR_ELSE VAR_GLOBAL VAR_EXTERNAL""".split()
)
_PRECEDENCE = {
    "OR": 1,
    "OR_ELSE": 1,
    "XOR": 2,
    "AND": 3,
    "AND_THEN": 3,
    "=": 4,
    "<>": 4,
    "<": 5,
    "<=": 5,
    ">": 5,
    ">=": 5,
    "+": 6,
    "-": 6,
    "*": 7,
    "/": 7,
    "MOD": 7,
}


@dataclass(frozen=True)
class _Token:
    kind: str
    text: str
    loc: Location


def _lex(text: str, source: str, locations: Mapping[int, Location] | None) -> list[_Token]:
    tokens = []
    index, line, column = 0, 1, 1

    def loc() -> Location:
        original = locations.get(line) if locations else None
        if original:
            return Location(original.source, original.line, original.column + column - 1)
        return Location(source, line, column)

    def advance(count: int = 1) -> None:
        nonlocal index, line, column
        for char in text[index : index + count]:
            if char == "\n":
                line, column = line + 1, 1
            else:
                column += 1
        index += count

    while index < len(text):
        char = text[index]
        if char.isspace():
            advance()
        elif text.startswith("//", index):
            while index < len(text) and text[index] != "\n":
                advance()
        elif text.startswith("(*", index):
            start = loc()
            advance(2)
            depth = 1
            while depth:
                if index >= len(text):
                    raise ParseError("Unterminated block comment", start)
                if text.startswith("(*", index):
                    depth += 1
                    advance(2)
                elif text.startswith("*)", index):
                    depth -= 1
                    advance(2)
                else:
                    advance()
        elif char == "{":
            start, position = index, loc()
            while index < len(text) and text[index] != "}":
                advance()
            if index >= len(text):
                raise ParseError("Unterminated attribute pragma", position)
            advance()
            pragma = text[start:index]
            match = re.fullmatch(
                r"\{\s*attribute\s+'(qualified_only|call_after_init)'\s*\}", pragma, re.I
            )
            if match is None:
                raise ParseError("Unsupported attribute pragma", position)
            tokens.append(_Token(match[1].upper(), pragma, position))
        elif char == "'":
            start, position = index, loc()
            advance()
            while index < len(text):
                if text[index] in "\r\n":
                    raise ParseError("Raw newlines are not allowed in STRING literals", loc())
                if text[index] == "'":
                    advance()
                    tokens.append(_Token("STRING_LITERAL", text[start:index], position))
                    break
                if text[index] == "$":
                    advance()
                    if index >= len(text):
                        raise ParseError("Unterminated STRING literal", position)
                    if text[index] in "\r\n":
                        raise ParseError("Raw newlines are not allowed in STRING literals", loc())
                advance()
            else:
                raise ParseError("Unterminated STRING literal", position)
        elif char.isascii() and (char.isalpha() or char == "_"):
            start, position = index, loc()
            while (
                index < len(text)
                and text[index].isascii()
                and (text[index].isalnum() or text[index] == "_")
            ):
                advance()
            word = text[start:index].upper()
            if word in _INTEGER_PREFIXES and index < len(text) and text[index] == "#":
                advance()
                if index < len(text) and text[index] in "+-":
                    advance()
                while (
                    index < len(text)
                    and text[index].isascii()
                    and (text[index].isalnum() or text[index] in "_#")
                ):
                    advance()
                tokens.append(_Token("INTEGER_LITERAL", text[start:index], position))
            elif word in {"T", "TIME"} and index < len(text) and text[index] == "#":
                advance()
                while (
                    index < len(text)
                    and text[index].isascii()
                    and (text[index].isalnum() or text[index] in "_.")
                ):
                    advance()
                tokens.append(_Token("TIME_LITERAL", text[start:index], position))
            else:
                tokens.append(_Token(word if word in _RESERVED else "ID", word, position))
        elif "0" <= char <= "9":
            start, position = index, loc()
            while index < len(text) and ("0" <= text[index] <= "9" or text[index] == "_"):
                advance()
            kind = "INT"
            if index < len(text) and text[index] == "#":
                while (
                    index < len(text)
                    and text[index].isascii()
                    and (text[index].isalnum() or text[index] in "_#")
                ):
                    advance()
                tokens.append(_Token("INTEGER_LITERAL", text[start:index], position))
                continue
            if index < len(text) and text[index] == "." and not text.startswith("..", index):
                kind = "FLOAT"
                advance()
                while index < len(text) and "0" <= text[index] <= "9":
                    advance()
            if index < len(text) and text[index] in "eE":
                kind = "FLOAT"
                advance()
                if index < len(text) and text[index] in "+-":
                    advance()
                exponent = index
                while index < len(text) and "0" <= text[index] <= "9":
                    advance()
                if index == exponent:
                    raise ParseError("Expected digits in floating exponent", position)
            tokens.append(_Token(kind, text[start:index], position))
        else:
            position = loc()
            pair = text[index : index + 2]
            if pair in {":=", "=>", "<>", "<=", ">=", ".."}:
                tokens.append(_Token(pair, pair, position))
                advance(2)
            elif char in ";:,.()+-*/=<>[]#^":
                tokens.append(_Token(char, char, position))
                advance()
            else:
                raise ParseError(f"Unsupported character {char!r}", position)
    tokens.append(_Token("EOF", "", loc()))
    return tokens


class _Parser:
    def __init__(self, tokens: list[_Token]):
        self.tokens = tokens
        self.index = 0

    @property
    def token(self) -> _Token:
        return self.tokens[self.index]

    def take(self) -> _Token:
        token = self.token
        self.index += 1
        return token

    def accept(self, kind: str) -> _Token | None:
        return self.take() if self.token.kind == kind else None

    def accept_ref_assign(self) -> _Token | None:
        # REF remains an identifier in expressions and named arguments. Combine
        # its adjacent '=' only where the grammar allows a binding operator.
        token = self.token
        if token.kind != "ID" or token.text != "REF":
            return None
        equals = self.tokens[self.index + 1]
        adjacent = Location(token.loc.source, token.loc.line, token.loc.column + 3)
        if equals.kind != "=" or equals.loc != adjacent:
            return None
        self.take()
        self.take()
        return _Token("REF=", "REF=", token.loc)

    def expect(self, kind: str) -> _Token:
        if self.token.kind != kind:
            raise ParseError(
                f"Expected {kind}, found {self.token.text or 'end of source'}", self.token.loc
            )
        return self.take()

    def program(self, gvl_name: str) -> Program:
        pous = []
        types = []
        interfaces = []
        globals_ = []
        global_location = None
        qualified_only = False
        while self.token.kind != "EOF":
            if self.accept("TYPE"):
                types.append(self.type_declaration())
                while self.token.kind != "END_TYPE":
                    types.append(self.type_declaration())
                self.expect("END_TYPE")
            elif self.token.kind in {"QUALIFIED_ONLY", "VAR_GLOBAL"}:
                if self.token.kind == "QUALIFIED_ONLY":
                    attribute = self.take()
                    if global_location is not None or self.token.kind != "VAR_GLOBAL":
                        raise ParseError(
                            "qualified_only must immediately precede the first VAR_GLOBAL section",
                            attribute.loc,
                        )
                    qualified_only = True
                section = self.expect("VAR_GLOBAL")
                if global_location is None:
                    global_location = section.loc
                constant = bool(self.accept("CONSTANT"))
                globals_.extend(
                    self.variable_declarations("VAR_GLOBAL", "END_VAR", constant=constant)
                )
                self.expect("END_VAR")
            elif self.token.kind == "INTERFACE":
                interfaces.append(self.interface_declaration())
            else:
                pous.append(self.pou())
        gvls = ()
        if global_location is not None:
            if (
                not isinstance(gvl_name, str)
                or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", gvl_name) is None
                or gvl_name.upper() in _RESERVED
            ):
                raise ParseError("Global list name must be a valid ST identifier", global_location)
            gvls = (
                GlobalVarList(gvl_name.upper(), tuple(globals_), global_location, qualified_only),
            )
        return Program(tuple(pous), tuple(types), gvls, tuple(interfaces))

    def interface_declaration(self) -> InterfaceDecl:
        start = self.expect("INTERFACE")
        name = self.expect("ID").text
        methods = []
        properties = []
        while self.token.kind in {"METHOD", "PROPERTY"}:
            if self.token.kind == "METHOD":
                methods.append(self.method(name, prototype=True))
            else:
                properties.append(self.property_declaration(name, prototype=True))
        self.expect("END_INTERFACE")
        return InterfaceDecl(name, tuple(methods), tuple(properties), start.loc)

    def variable_declarations(
        self, section: str, ending: str, *, constant: bool = False
    ) -> tuple[VarDecl, ...]:
        variables = []
        while self.token.kind != ending:
            names = [self.expect("ID")]
            while self.accept(","):
                names.append(self.expect("ID"))
            self.expect(":")
            type_name = self.type_spec()
            init_arguments = self.arguments() if self.token.kind == "(" else None
            element_init_arguments = None
            if (
                init_arguments is None
                and self.token.kind == "["
                and isinstance(type_name, (ArrayType, ArrayBounds))
            ):
                self.take()
                elements = []
                if self.token.kind != "]":
                    while True:
                        elements.append(self.arguments())
                        if not self.accept(","):
                            break
                self.expect("]")
                element_init_arguments = tuple(elements)
            initial = None
            if self.accept(":="):
                initial = (
                    self.expression()
                    if isinstance(type_name, ReferenceSpec)
                    else self.initializer()
                )
            elif operator := self.accept_ref_assign():
                if not isinstance(type_name, ReferenceSpec):
                    raise ParseError("REF= initializer requires REFERENCE TO", operator.loc)
                initial = self.expression()
            self.expect(";")
            variables.extend(
                VarDecl(
                    n.text,
                    type_name,
                    section,
                    initial,
                    n.loc,
                    constant=constant,
                    init_arguments=init_arguments,
                    element_init_arguments=element_init_arguments,
                )
                for n in names
            )
        return tuple(variables)

    def type_declaration(self) -> TypeDecl:
        name = self.expect("ID")
        self.expect(":")
        if self.accept("STRUCT"):
            definition = StructDecl(self.variable_declarations("VAR", "END_STRUCT"))
            self.expect("END_STRUCT")
        elif self.accept("("):
            members = []
            while True:
                member = self.expect("ID")
                value = self.signed_integer() if self.accept(":=") else None
                members.append(EnumMember(member.text, value, member.loc))
                if not self.accept(","):
                    break
            self.expect(")")
            base_type = self.take().text if self.token.kind == "ID" else "INT"
            definition = EnumDecl(tuple(members), base_type)
        else:
            definition = self.type_spec()
        initial = self.initializer() if self.accept(":=") else None
        if self.token.kind != "END_TYPE":
            self.expect(";")
        return TypeDecl(name.text, definition, initial, name.loc)

    def pou(self) -> Pou:
        attribute = self.accept("CALL_AFTER_INIT")
        if attribute and self.token.kind != "FUNCTION_BLOCK":
            raise ParseError(
                "call_after_init must immediately precede FUNCTION_BLOCK", attribute.loc
            )
        if self.token.kind not in {"FUNCTION", "FUNCTION_BLOCK", "PROGRAM"}:
            raise ParseError("Expected FUNCTION, FUNCTION_BLOCK or PROGRAM", self.token.loc)
        kind = self.take()
        name = self.expect("ID").text
        extends = None
        if extension := self.accept("EXTENDS"):
            if kind.kind != "FUNCTION_BLOCK":
                raise ParseError("EXTENDS requires a FUNCTION_BLOCK", extension.loc)
            extends = self.expect("ID").text
        implements = []
        if self.accept("IMPLEMENTS"):
            if kind.kind != "FUNCTION_BLOCK":
                raise ParseError("IMPLEMENTS requires a FUNCTION_BLOCK", kind.loc)
            while True:
                interface = self.expect("ID")
                if interface.text in implements:
                    raise ParseError(
                        f"Duplicate implemented interface {interface.text}", interface.loc
                    )
                implements.append(interface.text)
                if not self.accept(","):
                    break
        return_type = None
        if kind.kind == "FUNCTION":
            self.expect(":")
            return_type = self.type_spec()
        variables = []
        while self.token.kind in _SECTIONS:
            section_token = self.take()
            section = section_token.kind
            if section == "VAR_INST":
                raise ParseError("VAR_INST requires an FB METHOD", section_token.loc)
            if kind.kind == "PROGRAM" and section == "VAR_IN_OUT":
                raise ParseError("PROGRAM does not support VAR_IN_OUT", section_token.loc)
            constant = bool(self.accept("CONSTANT"))
            if constant and section != "VAR":
                raise ParseError("CONSTANT requires a local VAR section", self.token.loc)
            variables.extend(self.variable_declarations(section, "END_VAR", constant=constant))
            self.expect("END_VAR")
        ending = "END_" + kind.kind
        body = self.block(
            {ending, "METHOD", "PROPERTY", "CALL_AFTER_INIT"}
            if kind.kind == "FUNCTION_BLOCK"
            else {ending}
        )
        methods = []
        properties = []
        while kind.kind == "FUNCTION_BLOCK" and self.token.kind in {
            "METHOD",
            "PROPERTY",
            "CALL_AFTER_INIT",
        }:
            if self.token.kind in {"METHOD", "CALL_AFTER_INIT"}:
                methods.append(self.method(name))
            else:
                properties.append(self.property_declaration(name))
        self.expect(ending)
        return Pou(
            kind.kind,
            name,
            return_type,
            tuple(variables),
            body,
            kind.loc,
            tuple(methods),
            properties=tuple(properties),
            implements=tuple(implements),
            extends=extends,
            call_after_init=attribute is not None,
        )

    def method(self, owner: str, *, prototype: bool = False) -> Pou:
        attribute = self.accept("CALL_AFTER_INIT")
        if attribute and self.token.kind != "METHOD":
            raise ParseError("call_after_init must immediately precede METHOD", attribute.loc)
        start = self.expect("METHOD")
        access = (
            self.take().text if self.token.text in {"PUBLIC", "PROTECTED", "PRIVATE"} else "PUBLIC"
        )
        if prototype and access != "PUBLIC":
            raise ParseError("Interface methods must be PUBLIC", start.loc)
        name = self.expect("ID").text
        return_type = self.type_spec() if self.accept(":") else None
        variables = []
        while self.token.kind in _SECTIONS:
            section_token = self.take()
            if prototype and section_token.kind not in {"VAR_INPUT", "VAR_OUTPUT", "VAR_IN_OUT"}:
                raise ParseError(
                    "Interface methods support only formal parameters", section_token.loc
                )
            if section_token.kind == "VAR_TEMP":
                raise ParseError("METHOD does not support VAR_TEMP", section_token.loc)
            constant = bool(self.accept("CONSTANT"))
            if constant and section_token.kind != "VAR":
                raise ParseError("CONSTANT requires a local VAR section", self.token.loc)
            declarations = self.variable_declarations(
                section_token.kind, "END_VAR", constant=constant
            )
            if prototype and section_token.kind != "VAR_INPUT":
                for declaration in declarations:
                    if declaration.initial is not None:
                        raise ParseError(
                            "Only VAR_INPUT may have a prototype default", declaration.loc
                        )
            variables.extend(declarations)
            self.expect("END_VAR")
        body = self.block({"END_METHOD"})
        if prototype and body:
            raise ParseError("Interface methods must have empty bodies", body[0].loc)
        self.expect("END_METHOD")
        return Pou(
            "METHOD",
            f"{owner}.{name}",
            return_type,
            tuple(variables),
            body,
            start.loc,
            owner=owner,
            access=access,
            call_after_init=attribute is not None,
        )

    def property_declaration(self, owner: str, *, prototype: bool = False) -> Property:
        start = self.expect("PROPERTY")
        access = (
            self.take().text if self.token.text in {"PUBLIC", "PROTECTED", "PRIVATE"} else "PUBLIC"
        )
        if prototype and access != "PUBLIC":
            raise ParseError("Interface properties must be PUBLIC", start.loc)
        name = self.expect("ID").text
        self.expect(":")
        type_name = self.type_spec()
        if prototype and self.token.kind in _SECTIONS:
            raise ParseError("Interface properties cannot declare variables", self.token.loc)
        variables = self.property_variables()
        accessors = {}
        while self.token.text in {"GET", "SET"}:
            token = self.take()
            accessor_kind = token.text
            if accessor_kind in accessors:
                raise ParseError(f"Duplicate property {accessor_kind} accessor", token.loc)
            accessor_access = (
                self.take().text
                if self.token.text in {"PUBLIC", "PROTECTED", "PRIVATE"}
                else access
            )
            if prototype and accessor_access != "PUBLIC":
                raise ParseError("Interface accessors must be PUBLIC", token.loc)
            if prototype and self.token.kind in _SECTIONS:
                raise ParseError("Interface accessors cannot declare variables", self.token.loc)
            local = self.property_variables()
            body = self.block({"END_" + accessor_kind})
            if prototype and body:
                raise ParseError("Interface accessors must have empty bodies", body[0].loc)
            self.expect("END_" + accessor_kind)
            accessors[accessor_kind] = Pou(
                "PROPERTY_" + accessor_kind,
                f"{owner}.{name}.{accessor_kind}",
                type_name,
                variables + local,
                body,
                token.loc,
                owner=owner,
                access=accessor_access,
                property_name=name,
            )
        if not accessors:
            raise ParseError("PROPERTY requires GET and/or SET", self.token.loc)
        self.expect("END_PROPERTY")
        return Property(
            name,
            type_name,
            variables,
            accessors.get("GET"),
            accessors.get("SET"),
            start.loc,
            access,
        )

    def property_variables(self) -> tuple[VarDecl, ...]:
        variables = []
        while self.token.kind in _SECTIONS:
            section = self.take()
            if section.kind != "VAR":
                raise ParseError("Properties and accessors support only local VAR", section.loc)
            constant = bool(self.accept("CONSTANT"))
            variables.extend(self.variable_declarations("VAR", "END_VAR", constant=constant))
            self.expect("END_VAR")
        return tuple(variables)

    def scalar_type(self) -> TypeSpec | StringBounds | ReferenceSpec:
        if self.token.kind == "REFERENCE":
            return self.type_spec()
        token = self.expect("ID")
        if token.text != "STRING":
            return token.text
        if self.token.kind not in {"(", "["}:
            return StringType()
        ending = ")" if self.take().kind == "(" else "]"
        length = self.expression()
        self.expect(ending)
        if not isinstance(length, Literal):
            return StringBounds(length, token.loc)
        if type(length.value) is not int or (
            length.type_name is not None and length.type_name not in _INTEGER_PREFIXES
        ):
            raise ParseError("STRING capacity must be an integer", length.loc)
        try:
            return StringType(length.value)
        except (TypeError, ValueError) as error:
            raise ParseError(str(error), token.loc) from error

    def type_spec(
        self,
    ) -> TypeSpec | ArrayBounds | OpenArrayBounds | StringBounds | ReferenceSpec:
        start = self.token
        if self.accept("REFERENCE"):
            self.expect("TO")
            return ReferenceSpec(self.type_spec(), start.loc)
        if not self.accept("ARRAY"):
            return self.scalar_type()
        self.expect("[")
        if self.accept("*"):
            rank = 1
            while self.accept(","):
                self.expect("*")
                rank += 1
            self.expect("]")
            self.expect("OF")
            element_type = self.scalar_type()
            if isinstance(element_type, ReferenceSpec):
                return OpenArrayBounds(rank, element_type, start.loc)
            try:
                descriptor = OpenArrayType(
                    rank, "STRING" if isinstance(element_type, StringBounds) else element_type
                )
            except (TypeError, ValueError) as error:
                raise ParseError(str(error), start.loc) from error
            if isinstance(element_type, StringBounds):
                return OpenArrayBounds(rank, element_type, start.loc)
            return descriptor
        bounds = []
        while True:
            lower = self.expression()
            self.expect("..")
            upper = self.expression()
            bounds.append((lower, upper))
            if not self.accept(","):
                break
        self.expect("]")
        self.expect("OF")
        element_type = self.scalar_type()

        def literal_bound(expr):
            if isinstance(expr, Literal):
                if type(expr.value) is not int or (
                    expr.type_name is not None and expr.type_name not in _INTEGER_PREFIXES
                ):
                    raise ParseError("Array bounds must be integers", expr.loc)
                return expr.value
            if (
                isinstance(expr, Unary)
                and expr.op in {"+", "-"}
                and isinstance(expr.operand, Literal)
            ):
                value = literal_bound(expr.operand)
                return -value if expr.op == "-" else value
            return None

        literal_bounds = tuple((literal_bound(low), literal_bound(high)) for low, high in bounds)
        if isinstance(element_type, (StringBounds, ReferenceSpec)) or any(
            low is None or high is None for low, high in literal_bounds
        ):
            return ArrayBounds(tuple(bounds), element_type, start.loc)
        try:
            return ArrayType(literal_bounds, element_type)
        except (TypeError, ValueError) as error:
            raise ParseError(str(error), start.loc) from error

    def initializer(self) -> Initializer:
        if self.token.kind == "(" and (
            self.tokens[self.index + 1].kind == ")"
            or (
                self.tokens[self.index + 1].kind == "ID"
                and self.tokens[self.index + 2].kind == ":="
            )
        ):
            start = self.take()
            fields = []
            if self.token.kind != ")":
                while True:
                    name = self.expect("ID").text
                    self.expect(":=")
                    fields.append((name, self.initializer()))
                    if not self.accept(","):
                        break
            self.expect(")")
            return StructInitializer(tuple(fields), start.loc)
        if self.token.kind != "[":
            return self.expression()
        start = self.take()
        items = []
        if self.token.kind != "]":
            while True:
                count = 1
                repeated = (
                    self.token.kind in _INTEGER_TOKENS and self.tokens[self.index + 1].kind == "("
                )
                if repeated:
                    position = self.token.loc
                    count = self.integer()
                    if count <= 0:
                        raise ParseError("Initializer repetition must be positive", position)
                    self.expect("(")
                value = self.initializer()
                if repeated:
                    self.expect(")")
                items.append(ArrayItem(value, count))
                if not self.accept(","):
                    break
        self.expect("]")
        return ArrayInitializer(tuple(items), start.loc)

    def block(self, endings: set[str], *, case_labels: bool = False) -> tuple[Statement, ...]:
        statements = []
        while self.token.kind not in endings:
            if case_labels and self.starts_case_label():
                break
            if self.accept(";"):
                continue
            statements.append(self.statement())
        return tuple(statements)

    def statement(self) -> Statement:
        token = self.token
        kind = token.kind
        if kind == "IF":
            self.take()
            branches = []
            condition = self.expression()
            self.expect("THEN")
            branches.append((condition, self.block({"ELSIF", "ELSE", "END_IF"})))
            while self.accept("ELSIF"):
                condition = self.expression()
                self.expect("THEN")
                branches.append((condition, self.block({"ELSIF", "ELSE", "END_IF"})))
            otherwise = self.block({"END_IF"}) if self.accept("ELSE") else ()
            self.expect("END_IF")
            result = If(tuple(branches), otherwise, token.loc)
        elif kind == "CASE":
            self.take()
            selector = self.expression()
            self.expect("OF")
            arms = []
            while self.token.kind not in {"ELSE", "END_CASE"}:
                labels = [self.case_label()]
                while self.accept(","):
                    labels.append(self.case_label())
                self.expect(":")
                arms.append((tuple(labels), self.block({"ELSE", "END_CASE"}, case_labels=True)))
            otherwise = self.block({"END_CASE"}) if self.accept("ELSE") else ()
            self.expect("END_CASE")
            result = Case(selector, tuple(arms), otherwise, token.loc)
        elif kind == "FOR":
            self.take()
            variable = self.lvalue()
            self.expect(":=")
            start = self.expression()
            self.expect("TO")
            stop = self.expression()
            step = self.expression() if self.accept("BY") else Literal(1, token.loc)
            self.expect("DO")
            body = self.block({"END_FOR"})
            self.expect("END_FOR")
            result = For(variable, start, stop, step, body, token.loc)
        elif kind == "WHILE":
            self.take()
            condition = self.expression()
            self.expect("DO")
            body = self.block({"END_WHILE"})
            self.expect("END_WHILE")
            result = While(condition, body, token.loc)
        elif kind in {"RETURN", "EXIT"}:
            self.take()
            result = Return(token.loc) if kind == "RETURN" else Exit(token.loc)
        elif kind in {"ID", "THIS", "SUPER"}:
            target = self.lvalue()
            if self.accept(":="):
                result = Assign(target, self.expression(), token.loc)
            elif self.accept_ref_assign():
                result = RefAssign(target, self.expression(), token.loc)
            elif not isinstance(target, BitAccess) and self.token.kind == "(":
                result = CallStatement(self.call(target), token.loc)
            else:
                raise ParseError("Expected assignment or call", self.token.loc)
        else:
            raise ParseError(
                f"Unsupported or unexpected statement {token.text or 'end of source'}", token.loc
            )
        self.expect(";")
        return result

    def starts_case_label(self) -> bool:
        if self.token.kind in _INTEGER_TOKENS | {"+", "-"}:
            return True
        # A qualified enum label is distinguishable from a member assignment
        # by its following comma or colon. Do not consume the statement here.
        if self.token.kind != "ID":
            return False
        if self.tokens[self.index + 1].kind in {",", ":"}:
            return True
        return (
            self.tokens[self.index + 1].kind == "."
            and self.tokens[self.index + 2].kind == "ID"
            and self.tokens[self.index + 3].kind in {",", ":"}
        )

    def case_label(self) -> int | Reference:
        if self.token.kind == "ID":
            label = self.reference()
            if len(label.parts) > 2:
                raise ParseError("CASE labels require a local constant or Type.Member", label.loc)
            return label
        return self.signed_integer()

    def signed_integer(self) -> int:
        sign = -1 if self.accept("-") else 1
        if sign == 1:
            self.accept("+")
        return sign * self.integer()

    def integer(self) -> int:
        return self.integer_literal().value

    def integer_literal(self) -> Literal:
        token = self.token
        if token.kind not in _INTEGER_TOKENS:
            raise ParseError("Expected integer literal", token.loc)
        self.take()
        body = token.text.upper()
        type_name = None
        prefix, separator, remainder = body.partition("#")
        if separator and prefix in _INTEGER_PREFIXES:
            type_name, body = prefix, remainder
        sign = 1
        if type_name is not None and body.startswith(("+", "-")):
            sign = -1 if body[0] == "-" else 1
            body = body[1:]
        radix_text, separator, digits = body.partition("#")
        if separator:
            if radix_text not in {"2", "8", "16"}:
                raise ParseError("Integer literal base must be 2, 8 or 16", token.loc)
            radix = int(radix_text)
        else:
            radix, digits = 10, body
        alphabet = {2: "01", 8: "0-7", 10: "0-9", 16: "0-9A-F"}[radix]
        if re.fullmatch(f"[{alphabet}]+(?:_[{alphabet}]+)*", digits) is None:
            raise ParseError("Invalid integer literal digits or separators", token.loc)
        try:
            value = sign * int(digits.replace("_", ""), radix)
        except ValueError as error:
            raise ParseError(
                "Integer literal exceeds decimal conversion capacity", token.loc
            ) from error
        if type_name is None and separator:
            if value > 4294967295:
                raise ParseError("Based integer literal exceeds DWORD range", token.loc)
            type_name = "BYTE" if value <= 255 else "WORD" if value <= 65535 else "DWORD"
        if type_name is not None:
            try:
                check_value(type_name, value)
            except (TypeError, ValueError) as error:
                raise ParseError(str(error), token.loc) from error
        return Literal(value, token.loc, type_name)

    def reference(self) -> Reference:
        token = self.expect("ID")
        parts = [token.text]
        while self.token.kind == "." and self.tokens[self.index + 1].kind in {"ID", "ARRAY"}:
            self.take()
            parts.append(self.take().text)
        return Reference(tuple(parts), token.loc)

    def lvalue(self) -> LValue:
        if self.token.kind == "SUPER":
            token = self.take()
            self.expect("^")
            base = Super(token.loc)
        elif self.token.kind == "THIS":
            token = self.take()
            self.expect("^")
            self.expect(".")
            member = self.expect("ID")
            base = Member(This(token.loc), member.text, token.loc)
        else:
            base = self.reference()
        while True:
            if self.accept("["):
                indices = [self.expression()]
                while self.accept(","):
                    indices.append(self.expression())
                self.expect("]")
                base = Index(base, tuple(indices), base.loc)
            elif self.accept("."):
                if self.token.kind in _INTEGER_TOKENS:
                    base = BitAccess(base, self.integer_literal(), base.loc)
                else:
                    member = self.take() if self.token.kind == "ARRAY" else self.expect("ID")
                    base = Member(base, member.text, base.loc)
            else:
                return base

    def floating_literal(self, type_name: str = "LREAL", loc: Location | None = None) -> Literal:
        position = loc or self.token.loc
        sign = ""
        if loc is not None and self.token.kind in {"+", "-"}:
            sign = self.take().text
        token = self.token
        if token.kind not in {"INT", "FLOAT"}:
            raise ParseError("Expected floating literal", token.loc)
        self.take()
        try:
            value = float(sign + token.text)
        except ValueError as error:
            raise ParseError("Invalid floating literal", position) from error
        return Literal(value, position, type_name, sign + token.text)

    def call(self, target: LValue) -> Call:
        return Call(target, self.arguments(), target.loc)

    def arguments(self) -> tuple[Argument, ...]:
        self.expect("(")
        arguments = []
        if self.token.kind != ")":
            while True:
                position = self.token.loc
                name, mode = None, ""
                if self.token.kind == "ID" and self.tokens[self.index + 1].kind in {":=", "=>"}:
                    name = self.take().text
                    mode = self.take().kind
                arguments.append(Argument(name, mode, self.expression(), position))
                if not self.accept(","):
                    break
        self.expect(")")
        return tuple(arguments)

    def string_literal(self, loc: Location | None = None) -> Literal:
        token = self.expect("STRING_LITERAL")
        position = loc or token.loc
        body = token.text[1:-1]
        escapes = {"$": "$", "'": "'", "L": "\n", "N": "\n", "R": "\r", "T": "\t", "P": "\f"}
        decoded = []
        index = 0
        while index < len(body):
            char = body[index]
            index += 1
            if char == "$":
                if index >= len(body):
                    raise ParseError("Incomplete STRING escape", position)
                escape = body[index].upper()
                if escape in escapes:
                    char = escapes[escape]
                    index += 1
                elif re.fullmatch("[0-9A-Fa-f]{2}", body[index : index + 2]):
                    char = chr(int(body[index : index + 2], 16))
                    index += 2
                else:
                    raise ParseError("Invalid STRING dollar escape", position)
            decoded.append(char)
        try:
            type_name = StringType(max(1, len(decoded)))
            value = check_value(type_name, "".join(decoded))
        except (TypeError, ValueError) as error:
            raise ParseError(str(error), position) from error
        return Literal(value, position, type_name, token.text)

    def expression(self, minimum: int = 0) -> Expr:
        token = self.token
        if token.kind in {"+", "-", "NOT"}:
            self.take()
            left = Unary(token.kind, self.expression(8), token.loc)
        elif token.kind == "FLOAT":
            left = self.floating_literal()
        elif token.kind == "STRING_LITERAL":
            left = self.string_literal()
        elif token.kind == "TIME_LITERAL":
            self.take()
            try:
                left = Literal(parse_time_literal(token.text), token.loc, "TIME")
            except ValueError as error:
                raise ParseError(str(error), token.loc) from error
        elif token.kind in _INTEGER_TOKENS:
            left = self.integer_literal()
        elif token.kind in {"TRUE", "FALSE"}:
            self.take()
            left = Literal(token.kind == "TRUE", token.loc)
        elif self.accept("("):
            left = self.expression()
            self.expect(")")
        elif token.kind in {"ID", "THIS", "SUPER"}:
            if token.kind == "ID" and self.tokens[self.index + 1].kind == "#":
                self.take()
                self.take()
                if token.text == "STRING":
                    left = self.string_literal(token.loc)
                elif token.text in FLOAT_TYPES:
                    left = self.floating_literal(token.text, token.loc)
                else:
                    raise ParseError(f"Unsupported typed literal prefix {token.text}", token.loc)
            else:
                left = self.lvalue()
                if not isinstance(left, BitAccess) and self.token.kind == "(":
                    left = self.call(left)
        else:
            raise ParseError(
                f"Expected expression, found {token.text or 'end of source'}", token.loc
            )
        while (precedence := _PRECEDENCE.get(self.token.kind, -1)) >= minimum:
            operator = self.take()
            right = self.expression(precedence + 1)
            left = Binary(operator.kind, left, right, operator.loc)
        return left


def parse(
    text: str,
    source: str = "<string>",
    *,
    locations: Mapping[int, Location] | None = None,
    gvl_name: str = "GVL",
) -> Program:
    """Parse ST type declarations and POUs, preserving original source positions."""
    parser = _Parser(_lex(text, source, locations))
    try:
        return parser.program(gvl_name)
    except RecursionError as error:
        raise ParseError("Source nesting exceeds parser capacity", parser.token.loc) from error


def parse_type(
    text: str,
) -> TypeSpec | ArrayBounds | OpenArrayBounds | ReferenceSpec:
    """Parse one complete scalar or array type description safely."""
    parser = _Parser(_lex(text, "<type>", None))
    try:
        result = parser.type_spec()
    except RecursionError as error:
        raise ParseError("Source nesting exceeds parser capacity", parser.token.loc) from error
    parser.expect("EOF")
    if isinstance(result, StringBounds) or (
        isinstance(result, (ArrayBounds, OpenArrayBounds))
        and isinstance(result.element_type, StringBounds)
    ):
        raise ParseError("STRING capacity requires a literal without constant scope", result.loc)
    return result
