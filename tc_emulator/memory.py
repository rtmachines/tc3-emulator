"""Typed scalar/array storage with stable element aliases and immutable snapshots."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Protocol

from tc_emulator.bitwise import read_bit, write_bit
from tc_emulator.errors import ArgumentError, ExecutionError
from tc_emulator.standard_blocks import StandardBlockState
from tc_emulator.syntax import Location, Pou
from tc_emulator.timers import TimerState
from tc_emulator.types import (
    AliasType,
    ArrayType,
    FBArrayType,
    InterfaceArrayType,
    InterfaceType,
    ReferenceType,
    StructType,
    StructValue,
    TypeSpec,
    Value,
    check_value,
)


class MemoryOwner(Protocol):
    def _ensure_healthy(self) -> None: ...


class Cell:
    """Checked PLC storage usable as a VAR_IN_OUT or reference input argument."""

    __slots__ = ("_type_name", "_value", "_owner", "_items", "_members", "_read_only", "_lifetime")

    def __init__(
        self,
        type_name: TypeSpec,
        value: object,
        owner: MemoryOwner,
        *,
        read_only: bool = False,
        lifetime: Lifetime | None = None,
    ) -> None:
        normalized = check_value(type_name, value)
        self._type_name = type_name
        self._owner = owner
        self._read_only = read_only
        self._lifetime = lifetime or Lifetime()
        self._value = None
        self._items: tuple[Cell, ...] | None = None
        self._members: dict[str, Cell] | None = None
        kind = self._storage_type()
        if isinstance(kind, ArrayType):
            self._items = tuple(
                Cell(kind.element_type, item, owner, read_only=read_only, lifetime=self._lifetime)
                for item in self._flatten(normalized, len(kind.bounds))
            )
        elif isinstance(kind, StructType):
            self._members = {
                item.name: Cell(
                    item.type_name,
                    normalized[item.name],
                    owner,
                    read_only=read_only,
                    lifetime=self._lifetime,
                )
                for item in kind.fields
            }
        else:
            self._value = normalized

    def _storage_type(self) -> TypeSpec:
        kind = self._type_name
        while isinstance(kind, AliasType):
            kind = kind.target
        return kind

    @staticmethod
    def _flatten(value: tuple, dimensions: int):
        if dimensions == 1:
            yield from value
        else:
            for item in value:
                yield from Cell._flatten(item, dimensions - 1)

    @property
    def type_name(self) -> TypeSpec:
        """The declared scalar type or fixed array descriptor."""
        return self._type_name

    @property
    def read_only(self) -> bool:
        """Whether writes and VAR_IN_OUT binding are forbidden for this storage."""
        return self._read_only

    @property
    def value(self) -> Value:
        """Read a detached immutable snapshot, also after runtime failure."""
        kind = self._storage_type()
        if self._members is not None:
            return StructValue(
                kind.name, {name: cell.value for name, cell in self._members.items()}
            )
        if self._items is None:
            return self._value
        iterator = iter(self._items)
        shape = kind.shape

        def reshape(dimension: int) -> tuple:
            if dimension + 1 == len(shape):
                return tuple(next(iterator).value for _ in range(shape[dimension]))
            return tuple(reshape(dimension + 1) for _ in range(shape[dimension]))

        return reshape(0)

    def _replace(self, normalized: Value) -> None:
        if self._members is not None:
            for name, cell in self._members.items():
                cell._replace(normalized[name])
        elif self._items is None:
            self._value = normalized
        else:
            # Recurse without replacing children: IN_OUT may alias any descendant.
            dimensions = len(self._storage_type().bounds)
            for cell, value in zip(self._items, self._flatten(normalized, dimensions), strict=True):
                cell._replace(value)

    @value.setter
    def value(self, value: object) -> None:
        self._owner._ensure_healthy()
        if self.read_only:
            raise ArgumentError("Cannot write a read-only constant cell")
        try:
            normalized = check_value(self.type_name, value)
        except (TypeError, ValueError) as error:
            raise ArgumentError(str(error)) from error
        self._replace(normalized)

    def _write(self, value: object, loc: Location) -> None:
        if self.read_only:
            raise ExecutionError("Cannot write a read-only constant cell", loc)
        try:
            normalized = check_value(self.type_name, value)
        except (TypeError, ValueError) as error:
            raise ExecutionError(str(error), loc) from error
        self._replace(normalized)

    def _element(self, indices: tuple[int, ...]) -> Cell:
        kind = self._storage_type()
        if not isinstance(kind, ArrayType):
            raise TypeError("Cannot index a scalar cell")
        if len(indices) != len(kind.bounds):
            raise IndexError("Wrong number of array indices")
        offset = 0
        for index, (low, high) in zip(indices, kind.bounds, strict=True):
            if type(index) is not int:
                raise TypeError("Array indices must be integers, not BOOL")
            if not low <= index <= high:
                raise IndexError(f"Array index {index} outside [{low}, {high}]")
            offset = offset * (high - low + 1) + index - low
        return self._items[offset]

    def element(self, *indices: int) -> Cell:
        """Access a scalar element using ST indices, for reads or alias binding."""
        try:
            return self._element(indices)
        except (TypeError, IndexError) as error:
            raise ArgumentError(str(error)) from error

    def _field(self, name: str) -> Cell:
        if not isinstance(name, str):
            raise TypeError("Structure field name must be a string")
        if self._members is None:
            raise TypeError("Field access requires a structure cell")
        if name.upper() not in self._members:
            raise ValueError(f"Unknown structure field {name}")
        return self._members[name.upper()]

    def field(self, name: str) -> Cell:
        """Get a live child cell, usable as an IN_OUT reference at any depth."""
        try:
            return self._field(name)
        except (TypeError, ValueError) as error:
            raise ArgumentError(str(error)) from error

    def _bit(self, index: int) -> BitCell:
        return BitCell(self, index)

    def bit(self, index: int) -> BitCell:
        """Get a live BOOL view of an integer bit, using a zero-based index."""
        try:
            return self._bit(index)
        except (TypeError, ValueError) as error:
            raise ArgumentError(str(error)) from error


class BitCell(Cell):
    """A BOOL view writing through one stable parent cell, never an IN_OUT cell."""

    __slots__ = ("_parent", "_index")

    def __init__(self, parent: Cell, index: int) -> None:
        read_bit(parent.value, parent.type_name, index)
        super().__init__(
            "BOOL", False, parent._owner, read_only=parent.read_only, lifetime=parent._lifetime
        )
        self._parent = parent
        self._index = index

    @Cell.value.getter
    def value(self) -> bool:
        return read_bit(self._parent.value, self._parent.type_name, self._index)

    def _replace(self, normalized: Value) -> None:
        value = write_bit(self._parent.value, self._parent.type_name, self._index, normalized)
        self._parent._replace(value)


def _array_offset(bounds: tuple[tuple[int, int], ...], indices: tuple[int, ...]) -> int:
    """Check indices in declaration order and return their row-major offset."""
    if len(indices) != len(bounds):
        raise IndexError("Wrong number of array indices")
    offset = 0
    for index, (low, high) in zip(indices, bounds, strict=True):
        if type(index) is not int:
            raise TypeError("Array indices must be integers, not BOOL")
        if not low <= index <= high:
            raise IndexError(f"Array index {index} outside [{low}, {high}]")
        offset = offset * (high - low + 1) + index - low
    return offset


def _array_snapshot(items: Iterator[Frame | InterfaceSlot], shape: tuple[int, ...]) -> tuple:
    """Inspect row-major storage lazily while restoring its declared shape."""

    def reshape(dimension: int) -> tuple:
        if dimension + 1 == len(shape):
            return tuple(next(items).inspect() for _ in range(shape[dimension]))
        return tuple(reshape(dimension + 1) for _ in range(shape[dimension]))

    return reshape(0)


@dataclass
class FBArray:
    """Fixed instance storage, with distinct row-major function-block frames."""

    type_name: FBArrayType
    items: tuple[Frame, ...]

    def _element(self, indices: tuple[int, ...]) -> Frame:
        return self.items[_array_offset(self.type_name.bounds, indices)]

    def inspect(self) -> tuple:
        """Return a detached nested snapshot with the declared array shape."""
        return _array_snapshot(iter(self.items), self.type_name.shape)


@dataclass
class Lifetime:
    """An ST ownership lifetime, independent of Python object retention."""

    alive: bool = True


@dataclass
class InterfaceSlot:
    """A non-owning nominal reference; deliberately not a value Cell."""

    type_name: InterfaceType
    target: Frame | None = None

    def capture(self, loc: Location, *, dispatch: bool = False) -> Frame | None:
        if self.target is not None and not self.target.lifetime.alive:
            raise ExecutionError("Expired interface target", loc)
        if dispatch and self.target is None:
            raise ExecutionError("Null interface target", loc)
        return self.target

    def bind(self, target: Frame | None, loc: Location) -> None:
        if target is not None and not target.lifetime.alive:
            raise ExecutionError("Expired interface target", loc)
        self.target = target

    def inspect(self) -> dict[str, object]:
        return {
            "interface": self.type_name.name,
            "target": self.target.pou.name if self.target is not None else None,
            "valid": self.target is not None and self.target.lifetime.alive,
        }


@dataclass
class InterfaceArray:
    """Fixed non-owning storage, with distinct row-major interface slots."""

    type_name: InterfaceArrayType
    items: tuple[InterfaceSlot, ...]

    def _element(self, indices: tuple[int, ...]) -> InterfaceSlot:
        return self.items[_array_offset(self.type_name.bounds, indices)]

    def inspect(self) -> tuple:
        """Return a detached nested snapshot with the declared array shape."""
        return _array_snapshot(iter(self.items), self.type_name.shape)


@dataclass
class ReferenceSlot:
    """A data binding whose target keeps its original storage lifetime."""

    type_name: ReferenceType
    target: Cell | None = None

    @property
    def valid(self) -> bool:
        return self.target is not None and self.target._lifetime.alive

    def capture(self, loc: Location, *, dereference: bool = False) -> Cell | None:
        if self.target is not None and not self.target._lifetime.alive:
            raise ExecutionError("Expired reference target", loc)
        if dereference and self.target is None:
            raise ExecutionError("Null reference target", loc)
        return self.target

    def bind(self, target: Cell | None, loc: Location) -> None:
        if target is not None and not target._lifetime.alive:
            raise ExecutionError("Expired reference target", loc)
        self.target = target

    def inspect(self) -> dict[str, object]:
        return {
            "reference": str(self.type_name.target),
            "target": str(self.target.type_name) if self.target is not None else None,
            "valid": self.valid,
        }


@dataclass
class Frame:
    """One invocation's locals or one persistent FB instance."""

    pou: Pou
    slots: dict[str, Cell | Frame | FBArray | InterfaceArray | InterfaceSlot | ReferenceSlot | None]
    lifetime: Lifetime = field(default_factory=Lifetime)
    initialized: bool = False
    prepared: bool = False
    timer: TimerState | None = None
    standard: StandardBlockState | None = None
    method_owner: Frame | None = None
    method_instances: dict[
        str,
        dict[str, Cell | Frame | FBArray | InterfaceArray | InterfaceSlot | ReferenceSlot | None],
    ] = field(default_factory=dict)

    def inspect(self) -> dict[str, object]:
        def snapshot(slots):
            return {
                name: value.inspect()
                if isinstance(value, (Frame, FBArray, InterfaceArray, InterfaceSlot, ReferenceSlot))
                else value.value
                if isinstance(value, Cell)
                else None
                for name, value in slots.items()
            }

        result = snapshot(self.slots)
        if self.method_instances:
            short_names = [name.rsplit(".", 1)[-1] for name in self.method_instances]
            result["$VAR_INST"] = {
                (
                    name
                    if short_names.count(name.rsplit(".", 1)[-1]) > 1
                    else name.rsplit(".", 1)[-1]
                ): snapshot(slots)
                for name, slots in self.method_instances.items()
            }
        return result
