"""Sequential execution of validated ST syntax, with a shared call budget."""

from __future__ import annotations

from dataclasses import dataclass, field

from tc_emulator import syntax as st
from tc_emulator.bitwise import bitwise_result_type, bitwise_value
from tc_emulator.errors import ExecutionError
from tc_emulator.memory import (
    Cell,
    FBArray,
    Frame,
    InterfaceSlot,
    Lifetime,
    MemoryOwner,
    ReferenceSlot,
)
from tc_emulator.standard_blocks import STANDARD_BLOCK_NAMES, StandardBlockState
from tc_emulator.standard_functions import bind_arguments, evaluate, selection_index
from tc_emulator.timers import TIMER_NAMES, TimerState
from tc_emulator.types import (
    FLOAT_TYPES,
    INTEGER_TYPES,
    EnumType,
    FBArrayType,
    InterfaceType,
    ReferenceType,
    StringType,
    TypeSpec,
    Value,
    array_initial_value,
    canonical_type,
    check_float_literal,
    check_value,
    checked_integer,
    default_value,
    is_value_type,
    numeric_type,
    trunc_div,
)
from tc_emulator.validation import Registry


@dataclass
class Context:
    remaining: int
    max_depth: int
    stack: list[str] = field(default_factory=list)
    now_ms: int = 0

    def tick(self, loc: st.Location) -> None:
        self.remaining -= 1
        if self.remaining < 0:
            raise ExecutionError("Execution step budget exhausted", loc, tuple(self.stack))


class _Return(Exception):
    pass


class _Exit(Exception):
    pass


def initial_value(decl: st.VarDecl) -> Value:
    """Evaluate validated declaration constants without running ST bodies."""
    if decl.default is not None:
        return decl.default
    if decl.initial is None:
        return default_value(decl.type_name)

    def constant(expr: st.Expr) -> Value:
        if isinstance(expr, st.Literal):
            if expr.type_name in FLOAT_TYPES or type(expr.value) is float:
                return check_float_literal(expr.type_name or "LREAL", expr.value, expr.raw_text)
            return expr.value
        if isinstance(expr, st.Unary):
            value = constant(expr.operand)
            if expr.op == "NOT":
                return not value
            return -value if expr.op == "-" else value
        raise ExecutionError("Invalid constant initializer", expr.loc)

    if isinstance(decl.initial, st.ArrayInitializer):

        def elements():
            for item in decl.initial.items:
                value = constant(item.value)
                for _ in range(item.count):
                    yield value

        return array_initial_value(decl.type_name, elements())
    return constant(decl.initial)


