"""Immutable syntax for the supported Structured Text subset."""

from __future__ import annotations

from dataclasses import dataclass

from .types import Scalar, TypeSpec, Value


@dataclass(frozen=True)
class Location:
    source: str
    line: int
    column: int


@dataclass(frozen=True)
class Literal:
    value: Scalar
    loc: Location
    type_name: TypeSpec | None = None
    raw_text: str | None = None


@dataclass(frozen=True)
class Reference:
    parts: tuple[str, ...]
    loc: Location


@dataclass(frozen=True)
class This:
    loc: Location


@dataclass(frozen=True)
class Super:
    loc: Location


@dataclass(frozen=True)
class Index:
    base: LValue
    indices: tuple[Expr, ...]
    loc: Location


@dataclass(frozen=True)
class Member:
    base: LValue
    name: str
    loc: Location


@dataclass(frozen=True)
class BitAccess:
    base: LValue
    index: Expr
    loc: Location


LValue = Reference | This | Super | Index | Member | BitAccess


@dataclass(frozen=True)
class Unary:
    op: str
    operand: Expr
    loc: Location


@dataclass(frozen=True)
class Binary:
    op: str
    left: Expr
    right: Expr
    loc: Location


@dataclass(frozen=True)
class Argument:
    name: str | None
    mode: str
    value: Expr
    loc: Location


@dataclass(frozen=True)
class Call:
    target: LValue
    arguments: tuple[Argument, ...]
    loc: Location


Expr = Literal | Reference | This | Super | Index | Member | BitAccess | Unary | Binary | Call


@dataclass(frozen=True)
class ArrayItem:
    value: Initializer
    count: int = 1


@dataclass(frozen=True)
class ArrayInitializer:
    items: tuple[ArrayItem, ...]
    loc: Location


@dataclass(frozen=True)
class StructInitializer:
    fields: tuple[tuple[str, Initializer], ...]
    loc: Location


Initializer = Expr | ArrayInitializer | StructInitializer


@dataclass(frozen=True)
class Assign:
    target: LValue
    value: Expr
    loc: Location


@dataclass(frozen=True)
class RefAssign:
    target: LValue
    value: Expr
    loc: Location


@dataclass(frozen=True)
class CallStatement:
    call: Call
    loc: Location


@dataclass(frozen=True)
class If:
    branches: tuple[tuple[Expr, tuple[Statement, ...]], ...]
    otherwise: tuple[Statement, ...]
    loc: Location


@dataclass(frozen=True)
class Case:
    selector: Expr
    arms: tuple[tuple[tuple[int | Reference, ...], tuple[Statement, ...]], ...]
    otherwise: tuple[Statement, ...]
    loc: Location


@dataclass(frozen=True)
class For:
    variable: LValue
    start: Expr
    stop: Expr
    step: Expr
    body: tuple[Statement, ...]
    loc: Location


@dataclass(frozen=True)
class While:
    condition: Expr
    body: tuple[Statement, ...]
    loc: Location


@dataclass(frozen=True)
class Return:
    loc: Location


@dataclass(frozen=True)
class Exit:
    loc: Location


Statement = Assign | RefAssign | CallStatement | If | Case | For | While | Return | Exit


@dataclass(frozen=True)
class StringBounds:
    """A STRING capacity expression awaiting constant resolution."""

    length: Expr
    loc: Location


@dataclass(frozen=True)
class ArrayBounds:
    """An array type whose expression bounds await constant resolution."""

    bounds: tuple[tuple[Expr, Expr], ...]
    element_type: TypeSpec | StringBounds | ReferenceSpec
    loc: Location


@dataclass(frozen=True)
class OpenArrayBounds:
    """An open array parameter whose STRING capacity awaits constant resolution."""

    rank: int
    element_type: TypeSpec | StringBounds | ReferenceSpec
    loc: Location


@dataclass(frozen=True)
class ReferenceSpec:
    """A reference target awaiting semantic resolution and validation."""

    target: TypeSpec | ArrayBounds | OpenArrayBounds | StringBounds | ReferenceSpec
    loc: Location


@dataclass(frozen=True)
class VarDecl:
    name: str
    type_name: TypeSpec | ArrayBounds | OpenArrayBounds | StringBounds | ReferenceSpec
    section: str
    initial: Initializer | None
    loc: Location
    default: Value | None = None
    constant: bool = False


@dataclass(frozen=True)
class StructDecl:
    fields: tuple[VarDecl, ...]


@dataclass(frozen=True)
class EnumMember:
    name: str
    value: int | None
    loc: Location


@dataclass(frozen=True)
class EnumDecl:
    members: tuple[EnumMember, ...]
    base_type: str = "INT"


@dataclass(frozen=True)
class TypeDecl:
    name: str
    definition: (
        TypeSpec
        | ArrayBounds
        | OpenArrayBounds
        | StringBounds
        | ReferenceSpec
        | StructDecl
        | EnumDecl
    )
    initial: Initializer | None
    loc: Location


@dataclass(frozen=True)
class Property:
    name: str
    type_name: TypeSpec | ArrayBounds | OpenArrayBounds | StringBounds | ReferenceSpec
    variables: tuple[VarDecl, ...]
    getter: Pou | None
    setter: Pou | None
    loc: Location
    access: str = "PUBLIC"


@dataclass(frozen=True)
class Pou:
    kind: str
    name: str
    return_type: TypeSpec | ArrayBounds | OpenArrayBounds | StringBounds | ReferenceSpec | None
    variables: tuple[VarDecl, ...]
    body: tuple[Statement, ...]
    loc: Location
    methods: tuple[Pou, ...] = ()
    owner: str | None = None
    access: str = "PUBLIC"
    properties: tuple[Property, ...] = ()
    property_name: str | None = None
    implements: tuple[str, ...] = ()
    extends: str | None = None

    @property
    def result_name(self) -> str:
        return self.property_name or self.name.rsplit(".", 1)[-1]


@dataclass(frozen=True)
class GlobalVarList:
    name: str
    variables: tuple[VarDecl, ...]
    loc: Location
    qualified_only: bool = False


@dataclass(frozen=True)
class InterfaceDecl:
    name: str
    methods: tuple[Pou, ...]
    properties: tuple[Property, ...]
    loc: Location


@dataclass(frozen=True)
class Program:
    pous: tuple[Pou, ...]
    types: tuple[TypeDecl, ...] = ()
    gvls: tuple[GlobalVarList, ...] = ()
    interfaces: tuple[InterfaceDecl, ...] = ()
