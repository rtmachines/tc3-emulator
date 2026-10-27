"""Public Python API for deterministic tests of the supported ST subset."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from tc_emulator import syntax as st
from tc_emulator.errors import ArgumentError, ExecutionError, ParseError, RuntimeFaultedError
from tc_emulator.execution import Context, Engine
from tc_emulator.loader import load_files
from tc_emulator.memory import BitCell, Cell, FBArray, Frame, InterfaceSlot
from tc_emulator.parser import parse, parse_type
from tc_emulator.types import (
    InterfaceType,
    TypeSpec,
    Value,
    check_value,
    inout_compatible,
    resolve_type,
    value_leaf_count,
)
from tc_emulator.validation import validate


@dataclass(frozen=True)
class CallResult:
    """Function or method return value and snapshot of its additional outputs."""

    value: Value | None
    outputs: Mapping[str, Value]


class _OutputSnapshot(Mapping[str, Value]):
    """Read-only output values with ST name lookup and canonical iteration."""

    def __init__(self, values: dict[str, Value]) -> None:
        self._values = MappingProxyType(values)

    def __getitem__(self, name: str) -> Value:
        return self._values[_name(name)]

    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)


def _name(name: str) -> str:
    if not isinstance(name, str):
        raise ArgumentError("Names must be strings")
    return name.upper()


class Runtime:
    """A validated program and its isolated, sequential execution state."""

    def __init__(
        self,
        program: st.Program,
        *,
        max_steps: int = 100_000,
        max_call_depth: int = 128,
    ) -> None:
        for name, value in (("max_steps", max_steps), ("max_call_depth", max_call_depth)):
            if type(value) is not int or value <= 0:
                raise ArgumentError(f"{name} must be a positive integer")
        self._registry = validate(program)
        self._max_steps = max_steps
        self._max_call_depth = max_call_depth
        self._faulted = False
        self._now_ms = 0
        self._engine = Engine(self._registry, self)

    @classmethod
    def from_source(
        cls,
        text: str,
        source: str = "<string>",
        *,
        gvl_name: str = "GVL",
        max_steps: int = 100_000,
        max_call_depth: int = 128,
    ) -> Runtime:
        """Parse and validate every POU in a string without executing it."""
        return cls(
            parse(text, source, gvl_name=gvl_name),
            max_steps=max_steps,
            max_call_depth=max_call_depth,
        )

    @classmethod
    def from_files(
        cls,
        paths: Iterable[str | Path],
        *,
        max_steps: int = 100_000,
        max_call_depth: int = 128,
    ) -> Runtime:
        """Load .st/.TcPOU/.TcDUT/.TcGVL/.TcIO, resolving forward references together."""
        return cls(load_files(paths), max_steps=max_steps, max_call_depth=max_call_depth)

    def _ensure_healthy(self) -> None:
        if self._faulted:
            raise RuntimeFaultedError("Runtime is faulted; create a new Runtime for the next test")

    @property
    def now_ms(self) -> int:
        """Read virtual time in milliseconds, also after a runtime failure."""
        return self._now_ms

    def advance_time(self, milliseconds: int) -> int:
        """Advance the clock without executing code; FB outputs change on calls only."""
        self._ensure_healthy()
        if type(milliseconds) is not int or milliseconds < 0:
            raise ArgumentError("milliseconds must be a nonnegative integer, not BOOL")
        self._now_ms += milliseconds
        return self._now_ms

    def _pou(self, name: str, kind: str) -> st.Pou:
        self._ensure_healthy()
        canonical = _name(name)
        if canonical not in self._registry:
            raise ArgumentError(f"Unknown POU {name}")
        pou = self._registry[canonical]
        if pou.kind != kind:
            raise ArgumentError(f"{name} is not a {kind}", pou.loc)
        return pou

    def cell(self, type_name: TypeSpec, value: object) -> Cell:
        """Create a scalar or fixed-array variable that can be passed as VAR_IN_OUT."""
        self._ensure_healthy()
        try:
            resolved = resolve_type(
                parse_type(type_name) if isinstance(type_name, str) else type_name,
                self._registry.types,
            )
            if value_leaf_count(resolved) > 1_000_000:
                raise ValueError("Value type exceeds the 1000000 scalar leaf limit")
            return Cell(resolved, value, self)
        except (TypeError, ValueError, ParseError) as error:
            raise ArgumentError(str(error)) from error

    def instantiate(self, name: str) -> FBHandle:
        """Create an independent FB instance with its declared initial state."""
        return FBHandle(self, self._new_frame(self._pou(name, "FUNCTION_BLOCK")))

    def _new_frame(self, pou: st.Pou, method_owner: Frame | None = None) -> Frame:
        try:
            if method_owner is not None:
                return self._engine.new_method_frame(pou, method_owner)
            return self._engine.new_frame(pou)
        except RecursionError as error:
            self._faulted = True
            raise ExecutionError("Instance nesting limit exceeded", pou.loc, (pou.name,)) from error

    def call(self, name: str, /, **inputs: Value | Cell | FBHandle) -> CallResult:
        """Call a function with fresh local state and named input arguments."""
        pou = self._pou(name, "FUNCTION")
        arguments = self._arguments(pou, inputs)
        frame = self._new_frame(pou)
        self._execute(frame, arguments)
        return CallResult(
            frame.slots[pou.name].value,
            _OutputSnapshot(
                {
                    decl.name: frame.slots[decl.name].value
                    for decl in pou.variables
                    if decl.section == "VAR_OUTPUT"
                }
            ),
        )

    def _arguments(
        self,
        pou: st.Pou,
        inputs: dict[str, Value | Cell | FBHandle],
    ) -> dict[str, Value | Cell | Frame | None]:
        """Validate every Python argument before changing any persistent memory."""
        self._ensure_healthy()
        declarations = {
            decl.name: decl for decl in pou.variables if decl.section in ("VAR_INPUT", "VAR_IN_OUT")
        }
        normalized: dict[str, Value | Cell | Frame | None] = {}
        for name, value in inputs.items():
            canonical = _name(name)
            if canonical in normalized:
                raise ArgumentError(f"Duplicate argument {name}", pou.loc)
            if canonical not in declarations:
                raise ArgumentError(f"Unknown input argument {name}", pou.loc)
            decl = declarations[canonical]
            if isinstance(decl.type_name, InterfaceType):
                normalized[canonical] = self._interface_argument(decl.type_name, value, pou.loc)
            elif decl.section == "VAR_IN_OUT":
                if isinstance(value, BitCell):
                    raise ArgumentError(
                        f"{name}: a bit view cannot be passed as VAR_IN_OUT", pou.loc
                    )
                if not isinstance(value, Cell):
                    raise ArgumentError(f"{name} requires a Cell for VAR_IN_OUT", pou.loc)
                if value.read_only:
                    raise ArgumentError(
                        f"{name}: a read-only constant cell cannot be passed as VAR_IN_OUT", pou.loc
                    )
                if value._owner is not self:
                    raise ArgumentError(f"{name}: cell belongs to a different runtime", pou.loc)
                if not inout_compatible(decl.type_name, value.type_name):
                    raise ArgumentError(f"{name} requires exact type {decl.type_name}", pou.loc)
                normalized[canonical] = value
            else:
                try:
                    normalized[canonical] = check_value(decl.type_name, value)
                except (TypeError, ValueError) as error:
                    raise ArgumentError(f"{name}: {error}", pou.loc) from error
        for decl in declarations.values():
            if (
                pou.kind == "FUNCTION"
                or decl.section == "VAR_IN_OUT"
                or (pou.kind == "METHOD" and decl.initial is None)
            ) and decl.name not in normalized:
                raise ArgumentError(f"Missing required argument {decl.name}", pou.loc)
        return normalized

    def _interface_argument(
        self, kind: InterfaceType, value: object, loc: st.Location
    ) -> Frame | None:
        if type(value) is int and value == 0:
            return None
        if not isinstance(value, FBHandle) or value._runtime is not self:
            raise ArgumentError(
                "Interface input requires a same-runtime FBHandle or integer 0", loc
            )
        if value._frame.pou.name not in self._registry.implementers[kind.name]:
            raise ArgumentError(f"Function block does not implement {kind.name}", loc)
        if not value._frame.lifetime.alive:
            raise ArgumentError("Expired function-block handle", loc)
        return value._frame

    def _persistent_cell(
        self, frames: dict[str, Frame], owner_name: str, variable_name: str
    ) -> Cell:
        canonical_owner, canonical_variable = _name(owner_name), _name(variable_name)
        frame = frames.get(canonical_owner)
        if frame is None:
            raise ArgumentError(f"Unknown storage namespace {owner_name}")
        for decl in frame.pou.variables:
            if decl.name == canonical_variable and decl.section != "VAR_TEMP":
                cell = frame.slots[canonical_variable]
                if isinstance(cell, Cell):
                    return cell
                raise ArgumentError(f"{variable_name} is not a value cell", decl.loc)
        raise ArgumentError(f"Unknown stored variable {variable_name}", frame.pou.loc)

    def global_cell(self, gvl_name: str, variable_name: str) -> Cell:
        """Get live global VALUE storage, including after a runtime fault."""
        return self._persistent_cell(self._engine.global_frames, gvl_name, variable_name)

    def program_cell(self, program_name: str, variable_name: str) -> Cell:
        """Get persistent PROGRAM VALUE storage; VAR_TEMP is invocation-local."""
        return self._persistent_cell(self._engine.program_frames, program_name, variable_name)

    def _stored_fb(self, frame: Frame, variable_name: str, indices: tuple[int, ...]) -> FBHandle:
        canonical = _name(variable_name)
        for decl in frame.pou.variables:
            if decl.name != canonical or decl.section == "VAR_TEMP":
                continue
            storage = frame.slots[canonical]
            if isinstance(storage, FBArray):
                try:
                    return FBHandle(self, storage._element(indices))
                except (TypeError, IndexError) as error:
                    raise ArgumentError(str(error), decl.loc) from error
            if isinstance(storage, Frame):
                if indices:
                    raise ArgumentError("Scalar function block does not accept indices", decl.loc)
                return FBHandle(self, storage)
            raise ArgumentError(f"{variable_name} is not a function block", decl.loc)
        raise ArgumentError(f"Unknown stored function block {variable_name}", frame.pou.loc)

    def _namespace_fb(
        self,
        frames: dict[str, Frame],
        owner_name: str,
        variable_name: str,
        indices: tuple[int, ...],
    ) -> FBHandle:
        frame = frames.get(_name(owner_name))
        if frame is None:
            raise ArgumentError(f"Unknown storage namespace {owner_name}")
        return self._stored_fb(frame, variable_name, indices)

    def program_fb(self, program_name: str, variable_name: str, *indices: int) -> FBHandle:
        """Select a persistent PROGRAM instance using its original ST indices."""
        return self._namespace_fb(self._engine.program_frames, program_name, variable_name, indices)

    def global_fb(self, gvl_name: str, variable_name: str, *indices: int) -> FBHandle:
        """Select an existing GVL instance, including after a runtime fault."""
        return self._namespace_fb(self._engine.global_frames, gvl_name, variable_name, indices)

    def _programs(self, names: tuple[str, ...]) -> tuple[Frame, ...]:
        self._ensure_healthy()
        if not names:
            raise ArgumentError("At least one PROGRAM name is required")
        canonical = tuple(_name(name) for name in names)
        if len(set(canonical)) != len(canonical):
            raise ArgumentError("Duplicate PROGRAM names are not allowed")
        for name in canonical:
            self._pou(name, "PROGRAM")
        return tuple(self._engine.program_frames[name] for name in canonical)

    def _scan(self, frames: tuple[Frame, ...]) -> None:
        context = Context(self._max_steps, self._max_call_depth, now_ms=self._now_ms)
        try:
            for frame in frames:
                self._engine.invoke(frame, {}, context, frame.pou.loc)
        except ExecutionError:
            self._faulted = True
            raise

    def scan(self, *programs: str) -> None:
        """Execute unique PROGRAMs in order at one time and with one step budget."""
        self._scan(self._programs(programs))

    def run_cycles(self, *programs: str, cycles: int, period_ms: int) -> None:
        """Run scans, advancing virtual time after each successful whole cycle."""
        frames = self._programs(programs)
        if type(cycles) is not int or cycles < 0:
            raise ArgumentError("cycles must be a nonnegative integer, not BOOL")
        if type(period_ms) is not int or period_ms <= 0:
            raise ArgumentError("period_ms must be a positive integer, not BOOL")
        for _ in range(cycles):
            self._scan(frames)
            self._now_ms += period_ms

    def _execute(self, frame: Frame, inputs: dict[str, Value | Cell | Frame | None]) -> None:
        self._ensure_healthy()
        context = Context(self._max_steps, self._max_call_depth, now_ms=self._now_ms)
        try:
            self._engine.invoke(frame, inputs, context, frame.pou.loc)
        except ExecutionError:
            self._faulted = True
            raise


class FBHandle:
    """A persistent FB instance controlled from a Python test."""

    def __init__(self, runtime: Runtime, frame: Frame) -> None:
        self._runtime = runtime
        self._frame = frame

    def call(self, /, **inputs: Value | Cell | FBHandle) -> None:
        """Execute the body once, retaining omitted inputs and FB state."""
        arguments = self._runtime._arguments(self._frame.pou, inputs)
        self._runtime._execute(self._frame, arguments)

    def fb(self, variable_name: str, *indices: int) -> FBHandle:
        """Select a persistent nested instance or fixed-array element."""
        return self._runtime._stored_fb(self._frame, variable_name, indices)

    def call_method(self, name: str, /, **inputs: Value | Cell | FBHandle) -> CallResult:
        """Call a PUBLIC method with fresh locals, preserving its owner's state."""
        self._runtime._ensure_healthy()
        qualified = f"{self._frame.pou.name}.{_name(name)}"
        pou = self._runtime._registry.get(qualified)
        if pou is None or pou.kind != "METHOD":
            raise ArgumentError(f"Unknown method {name}", self._frame.pou.loc)
        if pou.access != "PUBLIC":
            raise ArgumentError(f"Cannot call PRIVATE method {name}", pou.loc)
        arguments = self._runtime._arguments(pou, inputs)
        frame = self._runtime._new_frame(pou, self._frame)
        self._runtime._execute(frame, arguments)
        return CallResult(
            frame.slots[pou.result_name].value if pou.return_type is not None else None,
            _OutputSnapshot(
                {
                    decl.name: frame.slots[decl.name].value
                    for decl in pou.variables
                    if decl.section == "VAR_OUTPUT"
                }
            ),
        )

    def _property(self, name: str, *, writable: bool) -> st.Pou:
        self._runtime._ensure_healthy()
        prop = self._runtime._registry.properties.get((self._frame.pou.name, _name(name)))
        if prop is None:
            raise ArgumentError(f"Unknown property {name}", self._frame.pou.loc)
        accessor = prop.setter if writable else prop.getter
        if accessor is None:
            raise ArgumentError(
                f"Property {name} has no {'SET' if writable else 'GET'} accessor", prop.loc
            )
        if prop.access != "PUBLIC" or accessor.access != "PUBLIC":
            raise ArgumentError(f"Cannot access PRIVATE property {name}", prop.loc)
        return accessor

    def _execute_property(self, accessor: st.Pou, value: Value | None = None) -> Value:
        runtime = self._runtime
        context = Context(runtime._max_steps, runtime._max_call_depth, now_ms=runtime._now_ms)
        try:
            return runtime._engine.invoke_property(
                self._frame, accessor, context, accessor.loc, value
            )
        except ExecutionError:
            runtime._faulted = True
            raise

    def get_property(self, name: str, /) -> Value:
        """Execute an available PUBLIC getter without executing the FB body."""
        return self._execute_property(self._property(name, writable=False))

    def set_property(self, name: str, value: Value, /) -> None:
        """Validate the value before executing an available PUBLIC setter."""
        accessor = self._property(name, writable=True)
        try:
            normalized = check_value(accessor.return_type, value)
        except (TypeError, ValueError) as error:
            raise ArgumentError(f"{name}: {error}", accessor.loc) from error
        self._execute_property(accessor, normalized)

    def _field(self, name: str, section: str) -> Cell | InterfaceSlot:
        canonical = _name(name)
        for decl in self._frame.pou.variables:
            if decl.name == canonical and decl.section == section:
                return self._frame.slots[canonical]
        raise ArgumentError(f"Unknown {section} variable {name}", self._frame.pou.loc)

    def set_input(self, name: str, value: Value | FBHandle) -> None:
        """Set a VAR_INPUT without executing the FB."""
        self._runtime._ensure_healthy()
        target = self._field(name, "VAR_INPUT")
        if isinstance(target, InterfaceSlot):
            target.bind(
                self._runtime._interface_argument(target.type_name, value, self._frame.pou.loc),
                self._frame.pou.loc,
            )
        else:
            target.value = value

    def output(self, name: str) -> Value:
        """Read a VAR_OUTPUT without executing, also after a runtime failure."""
        return self._field(name, "VAR_OUTPUT").value

    def inspect(self) -> dict[str, object]:
        """Return a detached snapshot of public and internal state for diagnostics."""
        return self._frame.inspect()