class Engine:
    def __init__(self, registry: Registry, owner: MemoryOwner) -> None:
        self.registry = registry
        self.owner = owner
        self.global_frames: dict[str, Frame] = {}
        self.program_frames: dict[str, Frame] = {}
        for name, pou in registry.items():
            if pou.kind not in {"GVL", "PROGRAM"}:
                continue
            frames = self.global_frames if pou.kind == "GVL" else self.program_frames
            try:
                frames[name] = self.new_frame(pou)
            except RecursionError as error:
                raise ExecutionError(
                    "Instance nesting limit exceeded", pou.loc, (pou.name,)
                ) from error

        for frame in (*self.global_frames.values(), *self.program_frames.values()):
            self.initialize_owned(frame)

    def _variable(
        self, decl: st.VarDecl, lifetime: Lifetime | None = None
    ) -> Cell | Frame | FBArray | InterfaceSlot | ReferenceSlot | None:
        if decl.section == "VAR_IN_OUT":
            return None
        if isinstance(decl.type_name, ReferenceType):
            return ReferenceSlot(decl.type_name)
        if isinstance(decl.type_name, InterfaceType):
            return InterfaceSlot(decl.type_name)
        if is_value_type(decl.type_name):
            return Cell(
                decl.type_name,
                initial_value(decl),
                self.owner,
                read_only=decl.constant,
                lifetime=lifetime,
            )
        if isinstance(decl.type_name, FBArrayType):
            return FBArray(
                decl.type_name,
                tuple(
                    self.new_frame(self.registry[decl.type_name.element_type], lifetime)
                    for _ in range(decl.type_name.size)
                ),
            )
        return self.new_frame(self.registry[decl.type_name], lifetime)

    def new_frame(self, pou: st.Pou, lifetime: Lifetime | None = None) -> Frame:
        lifetime = lifetime or Lifetime()
        frame = Frame(
            pou,
            {
                decl.name: self._variable(decl, lifetime)
                for decl in self.registry.variables_for(pou)
                if decl.section != "VAR_INST"
            },
            lifetime=lifetime,
        )
        if pou.kind == "FUNCTION_BLOCK":
            frame.method_instances = {
                method.name: {
                    decl.name: self._variable(decl, lifetime)
                    for decl in self.registry[method.name].variables
                    if decl.section == "VAR_INST"
                }
                for method in self.registry.instance_methods(pou)
                if any(decl.section == "VAR_INST" for decl in self.registry[method.name].variables)
            }
        if pou.name in TIMER_NAMES:
            frame.timer = TimerState(pou.name)
        elif pou.name in STANDARD_BLOCK_NAMES:
            frame.standard = StandardBlockState(pou.name)
        if pou.return_type is not None:
            frame.slots[pou.result_name] = Cell(
                pou.return_type, default_value(pou.return_type), self.owner, lifetime=lifetime
            )
        return frame

    def new_method_frame(self, pou: st.Pou, owner: Frame) -> Frame:
        """Allocate invocation-local storage linked to its persistent FB owner."""
        frame = self.new_frame(pou)
        frame.method_owner = owner
        frame.slots.update(owner.method_instances.get(pou.name, {}))
        return frame

    def initialize_storage(self, storage) -> None:
        if isinstance(storage, Frame):
            self.initialize_owned(storage)
        elif isinstance(storage, FBArray):
            for frame in storage.items:
                self.initialize_owned(frame)

    def initialize_owned(self, frame: Frame) -> None:
        """Bind persistent declarations only after the entire owned tree exists."""
        if frame.initialized:
            return
        frame.initialized = True
        for decl in self.registry.variables_for(frame.pou):
            if decl.section != "VAR_TEMP":
                self.initialize_storage(frame.slots.get(decl.name))
        if frame.pou.kind == "FUNCTION_BLOCK":
            for owner in self.registry.lineages.get(frame.pou.name, (frame.pou.name,)):
                lexical = Frame(
                    self.registry[owner], {}, lifetime=frame.lifetime, method_owner=frame
                )
                self.initialize_references(lexical, {"VAR", "VAR_INPUT"})
        elif frame.pou.kind in {"PROGRAM", "GVL"}:
            self.initialize_references(frame, {"VAR", "VAR_INPUT"})
        for method_name, slots in frame.method_instances.items():
            method = Frame(
                self.registry[method_name], slots, lifetime=frame.lifetime, method_owner=frame
            )
            for storage in slots.values():
                self.initialize_storage(storage)
            self.initialize_references(method, {"VAR_INST"})

    def initialize_references(
        self, frame: Frame, sections: set[str], ctx: Context | None = None, *, supplied=()
    ) -> None:
        for decl in frame.pou.variables:
            if (
                isinstance(decl.type_name, ReferenceType)
                and decl.section in sections
                and decl.initial is not None
                and decl.name not in supplied
            ):
                slot = self.resolve(st.Reference((decl.name,), decl.loc), frame, ctx)
                slot.bind(self.reference_value(decl.initial, frame, ctx), decl.loc)

    def reference_value(
        self, expr: st.Expr, frame: Frame, ctx: Context | None = None
    ) -> Cell | None:
        if isinstance(expr, st.Literal):
            return None
        target = self.resolve(expr, frame, ctx)
        if isinstance(target, ReferenceSlot):
            return target.capture(expr.loc)
        if isinstance(target, Cell):
            if not target._lifetime.alive:
                raise ExecutionError("Expired reference target", expr.loc)
            return target
        raise ExecutionError("Reference binding requires value storage", expr.loc)

    def owner_has(self, frame: Frame, name: str) -> bool:
        """Only the executing declaration's lexical fields precede globals."""
        owner = self.registry.lexical_owner(frame.pou)
        return (
            frame.method_owner is not None
            and owner is not None
            and any(var.name == name for var in self.registry.variables_for(self.registry[owner]))
        )

    def resolve(
        self, ref: st.LValue, frame: Frame, ctx: Context | None = None
    ) -> Cell | Frame | FBArray | InterfaceSlot | ReferenceSlot:
        if isinstance(ref, (st.This, st.Super)):
            return frame.method_owner or frame
        if id(ref) in self.registry.bit_accesses:
            base, index = self.registry.bit_accesses[id(ref)]
            return self.storage(base, frame, ctx)._bit(index)
        if isinstance(ref, st.Member):
            try:
                base = (
                    frame
                    if isinstance(ref.base, st.This)
                    and frame.pou.kind == "FUNCTION_BLOCK"
                    and ref.name in frame.slots
                    else self.resolve(ref.base, frame, ctx)
                )
                if isinstance(base, ReferenceSlot):
                    base = base.capture(ref.loc, dereference=True)
                if isinstance(base, Frame):
                    if ref.name not in base.slots:
                        raise ValueError(f"Unknown variable {ref.name}")
                    result = base.slots[ref.name]
                    if result is None:
                        raise ValueError(f"Unbound VAR_IN_OUT {ref.name}")
                    return result
                return base._field(ref.name)
            except (TypeError, ValueError) as error:
                raise ExecutionError(str(error), ref.loc) from error
        if isinstance(ref, st.Index):
            base = self.resolve(ref.base, frame, ctx)
            if isinstance(base, ReferenceSlot):
                base = base.capture(ref.loc, dereference=True)
            if not isinstance(base, (Cell, FBArray)):
                raise ExecutionError("Expected array storage", ref.loc)
            try:
                indices = tuple(self.expression(index, frame, ctx) for index in ref.indices)
                return base._element(indices)
            except (TypeError, IndexError) as error:
                raise ExecutionError(str(error), ref.loc) from error
        root = ref.parts[0]
        if root in frame.slots:
            current: Cell | Frame | FBArray | InterfaceSlot | ReferenceSlot | None = frame.slots[
                root
            ]
        elif self.owner_has(frame, root):
            current = frame.method_owner.slots[root]
        elif root in self.global_frames:
            current = self.global_frames[root]
        elif root in self.program_frames:
            current = self.program_frames[root]
        else:
            candidates = self.registry.global_variables.get(root, ())
            if len(candidates) != 1:
                message = "Ambiguous" if candidates else "Unknown"
                raise ExecutionError(f"{message} variable {root}", ref.loc)
            current = self.global_frames[candidates[0]].slots[root]
        for part in ref.parts[1:]:
            if isinstance(current, ReferenceSlot):
                current = current.capture(ref.loc, dereference=True)
            if isinstance(current, Cell):
                try:
                    current = current._field(part)
                except (TypeError, ValueError) as error:
                    raise ExecutionError(str(error), ref.loc) from error
            elif isinstance(current, Frame) and part in current.slots:
                current = current.slots[part]
            else:
                raise ExecutionError(f"Unknown variable {'.'.join(ref.parts)}", ref.loc)
        if current is None:
            raise ExecutionError(f"Unbound VAR_IN_OUT {'.'.join(ref.parts)}", ref.loc)
        return current

    def storage(self, ref: st.LValue, frame: Frame, ctx: Context | None = None) -> Cell:
        result = self.resolve(ref, frame, ctx)
        if isinstance(result, ReferenceSlot):
            result = result.capture(ref.loc, dereference=True)
        if not isinstance(result, Cell):
            raise ExecutionError("Expected a stored variable", ref.loc)
        return result

    def property_owner(self, receiver: st.LValue | None, frame: Frame, ctx: Context) -> Frame:
        owner = (
            (frame.method_owner or frame)
            if receiver is None
            else self.resolve(receiver, frame, ctx)
        )
        if isinstance(owner, InterfaceSlot):
            owner = owner.capture(
                receiver.loc if receiver is not None else frame.pou.loc, dispatch=True
            )
        if not isinstance(owner, Frame):
            raise ExecutionError("Property receiver is not a function block", frame.pou.loc)
        return owner

    def invoke_property(
        self,
        owner: Frame,
        accessor: st.Pou,
        ctx: Context,
        loc: st.Location,
        value: Value | None = None,
        *,
        static: bool = False,
    ) -> Value:
        """Use the ordinary invocation context for implicit and Python access."""
        accessor = self.registry.dispatch(owner.pou.name, accessor, static=static)
        if accessor.kind == "PROPERTY_SET":
            try:
                value = check_value(accessor.return_type, value)
            except (TypeError, ValueError) as error:
                raise ExecutionError(str(error), loc, tuple(ctx.stack)) from error
        try:
            target = self.new_method_frame(accessor, owner)
        except RecursionError as error:
            raise ExecutionError(
                "Instance nesting limit exceeded", loc, (*ctx.stack, accessor.name)
            ) from error
        inputs = {accessor.result_name: value} if accessor.kind == "PROPERTY_SET" else {}
        self.invoke(target, inputs, ctx, loc)
        return target.slots[accessor.result_name].value

    def invoke(
        self,
        frame: Frame,
        inputs: dict[str, Value | Cell | Frame | None],
        ctx: Context,
        loc: st.Location,
        *,
        body: st.Pou | None = None,
    ) -> None:
        for value in inputs.values():
            if isinstance(value, Cell) and value.read_only:
                raise ExecutionError("Cannot bind a read-only constant cell as VAR_IN_OUT", loc)
        if len(ctx.stack) >= ctx.max_depth:
            raise ExecutionError("Call depth limit exceeded", loc, tuple(ctx.stack))
        persistent = None
        if frame.pou.kind == "FUNCTION_BLOCK" and frame.timer is None and frame.standard is None:
            # Keep only temporaries in the activation. Persistent references use
            # lexical owner lookup against the live root, including IN_OUT aliases
            # rebound while this body is suspended inside SUPER.
            persistent = frame
            declaration = body or frame.pou
            frame = Frame(
                declaration,
                {},
                lifetime=persistent.lifetime,
                method_owner=persistent,
            )
        ctx.stack.append(frame.pou.name)
        temporary_lifetime = Lifetime()
        try:
            self.initialize_owned(persistent or frame)
            for decl in self.registry.variables_for(frame.pou):
                if decl.section == "VAR_TEMP":
                    frame.slots[decl.name] = self._variable(decl, temporary_lifetime)
                    if persistent is not None and persistent.pou.name == frame.pou.name:
                        persistent.slots[decl.name] = frame.slots[decl.name]
            input_slots = persistent.slots if persistent is not None else frame.slots
            for name, value in inputs.items():
                if isinstance(input_slots[name], ReferenceSlot):
                    input_slots[name].bind(value, loc)
                elif isinstance(value, Cell):
                    input_slots[name] = value
                else:
                    target = input_slots[name]
                    if isinstance(target, InterfaceSlot):
                        target.bind(value, loc)
                        continue
                    if not isinstance(target, Cell):
                        raise ExecutionError(f"Invalid input {name}", loc)
                    target._write(value, loc)
            for decl in self.registry.variables_for(frame.pou):
                if decl.section == "VAR_TEMP":
                    self.initialize_storage(frame.slots[decl.name])
            sections = (
                {"VAR_TEMP"}
                if frame.pou.kind in {"FUNCTION_BLOCK", "PROGRAM"}
                else {"VAR", "VAR_INPUT"}
            )
            self.initialize_references(frame, sections, ctx, supplied=inputs)
            try:
                if frame.timer is not None:
                    ctx.tick(loc)
                    q, elapsed = frame.timer.update(
                        frame.slots["IN"].value, frame.slots["PT"].value, ctx.now_ms
                    )
                    frame.slots["Q"]._write(q, loc)
                    frame.slots["ET"]._write(elapsed, loc)
                elif frame.standard is not None:
                    ctx.tick(loc)
                    values = {name: cell.value for name, cell in frame.slots.items()}
                    for name, value in frame.standard.update(values).items():
                        frame.slots[name]._write(value, loc)
                else:
                    self.statements(frame.pou.body, frame, ctx)
            except _Return:
                pass
        except ExecutionError as error:
            if not error.stack:
                raise ExecutionError(error.message, error.loc or loc, tuple(ctx.stack)) from error
            raise
        except RecursionError as error:
            raise ExecutionError(
                "Interpreter nesting limit exceeded", loc, tuple(ctx.stack)
            ) from error
        finally:
            temporary_lifetime.alive = False
            if frame.pou.kind in {"FUNCTION", "METHOD", "PROPERTY_GET", "PROPERTY_SET"}:
                frame.lifetime.alive = False
            ctx.stack.pop()

    def _call(self, call: st.Call, caller: Frame, ctx: Context) -> Value | None:
        if id(call) in self.registry.valid_reference_calls:
            ctx.tick(call.loc)
            operand = self.registry.valid_reference_calls[id(call)]
            return self.resolve(operand, caller, ctx).valid
        if id(call) in self.registry.bound_calls:
            reference, dimension_expr, upper = self.registry.bound_calls[id(call)]
            ctx.tick(call.loc)
            array = self.resolve(reference, caller, ctx)
            if isinstance(array, ReferenceSlot):
                array = array.capture(call.loc, dereference=True)
            kind = canonical_type(array.type_name)
            dimension = self.expression(dimension_expr, caller, ctx)
            if type(dimension) is not int or not 1 <= dimension <= len(kind.bounds):
                raise ExecutionError(
                    f"Array dimension must be between 1 and {len(kind.bounds)}",
                    call.loc,
                    tuple(ctx.stack),
                )
            return kind.bounds[dimension - 1][1 if upper else 0]
        if id(call) in self.registry.builtin_calls:
            return self._standard_call(call, caller, ctx)
        root = call.target.parts[0] if isinstance(call.target, st.Reference) else None
        method = self.registry.method_calls.get(id(call))
        method_owner = None
        if method is not None:
            receiver, qualified_name = method
            method_owner = (
                caller.method_owner or caller
                if receiver is None
                else self.resolve(receiver, caller, ctx)
            )
            if isinstance(method_owner, InterfaceSlot):
                method_owner = method_owner.capture(call.loc, dispatch=True)
            if not isinstance(method_owner, Frame):
                raise ExecutionError("Method receiver is not a function block", call.loc)
            declaration = (
                self.registry.prototype_pous.get(qualified_name) or self.registry[qualified_name]
            )
            pou = self.registry.dispatch(
                method_owner.pou.name, declaration, static=id(call) in self.registry.static_dispatch
            )
        elif id(call) in self.registry.super_calls:
            target = caller.method_owner or caller
            pou = self.registry[self.registry.super_calls[id(call)]]
        elif (
            isinstance(call.target, st.Reference)
            and len(call.target.parts) == 1
            and root not in caller.slots
            and not self.owner_has(caller, root)
            and root not in self.program_frames
            and root not in self.global_frames
            and root not in self.registry.global_variables
        ):
            target = self.new_frame(self.registry[root])
            pou = target.pou
        else:
            target = self.resolve(call.target, caller, ctx)
            if not isinstance(target, Frame):
                raise ExecutionError("Call target is not a function block", call.loc)
            pou = target.pou
        variables = {decl.name: decl for decl in self.registry.variables_for(pou)}
        positional = [
            decl for decl in variables.values() if decl.section in ("VAR_INPUT", "VAR_IN_OUT")
        ]
        inputs: dict[str, Value | Cell | Frame | None] = {}
        outputs: list[tuple[str, Cell]] = []
        for index, argument in enumerate(call.arguments):
            name = argument.name if argument.name is not None else positional[index].name
            decl = variables[name]
            if argument.mode == "=>":
                outputs.append((name, self.storage(argument.value, caller, ctx)))
            elif decl.section == "VAR_IN_OUT":
                inputs[name] = self.storage(argument.value, caller, ctx)
            elif isinstance(decl.type_name, ReferenceType):
                inputs[name] = self.reference_value(argument.value, caller, ctx)
            elif isinstance(decl.type_name, InterfaceType):
                inputs[name] = self.interface_value(argument.value, caller, ctx)
            else:
                inputs[name] = self.expression(argument.value, caller, ctx)
        if method_owner is not None:
            # Check all evaluated values before allocating fresh method storage.
            for name, value in inputs.items():
                if variables[name].section == "VAR_INPUT" and not isinstance(
                    variables[name].type_name, (InterfaceType, ReferenceType)
                ):
                    try:
                        inputs[name] = check_value(variables[name].type_name, value)
                    except (TypeError, ValueError) as error:
                        raise ExecutionError(str(error), call.loc, tuple(ctx.stack)) from error
            try:
                target = self.new_method_frame(pou, method_owner)
            except RecursionError as error:
                raise ExecutionError(
                    "Instance nesting limit exceeded", call.loc, (*ctx.stack, pou.name)
                ) from error
        self.invoke(
            target,
            inputs,
            ctx,
            call.loc,
            body=pou if id(call) in self.registry.super_calls else None,
        )
        for name, cell in outputs:
            output = target.slots[name]
            cell._write(output.value, call.loc)
        if pou.return_type is not None:
            return target.slots[pou.result_name].value
        return None

    def interface_value(self, expr: st.Expr, frame: Frame, ctx: Context) -> Frame | None:
        """Capture a validated identity without treating it as a scalar value."""
        if isinstance(expr, st.Literal):
            return None
        source = self.resolve(expr, frame, ctx)
        if isinstance(source, InterfaceSlot):
            return source.capture(expr.loc)
        if isinstance(source, Frame):
            if not source.lifetime.alive:
                raise ExecutionError("Expired interface target", expr.loc)
            return source
        raise ExecutionError("Expected interface or function-block reference", expr.loc)

    def _standard_call(self, call: st.Call, caller: Frame, ctx: Context) -> Value:
        """Execute checked builtins without evaluating unselected SEL/MUX branches."""
        ctx.tick(call.loc)
        name = call.target.parts[0]
        ordered = bind_arguments(name, call.arguments)
        try:
            if name in {"SEL", "MUX"}:
                selector = self.expression(ordered[0].value, caller, ctx)
                chosen = selection_index(name, selector, len(ordered) - 1)
                value = self.expression(ordered[chosen].value, caller, ctx)
                result_type = self.registry.builtin_calls[id(call)]
                return (
                    checked_integer(value)
                    if result_type == "INTEGER"
                    else check_value(result_type, value)
                )
            # Eager named arguments retain source evaluation order, then bind by name.
            values = {
                id(argument): self._typed_expression(argument.value, caller, ctx)
                for argument in call.arguments
            }
            return evaluate(name, tuple(values[id(argument)] for argument in ordered))[0]
        except (TypeError, ValueError, ZeroDivisionError, OverflowError) as error:
            raise ExecutionError(str(error), call.loc, tuple(ctx.stack)) from error

    def expression(self, expr: st.Expr, frame: Frame, ctx: Context) -> Value:
        return self._typed_expression(expr, frame, ctx)[0]

    def _typed_expression(
        self,
        expr: st.Expr,
        frame: Frame,
        ctx: Context,
    ) -> tuple[Value, TypeSpec]:
        try:
            if id(expr) in self.registry.property_reads:
                receiver, name = self.registry.property_reads[id(expr)]
                owner = self.property_owner(receiver, frame, ctx)
                accessor = self.registry.prototype_pous.get(name) or self.registry[name]
                return self.invoke_property(
                    owner, accessor, ctx, expr.loc, static=id(expr) in self.registry.static_dispatch
                ), canonical_type(accessor.return_type)
            if isinstance(expr, st.Literal):
                if isinstance(expr.type_name, StringType) or type(expr.value) is str:
                    kind = expr.type_name or StringType(max(1, len(expr.value)))
                    return check_value(kind, expr.value), canonical_type(kind)
                if expr.type_name in INTEGER_TYPES:
                    return check_value(expr.type_name, expr.value), expr.type_name
                if expr.type_name == "TIME":
                    return check_value("TIME", expr.value), "TIME"
                if expr.type_name in FLOAT_TYPES or type(expr.value) is float:
                    kind = expr.type_name or "LREAL"
                    return check_float_literal(kind, expr.value, expr.raw_text), kind
                return expr.value, "BOOL" if type(expr.value) is bool else "INTEGER"
            if (
                isinstance(expr, st.Reference)
                and len(expr.parts) == 2
                and expr.parts[0] not in frame.slots
                and not self.owner_has(frame, expr.parts[0])
                and expr.parts[0] not in self.registry.global_variables
            ):
                kind = canonical_type(self.registry.types.get(expr.parts[0], ""))
                if isinstance(kind, EnumType):
                    return check_value(kind, expr.parts[1]), kind
            if isinstance(expr, (st.Reference, st.Index, st.Member, st.BitAccess)):
                cell = self.storage(expr, frame, ctx)
                return cell.value, canonical_type(cell.type_name)
            if isinstance(expr, st.Call):
                value = self._call(expr, frame, ctx)
                if value is None:
                    raise ExecutionError("FB cannot be used as an expression", expr.loc)
                if id(expr) in self.registry.valid_reference_calls:
                    return value, "BOOL"
                if id(expr) in self.registry.builtin_calls:
                    return value, self.registry.builtin_calls[id(expr)]
                if id(expr) in self.registry.bound_calls:
                    return value, "DINT"
                if id(expr) in self.registry.method_calls:
                    _, method_name = self.registry.method_calls[id(expr)]
                    return value, canonical_type(
                        (
                            self.registry.prototype_pous.get(method_name)
                            or self.registry[method_name]
                        ).return_type
                    )
                return value, canonical_type(self.registry[expr.target.parts[0]].return_type)
            if isinstance(expr, st.Unary):
                value, kind = self._typed_expression(expr.operand, frame, ctx)
                if expr.op == "NOT":
                    result_type = bitwise_result_type("NOT", kind)
                    return bitwise_value("NOT", value, None, result_type), result_type
                result = -value if expr.op == "-" else value
                return (
                    (check_value(kind, result), kind)
                    if kind in FLOAT_TYPES or kind == "TIME"
                    else (checked_integer(result), "INTEGER")
                )
            if id(expr) in self.registry.interface_comparisons:
                reference = self.registry.interface_comparisons[id(expr)]
                target = self.interface_value(reference, frame, ctx)
                return (target is None if expr.op == "=" else target is not None), "BOOL"
            if isinstance(expr, st.Binary):
                left, left_type = self._typed_expression(expr.left, frame, ctx)
                if expr.op in {"AND_THEN", "OR_ELSE"}:
                    if (expr.op == "AND_THEN" and not left) or (expr.op == "OR_ELSE" and left):
                        return left, "BOOL"
                    return self.expression(expr.right, frame, ctx), "BOOL"
                right, right_type = self._typed_expression(expr.right, frame, ctx)
                if expr.op in {"AND", "OR", "XOR"}:
                    result_type = bitwise_result_type(expr.op, left_type, right_type)
                    return bitwise_value(expr.op, left, right, result_type), result_type
                if isinstance(left_type, StringType) and isinstance(right_type, StringType):
                    kind = left_type
                elif left_type == right_type and (
                    left_type in {"BOOL", "TIME"} or isinstance(left_type, EnumType)
                ):
                    kind = left_type
                else:
                    kind = numeric_type(left_type, right_type)
                    if kind in FLOAT_TYPES:
                        left, right = check_value(kind, left), check_value(kind, right)
                result = self._binary(expr.op, left, right, kind)
                return result, "BOOL" if type(result) is bool else kind
        except (ValueError, ZeroDivisionError, TypeError, OverflowError) as error:
            raise ExecutionError(str(error), expr.loc, tuple(ctx.stack)) from error
        raise ExecutionError("Unsupported expression", expr.loc)

    @staticmethod
    def _binary(op: str, left: Value, right: Value, kind: TypeSpec) -> Value:
        if isinstance(kind, EnumType):
            left, right = left.value, right.value
        if op in ("+", "-", "*", "/", "MOD"):
            if op == "+":
                value = left + right
            elif op == "-":
                value = left - right
            elif op == "*":
                value = left * right
            elif op == "/":
                value = left / right if kind in FLOAT_TYPES else trunc_div(left, right)
            else:
                value = left - trunc_div(left, right) * right
            return (
                check_value(kind, value)
                if kind in FLOAT_TYPES or kind == "TIME"
                else checked_integer(value)
            )
        if op == "=":
            return left == right
        if op == "<>":
            return left != right
        if op == "<":
            return left < right
        if op == "<=":
            return left <= right
        if op == ">":
            return left > right
        if op == ">=":
            return left >= right
        if op == "AND":
            return left and right
        if op == "OR":
            return left or right
        if op == "XOR":
            return left != right
        raise ValueError(f"Unsupported operator {op}")

    def statements(self, body: tuple[st.Statement, ...], frame: Frame, ctx: Context) -> None:
        for statement in body:
            ctx.tick(statement.loc)
            if isinstance(statement, st.RefAssign):
                target = self.resolve(statement.target, frame, ctx)
                target.bind(self.reference_value(statement.value, frame, ctx), statement.loc)
            elif isinstance(statement, st.Assign):
                prop = self.registry.property_writes.get(id(statement.target))
                if prop is not None:
                    receiver, name = prop
                    owner = self.property_owner(receiver, frame, ctx)
                    value = self.expression(statement.value, frame, ctx)
                    self.invoke_property(
                        owner,
                        self.registry.prototype_pous.get(name) or self.registry[name],
                        ctx,
                        statement.loc,
                        value,
                        static=id(statement.target) in self.registry.static_dispatch,
                    )
                else:
                    target = self.resolve(statement.target, frame, ctx)
                    if isinstance(target, InterfaceSlot):
                        target.bind(
                            self.interface_value(statement.value, frame, ctx), statement.loc
                        )
                    else:
                        if isinstance(target, ReferenceSlot):
                            target = target.capture(statement.loc, dereference=True)
                        target._write(self.expression(statement.value, frame, ctx), statement.loc)
            elif isinstance(statement, st.CallStatement):
                self._call(statement.call, frame, ctx)
            elif isinstance(statement, st.If):
                for condition, branch in statement.branches:
                    if self.expression(condition, frame, ctx):
                        self.statements(branch, frame, ctx)
                        break
                else:
                    self.statements(statement.otherwise, frame, ctx)
            elif isinstance(statement, st.Case):
                selector = self.expression(statement.selector, frame, ctx)
                for labels, branch in statement.arms:
                    values = (
                        self.expression(label, frame, ctx)
                        if isinstance(label, st.Reference)
                        else label
                        for label in labels
                    )
                    if selector in values:
                        self.statements(branch, frame, ctx)
                        break
                else:
                    self.statements(statement.otherwise, frame, ctx)
            elif isinstance(statement, st.While):
                while True:
                    ctx.tick(statement.loc)
                    if not self.expression(statement.condition, frame, ctx):
                        break
                    try:
                        self.statements(statement.body, frame, ctx)
                    except _Exit:
                        break
            elif isinstance(statement, st.For):
                self._for(statement, frame, ctx)
            elif isinstance(statement, st.Return):
                raise _Return
            elif isinstance(statement, st.Exit):
                raise _Exit
            else:
                raise ExecutionError("Unsupported statement", statement.loc)

    def _for(self, statement: st.For, frame: Frame, ctx: Context) -> None:
        start = self.expression(statement.start, frame, ctx)
        stop = self.expression(statement.stop, frame, ctx)
        step = self.expression(statement.step, frame, ctx)
        if step == 0:
            raise ExecutionError("FOR step must not be zero", statement.loc)
        variable = self.storage(statement.variable, frame, ctx)
        variable._write(start, statement.loc)
        while True:
            ctx.tick(statement.loc)
            if (step > 0 and variable.value > stop) or (step < 0 and variable.value < stop):
                break
            try:
                self.statements(statement.body, frame, ctx)
            except _Exit:
                break
            # Storage checks cover the loop counter, including the final increment.
            variable._write(variable.value + step, statement.loc)
