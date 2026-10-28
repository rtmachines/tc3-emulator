"""Whole-program static validation for the supported ST subset."""

from __future__ import annotations

from dataclasses import replace

from .bitwise import bit_width, bitwise_result_type, bitwise_value, read_bit
from .errors import ValidationError
from .initialization import (
    InstanceSetup,
    initialization_contracts,
    initialization_declarations,
    initialization_edges,
)
from .standard_blocks import STANDARD_BLOCK_NAMES, standard_block_definitions
from .standard_functions import bind_arguments, infer_result, is_standard_function
from .syntax import (
    ArrayBounds,
    ArrayInitializer,
    Assign,
    Binary,
    BitAccess,
    Call,
    CallStatement,
    Case,
    EnumDecl,
    Exit,
    Expr,
    For,
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
from .timers import TIMER_NAMES, timer_definitions
from .types import (
    FLOAT_TYPES,
    INTEGER_TYPES,
    SCALAR_TYPES,
    AliasType,
    ArrayType,
    EnumType,
    EnumValue,
    FBArrayType,
    InterfaceArrayType,
    InterfaceType,
    OpenArrayType,
    ReferenceType,
    Scalar,
    StringType,
    StructField,
    StructType,
    TypeSpec,
    Value,
    array_initial_value,
    canonical_type,
    check_float_literal,
    check_value,
    checked_integer,
    inout_compatible,
    is_value_type,
    numeric_type,
    same_type,
    trunc_div,
    value_leaf_count,
)

_SECTIONS = {"VAR", "VAR_INPUT", "VAR_OUTPUT", "VAR_IN_OUT", "VAR_TEMP", "VAR_INST"}
_MEMBER_KINDS = {"METHOD", "PROPERTY_GET", "PROPERTY_SET"}
_RESULT_KINDS = {"FUNCTION", *_MEMBER_KINDS}
_INTEGER_CATEGORIES = INTEGER_TYPES | {"INTEGER"}
_NUMERIC_CATEGORIES = _INTEGER_CATEGORIES | FLOAT_TYPES
_BUILTIN_BLOCK_NAMES = TIMER_NAMES | STANDARD_BLOCK_NAMES
_BOUND_OPERATORS = {"LOWER_BOUND", "UPPER_BOUND"}
_ACCESS = {"PRIVATE": 0, "PROTECTED": 1, "PUBLIC": 2}


class Registry(dict[str, Pou]):
    """Validated POU mapping with its resolved named value types."""

    def __init__(self) -> None:
        super().__init__()
        self.types: dict[str, TypeSpec] = {}
        self.enum_values: dict[int, EnumValue] = {}
        self.interfaces: dict[str, InterfaceDecl] = {}
        self.interface_ancestors: dict[str, frozenset[str]] = {}
        self.interface_methods: dict[tuple[str, str], str] = {}
        self.prototype_pous: dict[str, Pou] = {}
        self.implementers: dict[str, set[str]] = {}
        self.valid_reference_calls: dict[int, LValue] = {}
        self.reference_initializers: dict[tuple[str, str], tuple[Expr, frozenset[str]]] = {}
        self.interface_comparisons: dict[int, LValue] = {}
        self.global_lists: dict[str, bool] = {}
        self.global_variables: dict[str, tuple[str, ...]] = {}
        self.builtin_calls: dict[int, TypeSpec] = {}
        self.method_calls: dict[int, tuple[LValue | None, str]] = {}
        self.action_calls: dict[int, tuple[LValue | None, str, str]] = {}
        self.effective_actions: dict[tuple[str, str], str] = {}
        self.properties: dict[tuple[str, str], Property] = {}
        self.property_reads: dict[int, tuple[LValue | None, str]] = {}
        self.property_writes: dict[int, tuple[LValue | None, str]] = {}
        self.bound_calls: dict[int, tuple[LValue, Expr, bool]] = {}
        self.bit_accesses: dict[int, tuple[LValue, int]] = {}
        self.bases: dict[str, str | None] = {}
        self.lineages: dict[str, tuple[str, ...]] = {}
        self.effective_methods: dict[tuple[str, str], str] = {}
        self.super_calls: dict[int, str] = {}
        self.static_dispatch: set[int] = set()
        self.initialization_methods: dict[str, tuple[Pou, ...]] = {}
        self.initialization_hooks: dict[str, tuple[Pou, ...]] = {}
        self.instance_initializers: dict[tuple[str, str], tuple[InstanceSetup, ...]] = {}
        self.initialization_scopes: dict[tuple[str, str], tuple[Pou, frozenset[str]]] = {}

    @staticmethod
    def lexical_owner(pou: Pou) -> str | None:
        return pou.name if pou.kind in {"FUNCTION_BLOCK", "PROGRAM"} else pou.owner

    def variables_for(self, pou: Pou) -> tuple[VarDecl, ...]:
        """Keep resolved declarations in their scopes; inherit only persistent fields."""
        if pou.kind != "FUNCTION_BLOCK":
            return pou.variables
        return tuple(
            var
            for owner in self.lineages.get(pou.name, (pou.name,))
            for var in self[owner].variables
            if owner == pou.name or var.section != "VAR_TEMP"
        )

    def instance_methods(self, pou: Pou) -> tuple[Pou, ...]:
        """Include overridden ancestors because SUPER can still execute their banks."""
        return tuple(
            self[method.name]
            for owner in self.lineages.get(pou.name, (pou.name,))
            for method in self.get(owner, pou).methods
        )

    def method_for(self, owner: str, name: str) -> Pou | None:
        qualified = self.effective_methods.get((owner, name), f"{owner}.{name}")
        return self.get(qualified)

    def interface_method_for(self, owner: str, name: str) -> Pou | None:
        qualified = self.interface_methods.get((owner, name))
        return self.prototype_pous.get(qualified)

    def interface_assignable(self, actual: InterfaceType, expected: InterfaceType) -> bool:
        return expected.name in self.interface_ancestors.get(actual.name, frozenset())

    def action_for(self, owner: str, name: str) -> Pou | None:
        qualified = self.effective_actions.get((owner, name), f"{owner}.{name}")
        target = self.get(qualified)
        return target if target is not None and target.kind == "ACTION" else None

    def dispatch(self, owner: str, declaration: Pou, *, static: bool = False) -> Pou:
        """Resolve a checked member against its concrete receiver's effective table."""
        if static or declaration.access == "PRIVATE":
            return declaration
        if declaration.kind == "ACTION":
            target = self.action_for(owner, declaration.result_name)
            assert target is not None
            return target
        if declaration.kind == "METHOD":
            target = self.method_for(owner, declaration.result_name)
            assert target is not None
            return target
        prop = self.properties[owner, declaration.property_name]
        target = prop.setter if declaration.kind == "PROPERTY_SET" else prop.getter
        assert target is not None
        return target


def validate(program: Program) -> Registry:
    """Validate every declaration and body, returning the canonical POU table."""
    return _Validator(program).run()


class _Validator:
    def __init__(self, program: Program) -> None:
        self.program = program
        self.pous = Registry()
        self.type_declarations: dict[str, TypeDecl] = {}
        self.resolving: set[str] = set()
        self.variables: dict[str, dict[str, VarDecl]] = {}
        self.calls: dict[str, set[str]] = {}
        self.contains: dict[str, set[str]] = {}
        self.constant_values: dict[tuple[str, str], tuple[Value, TypeSpec]] = {}
        self.active_constants: set[tuple[str, str]] = set()
        self.preflight_constants = False
        self.property_scopes: dict[str, Pou] = {}

    def run(self) -> Registry:
        globals_as_pous = []
        for gvl in self.program.gvls:
            if gvl.name in self.pous.global_lists:
                self.fail(f"Duplicate global list name {gvl.name}", gvl.loc)
            self.pous.global_lists[gvl.name] = gvl.qualified_only
            globals_as_pous.append(
                Pou(
                    "GVL",
                    gvl.name,
                    None,
                    tuple(replace(var, section="VAR") for var in gvl.variables),
                    (),
                    gvl.loc,
                )
            )
            if not gvl.qualified_only:
                for var in gvl.variables:
                    candidates = self.pous.global_variables.get(var.name, ())
                    self.pous.global_variables[var.name] = (*candidates, gvl.name)
        self.program = replace(self.program, pous=(*self.program.pous, *globals_as_pous))
        for declaration in self.program.types:
            name = declaration.name
            if (
                name in self.type_declarations
                or name in SCALAR_TYPES | {"STRING"}
                or name in _BUILTIN_BLOCK_NAMES
                or is_standard_function(name)
                or name in _BOUND_OPERATORS
            ):
                self.fail(f"Duplicate or reserved type name {name}", declaration.loc)
            self.type_declarations[name] = declaration
        for interface in self.program.interfaces:
            name = interface.name
            if (
                name in self.pous.interfaces
                or name in self.type_declarations
                or name in SCALAR_TYPES | {"STRING"} | _BUILTIN_BLOCK_NAMES | _BOUND_OPERATORS
                or is_standard_function(name)
            ):
                self.fail(f"Duplicate or reserved interface name {name}", interface.loc)
            self.pous.interfaces[name] = interface
            self.pous.implementers[name] = set()
        for pou in self.program.pous:
            if pou.kind in {*_MEMBER_KINDS, "ACTION"}:
                self.fail("METHOD/accessor must be declared inside a FUNCTION_BLOCK", pou.loc)
            if (
                pou.name in self.pous
                or pou.name in SCALAR_TYPES | {"STRING"}
                or pou.name in _BUILTIN_BLOCK_NAMES
                or is_standard_function(pou.name)
                or pou.name in _BOUND_OPERATORS
                or pou.name in self.type_declarations
                or pou.name in self.pous.interfaces
            ):
                self.fail(f"Duplicate or reserved POU name {pou.name}", pou.loc)
            self.pous[pou.name] = pou
            if pou.extends is not None and pou.kind != "FUNCTION_BLOCK":
                self.fail("EXTENDS requires FUNCTION_BLOCK", pou.loc)
            if pou.implements and pou.kind != "FUNCTION_BLOCK":
                self.fail("IMPLEMENTS requires FUNCTION_BLOCK", pou.loc)
            if len(set(pou.implements)) != len(pou.implements):
                self.fail("Duplicate IMPLEMENTS interface", pou.loc)
            for name in pou.implements:
                if name not in self.pous.interfaces:
                    self.fail(f"Unknown interface {name}", pou.loc)
                self.pous.implementers[name].add(pou.name)
        self.inheritance_graph()
        self.interface_inheritance()
        methods = []
        for owner in self.program.pous:
            if (owner.methods or owner.properties) and owner.kind != "FUNCTION_BLOCK":
                self.fail("Only FUNCTION_BLOCK can declare methods", owner.loc)
            names = {var.name for var in owner.variables} | {owner.name}
            for method in owner.methods:
                name = method.result_name
                if name in names or name in {"FB_REINIT", "FB_EXIT"}:
                    self.fail(f"Duplicate or reserved method name {name}", method.loc)
                if (
                    method.kind != "METHOD"
                    or method.owner != owner.name
                    or method.name != f"{owner.name}.{name}"
                    or method.access not in {"PUBLIC", "PRIVATE", "PROTECTED"}
                    or method.extends is not None
                    or method.methods
                    or method.properties
                    or method.actions
                ):
                    self.fail("Invalid method declaration or owner", method.loc)
                names.add(name)
                self.pous[method.name] = method
                methods.append(method)
            for prop in owner.properties:
                if prop.name in names or prop.name in {"FB_INIT", "FB_REINIT", "FB_EXIT"}:
                    self.fail(f"Duplicate or reserved property name {prop.name}", prop.loc)
                names.add(prop.name)
                if prop.access not in {"PUBLIC", "PRIVATE", "PROTECTED"} or not (
                    prop.getter or prop.setter
                ):
                    self.fail("Invalid property access or missing accessor", prop.loc)
                declaration_scope = Pou(
                    "PROPERTY_DECL",
                    f"{owner.name}.{prop.name}",
                    None,
                    prop.variables,
                    (),
                    prop.loc,
                    owner=owner.name,
                )
                for kind, accessor in (("GET", prop.getter), ("SET", prop.setter)):
                    if accessor is None:
                        continue
                    if (
                        accessor.kind != f"PROPERTY_{kind}"
                        or accessor.name != f"{owner.name}.{prop.name}.{kind}"
                        or accessor.owner != owner.name
                        or accessor.property_name != prop.name
                        or accessor.access not in {"PUBLIC", "PRIVATE", "PROTECTED"}
                        or _ACCESS.get(accessor.access, 3) > _ACCESS[prop.access]
                        or accessor.extends is not None
                        or accessor.methods
                        or accessor.properties
                        or accessor.actions
                    ):
                        self.fail("Invalid property accessor declaration", accessor.loc)
                    self.pous[accessor.name] = accessor
                    self.property_scopes[accessor.name] = declaration_scope
                    methods.append(accessor)
                self.pous.properties[owner.name, prop.name] = prop
            if owner.actions and owner.kind not in {"FUNCTION_BLOCK", "PROGRAM"}:
                self.fail("Actions require FUNCTION_BLOCK or PROGRAM", owner.loc)
            for action in owner.actions:
                name = action.result_name
                if name in names or name in {"FB_INIT", "FB_REINIT", "FB_EXIT"}:
                    self.fail(f"Duplicate or reserved action name {name}", action.loc)
                if (
                    action.kind != "ACTION"
                    or action.owner != owner.name
                    or action.name != f"{owner.name}.{name}"
                    or action.variables
                    or action.return_type is not None
                    or action.methods
                    or action.properties
                    or action.actions
                    or action.extends is not None
                    or action.implements
                    or action.access != "PUBLIC"
                    or action.property_name is not None
                    or action.call_after_init
                ):
                    self.fail("Invalid action declaration or owner", action.loc)
                names.add(name)
                self.pous[action.name] = action
                methods.append(action)
        self.program = replace(self.program, pous=(*self.program.pous, *methods))
        self.inherited_members()
        self.resolve_bounds()
        self.check_type_graph()
        for name in self.type_declarations:
            self.resolve_named(name)
        for pou in (*timer_definitions(), *standard_block_definitions()):
            self.pous[pou.name] = pou
        for pou in self.pous.values():
            self.calls[pou.name] = set()
            self.contains[pou.name] = set()
        for pou in tuple(self.pous.values()):
            self.declarations(pou)
        for key, prop in tuple(self.pous.properties.items()):
            getter = self.pous[prop.getter.name] if prop.getter else None
            setter = self.pous[prop.setter.name] if prop.setter else None
            kind = (getter or setter).return_type
            if isinstance(canonical_type(kind), (ArrayType, StructType, OpenArrayType)):
                self.fail("Property type must be scalar, enum, TIME or STRING", prop.loc)
            self.pous.properties[key] = replace(prop, type_name=kind, getter=getter, setter=setter)
        self.inherited_members(resolved=True)
        self.interface_contracts()
        initialization_contracts(self)
        self.reject_cycles(self.contains, "FB containment")
        for pou in self.pous.values():
            try:
                self.reference_initializers(pou)
                initialization_declarations(self, pou)
                self.statements(pou.body, pou, 0)
            except RecursionError as error:
                raise ValidationError("Validation nesting limit exceeded", pou.loc) from error
        initialization_edges(self)
        self.reject_cycles(self.calls, "Recursive call")
        return self.pous

    def inheritance_graph(self) -> None:
        """Resolve forward bases without recursively walking an unchecked graph."""
        for pou in self.program.pous:
            if pou.kind != "FUNCTION_BLOCK":
                continue
            base = self.pous.get(pou.extends) if pou.extends is not None else None
            if pou.extends is not None and (base is None or base.kind != "FUNCTION_BLOCK"):
                self.fail(f"Invalid EXTENDS base {pou.extends}", pou.loc)
            self.pous.bases[pou.name] = pou.extends
        for name in self.pous.bases:
            chain = []
            current = name
            while current is not None:
                if current in chain:
                    self.fail(f"Cyclic inheritance involving {current}", self.pous[name].loc)
                chain.append(current)
                current = self.pous.bases[current]
            self.pous.lineages[name] = tuple(reversed(chain))
            for owner in chain:
                for interface in self.pous[owner].implements:
                    self.pous.implementers[interface].add(name)

    def interface_inheritance(self) -> None:
        """Validate all interface bases, then close ancestry in iterative postorder."""
        interfaces = self.pous.interfaces
        for interface in interfaces.values():
            if len(set(interface.extends)) != len(interface.extends):
                self.fail("Duplicate interface EXTENDS base", interface.loc)
            for base in interface.extends:
                if base not in interfaces:
                    self.fail(f"Invalid interface EXTENDS base {base}", interface.loc)
        ancestors = self.pous.interface_ancestors
        for name in interfaces:
            if name in ancestors:
                continue
            active = {name}
            stack = [(name, iter(interfaces[name].extends))]
            while stack:
                current, bases = stack[-1]
                base = next(bases, None)
                if base is None:
                    closure = {current}
                    for parent in interfaces[current].extends:
                        closure.update(ancestors[parent])
                    ancestors[current] = frozenset(closure)
                    active.remove(current)
                    stack.pop()
                elif base in active:
                    self.fail(
                        f"Cyclic interface inheritance involving {base}", interfaces[current].loc
                    )
                elif base not in ancestors:
                    active.add(base)
                    stack.append((base, iter(interfaces[base].extends)))
        for name, closure in ancestors.items():
            for base in closure:
                self.pous.implementers[base].update(self.pous.implementers[name])

    def inherited_members(self, *, resolved: bool = False) -> None:
        """Build effective member tables without changing any declaration's owner."""
        for name, lineage in self.pous.lineages.items():
            inherited: dict[str, tuple[str, object]] = {}
            for owner in lineage:
                pou = self.pous[owner]
                declarations = [(var.name, "variable", var) for var in pou.variables]
                declarations += [
                    (method.result_name, "method", self.pous[method.name]) for method in pou.methods
                ]
                declarations += [
                    (prop.name, "property", self.pous.properties[owner, prop.name])
                    for prop in pou.properties
                ]
                declarations += [
                    (action.result_name, "action", self.pous[action.name]) for action in pou.actions
                ]
                for member_name, kind, declaration in declarations:
                    previous = inherited.get(member_name)
                    if previous is not None:
                        old_kind, old = previous
                        if old_kind != kind or kind == "variable":
                            self.fail(
                                f"Inherited member collision for {member_name}", declaration.loc
                            )
                        if old.access == "PRIVATE":
                            self.fail(
                                f"Cannot override PRIVATE member {member_name}", declaration.loc
                            )
                        if resolved and kind != "action":
                            self.check_override(old, declaration, kind)
                    inherited[member_name] = kind, declaration
            for member_name, (kind, declaration) in inherited.items():
                if kind == "method":
                    self.pous.effective_methods[name, member_name] = declaration.name
                elif kind == "property":
                    self.pous.properties[name, member_name] = declaration
                elif kind == "action":
                    self.pous.effective_actions[name, member_name] = declaration.name

    def check_override(self, base, derived, kind: str) -> None:
        matches = base.access == derived.access
        if kind == "method":
            matches = matches and same_type(base.return_type, derived.return_type)

            def parameters(member):
                return tuple(
                    var
                    for var in member.variables
                    if var.section in {"VAR_INPUT", "VAR_OUTPUT", "VAR_IN_OUT"}
                )

            wanted, actual = parameters(base), parameters(derived)
            matches = matches and (
                len(wanted) <= len(actual)
                if derived.result_name == "FB_INIT"
                else len(wanted) == len(actual)
            )
            matches = matches and (not base.call_after_init or derived.call_after_init)
            matches = matches and all(
                a.name == b.name
                and a.section == b.section
                and same_type(a.type_name, b.type_name)
                and (
                    (a.initial is None) == (b.initial is None) and a.default == b.default
                    if a.section == "VAR_INPUT"
                    else True
                )
                for a, b in zip(wanted, actual)
            )
        else:
            matches = matches and same_type(base.type_name, derived.type_name)
            for accessor in ("getter", "setter"):
                a, b = getattr(base, accessor), getattr(derived, accessor)
                matches = matches and ((a is None) == (b is None))
                if a is not None and b is not None:
                    matches = matches and a.access == b.access
        if not matches:
            self.fail(f"Override contract mismatch for {derived.name}", derived.loc)

    def fb_variable(self, owner: str, name: str) -> tuple[Pou, VarDecl] | None:
        """Return the declaring scope, not the dynamic receiver's namespace."""
        for ancestor in reversed(self.pous.lineages.get(owner, (owner,))):
            var = self.variables.get(ancestor, {}).get(name)
            if var is not None and (ancestor == owner or var.section != "VAR_TEMP"):
                return self.pous[ancestor], var
        return None

    def member_access(self, target: Pou, caller: Pou, loc: Location) -> None:
        owner = self.pous.lexical_owner(caller)
        permitted = target.access == "PUBLIC" or owner == target.owner
        if target.access == "PROTECTED":
            permitted = target.owner in self.pous.lineages.get(owner, ())
        if not permitted:
            self.fail(f"{target.access.title()} member {target.name} is inaccessible", loc)

    @staticmethod
    def literal_zero(expr: Expr) -> bool:
        return (
            isinstance(expr, Literal)
            and type(expr.value) is int
            and expr.value == 0
            and expr.type_name in (None, *INTEGER_TYPES)
        )

    def interface_variable(self, var: VarDecl) -> VarDecl:
        kind = var.type_name
        name = kind.name if isinstance(kind, InterfaceType) else kind
        if name not in self.pous.interfaces:
            self.fail(f"Unknown interface {name}", var.loc)
        if var.constant or var.section not in {"VAR", "VAR_INPUT", "VAR_TEMP", "VAR_INST"}:
            self.fail(
                "Interface storage requires nonconstant VAR, VAR_INPUT, VAR_TEMP or VAR_INST",
                var.loc,
            )
        if var.initial is not None and not self.literal_zero(var.initial):
            self.fail("Interface initializer must be literal integer 0", var.loc)
        return replace(var, type_name=InterfaceType(name), default=None)

    def interface_array_variable(self, var: VarDecl) -> VarDecl:
        kind = var.type_name
        if kind.element_type.name not in self.pous.interfaces:
            self.fail(f"Unknown interface {kind.element_type}", var.loc)
        if var.constant or var.section not in {"VAR", "VAR_TEMP", "VAR_INST"}:
            self.fail("Interface arrays require nonconstant owned local or global storage", var.loc)
        if var.initial is not None:
            self.fail("Interface arrays cannot have an initializer", var.loc)
        self.initialization_arguments(var)
        return replace(var, default=None)

    def reference_variable(self, var: VarDecl) -> VarDecl:
        if var.constant or var.section not in {"VAR", "VAR_INPUT", "VAR_TEMP", "VAR_INST"}:
            self.fail(
                "Reference storage requires nonconstant VAR, VAR_INPUT, VAR_TEMP or VAR_INST",
                var.loc,
            )
        target = self.resolve_spec(var.type_name.target, var.loc)
        if not is_value_type(target):
            self.fail("Reference target must be a value type", var.loc)
        return replace(var, type_name=ReferenceType(target), default=None)

    def reference_source(self, expr: Expr, expected: ReferenceType, pou: Pou) -> None:
        if self.literal_zero(expr):
            return
        if not isinstance(expr, (Reference, Index, Member, BitAccess)):
            self.fail("Reference binding requires writable storage or literal integer 0", expr.loc)
        actual = self.raw_reference(expr, pou, writable=True)
        if id(expr) in self.pous.bit_accesses:
            self.fail("Bit locations cannot bind references", expr.loc)
        if isinstance(actual, ReferenceType):
            actual = actual.target
        if not same_type(expected.target, actual):
            self.fail(f"Reference requires exact type {expected.target}, got {actual}", expr.loc)

    def reference_initializers(self, pou: Pou) -> None:
        for var in pou.variables:
            if not isinstance(var.type_name, ReferenceType) or var.initial is None:
                continue
            scope = self.declaration_scope(pou, var)
            original_variables = self.variables[scope.name]
            if var.section == "VAR_INST":
                # Address targets may include this method's persistent bank; declaration
                # constants keep the owner's scope, as with ordinary VAR_INST defaults.
                variables = {
                    name: item
                    for name, item in original_variables.items()
                    if item.section == "VAR_INST"
                }
                index_scope = self.pous[pou.owner]
            else:
                # Header declarations were copied into each accessor. Preserve their
                # visible names, using the accessor's already resolved value types.
                variables = {name: self.variables[pou.name][name] for name in original_variables}
                index_scope = scope
            self.variables[scope.name] = variables
            try:
                initial = self.prepare_reference_initializer(var, scope, index_scope)
            finally:
                self.variables[scope.name] = original_variables
            visible = set(variables)
            if scope.kind in _RESULT_KINDS and scope.return_type is not None:
                visible.add(scope.result_name)
            self.pous.reference_initializers[pou.name, var.name] = initial, frozenset(visible)

    def prepare_reference_initializer(self, var: VarDecl, pou: Pou, index_scope: Pou) -> Expr:
        """Check the storage scope and retain selector constants without a second lookup."""

        def freeze_indices(expr):
            if isinstance(expr, Index):
                indices = []
                for index in expr.indices:
                    value, kind = self.constant_expression(index, index_scope)
                    self.require(kind, "INTEGER", index.loc)
                    indices.append(Literal(value, index.loc))
                return replace(expr, base=freeze_indices(expr.base), indices=tuple(indices))
            if isinstance(expr, Member):
                return replace(expr, base=freeze_indices(expr.base))
            return expr

        initial = freeze_indices(var.initial)
        self.reference_source(initial, var.type_name, pou)
        if self.literal_zero(initial):
            return initial
        if var.section == "VAR_INPUT" and pou.kind in {"FUNCTION", "METHOD"}:
            self.fail("Reference input default must be literal integer 0", var.loc)
        persistent = var.section == "VAR_INST" or (
            pou.kind in {"GVL", "PROGRAM", "FUNCTION_BLOCK"} and var.section != "VAR_TEMP"
        )

        def inspect(expr):
            if isinstance(self.raw_reference(expr, pou), ReferenceType):
                self.fail("Reference initializer cannot pass through another reference", expr.loc)
            if isinstance(expr, Index):
                inspect(expr.base)
            elif isinstance(expr, Member):
                if isinstance(expr.base, (This, Super)):
                    owner = self.reference(expr.base, pou)
                    binding = self.fb_variable(owner, expr.name)
                    check(binding[0], binding[1], expr.loc)
                else:
                    inspect(expr.base)
            elif isinstance(expr, Reference):
                binding = self.variable_binding(expr, pou)
                if binding is not None:
                    check(binding[0], binding[1], expr.loc)
                elif persistent and expr.parts[0] == pou.result_name and pou.kind in _RESULT_KINDS:
                    self.fail(
                        "Persistent reference initializer cannot target invocation storage",
                        expr.loc,
                    )
                if len(expr.parts) > 1:
                    inspect(Reference(expr.parts[:-1], expr.loc))

        def check(owner, target, loc):
            if not persistent:
                return
            if target.section in {"VAR_TEMP", "VAR_IN_OUT"} or (
                owner.kind in _RESULT_KINDS and target.section != "VAR_INST"
            ):
                self.fail("Persistent reference initializer cannot target invocation storage", loc)

        inspect(initial)
        return initial

    def interface_source(self, expr: Expr, expected: InterfaceType, pou: Pou) -> None:
        if self.literal_zero(expr):
            return
        if not isinstance(expr, (Reference, Index, Member, This)):
            self.fail(
                "Interface binding requires a function-block or same-interface reference, or literal 0",
                expr.loc,
            )
        actual = self.reference(expr, pou)
        if isinstance(actual, InterfaceType) and self.pous.interface_assignable(actual, expected):
            return
        if isinstance(actual, str) and actual in self.pous.implementers[expected.name]:
            return
        self.fail(f"Incompatible interface binding: expected {expected}, got {actual}", expr.loc)

    def call_edge(self, caller: Pou, target: Pou, *, static: bool = False) -> None:
        if target.name in self.pous.prototype_pous:
            self.calls[caller.name].update(
                self.pous.dispatch(owner, target).name
                for owner in self.pous.implementers[target.owner]
            )
        elif (
            target.owner
            and target.kind in {*_MEMBER_KINDS, "ACTION"}
            and target.access != "PRIVATE"
            and not static
            and self.pous[target.owner].kind == "FUNCTION_BLOCK"
        ):
            self.calls[caller.name].update(
                self.pous.dispatch(owner, target).name
                for owner, lineage in self.pous.lineages.items()
                if target.owner in lineage
            )
        else:
            self.calls[caller.name].add(target.name)

    def interface_contracts(self) -> None:
        """Resolve declaration-only signatures in their own lexical scopes."""

        def prepare(spec, scope, loc):
            if isinstance(spec, StringBounds):
                spec = self.resolve_string_bounds(spec, scope)
            elif isinstance(spec, ArrayBounds):
                spec = self.resolve_array_bounds(spec, scope)
            if isinstance(spec, (OpenArrayBounds, OpenArrayType)):
                return OpenArrayType(spec.rank, prepare(spec.element_type, scope, loc))
            return self.resolve_spec(spec, loc)

        def prototype(raw, interface, *, property_name=None):
            kind = "METHOD" if property_name is None else raw.kind
            suffix = (
                raw.result_name
                if property_name is None
                else f"{property_name}.{kind.removeprefix('PROPERTY_')}"
            )
            if (
                raw.access != "PUBLIC"
                or raw.body
                or raw.methods
                or raw.properties
                or raw.owner != interface.name
                or raw.name != f"{interface.name}.{suffix}"
                or raw.kind != kind
                or raw.implements
                or raw.extends is not None
            ):
                self.fail("Interface prototypes must be PUBLIC, declaration-only members", raw.loc)
            scope = replace(raw, kind="INTERFACE_DECL", owner=None)
            self.variables[scope.name] = {var.name: var for var in raw.variables}
            result_type = (
                prepare(raw.return_type, scope, raw.loc) if raw.return_type is not None else None
            )
            if isinstance(result_type, OpenArrayType):
                self.fail("Method return type cannot be an open array", raw.loc)
            variables = []
            names = set()
            for var in raw.variables:
                self.initialization_arguments(var)
                if (
                    var.constant
                    or var.section not in {"VAR_INPUT", "VAR_OUTPUT", "VAR_IN_OUT"}
                    or property_name is not None
                ):
                    self.fail(
                        "Interface prototypes cannot declare local or instance storage", var.loc
                    )
                if var.name in names or var.name == raw.result_name:
                    self.fail(f"Duplicate variable or result name {var.name}", var.loc)
                names.add(var.name)
                if var.initial is not None and var.section != "VAR_INPUT":
                    self.fail("Only interface VAR_INPUT may have a default", var.loc)
                if isinstance(var.type_name, (ReferenceSpec, ReferenceType)):
                    if var.initial is not None and not self.literal_zero(var.initial):
                        self.fail("Reference input default must be literal integer 0", var.loc)
                    target = var.type_name.target
                    if isinstance(target, StringBounds):
                        target = self.resolve_string_bounds(target, scope)
                    elif isinstance(target, ArrayBounds):
                        target = self.resolve_array_bounds(target, scope)
                    var = self.reference_variable(replace(var, type_name=ReferenceType(target)))
                elif isinstance(var.type_name, InterfaceType) or (
                    isinstance(var.type_name, str) and var.type_name in self.pous.interfaces
                ):
                    if var.section != "VAR_INPUT":
                        self.fail("Interface parameters require VAR_INPUT", var.loc)
                    var = self.interface_variable(var)
                else:
                    resolved = prepare(var.type_name, scope, var.loc)
                    if isinstance(resolved, OpenArrayType) and var.section != "VAR_IN_OUT":
                        self.fail("Open arrays require VAR_IN_OUT", var.loc)
                    var = replace(var, type_name=resolved)
                    if var.initial is not None:
                        var = replace(var, default=self.initializer(var.initial, resolved, scope))
                variables.append(var)
            result = replace(raw, return_type=result_type, variables=tuple(variables))
            self.pous.prototype_pous[result.name] = result
            return result

        for name, interface in tuple(self.pous.interfaces.items()):
            names = set()
            methods, properties = [], []
            for raw in interface.methods:
                if raw.kind != "METHOD":
                    self.fail("Invalid interface method prototype", raw.loc)
                if raw.result_name in names or raw.result_name in {
                    name,
                    "FB_INIT",
                    "FB_REINIT",
                    "FB_EXIT",
                }:
                    self.fail("Duplicate or reserved interface member", raw.loc)
                names.add(raw.result_name)
                methods.append(prototype(raw, interface))
            for prop in interface.properties:
                if prop.name in names or prop.name in {name, "FB_INIT", "FB_REINIT", "FB_EXIT"}:
                    self.fail("Duplicate or reserved interface member", prop.loc)
                names.add(prop.name)
                if prop.access != "PUBLIC" or prop.variables or not (prop.getter or prop.setter):
                    self.fail("Invalid interface property prototype", prop.loc)
                getter = (
                    prototype(prop.getter, interface, property_name=prop.name)
                    if prop.getter
                    else None
                )
                setter = (
                    prototype(prop.setter, interface, property_name=prop.name)
                    if prop.setter
                    else None
                )
                for accessor, expected in ((getter, "PROPERTY_GET"), (setter, "PROPERTY_SET")):
                    if accessor is not None and (
                        accessor.kind != expected or accessor.property_name != prop.name
                    ):
                        self.fail("Invalid interface property accessor", accessor.loc)
                kind = (getter or setter).return_type
                if kind is None or isinstance(
                    canonical_type(kind), (ArrayType, StructType, OpenArrayType)
                ):
                    self.fail(
                        "Interface property type must be scalar, enum, TIME or STRING", prop.loc
                    )
                if setter and getter and not same_type(setter.return_type, getter.return_type):
                    self.fail("Interface accessor types differ", prop.loc)
                resolved = replace(prop, type_name=kind, getter=getter, setter=setter)
                properties.append(resolved)
                self.pous.properties[name, prop.name] = resolved
            self.pous.interfaces[name] = replace(
                interface, methods=tuple(methods), properties=tuple(properties)
            )

        effective: dict[str, dict[str, Pou | Property]] = {}
        for name in self.pous.interface_ancestors:
            interface = self.pous.interfaces[name]
            members: dict[str, Pou | Property] = {}

            def merge(member: Pou | Property) -> None:
                member_name = member.result_name if isinstance(member, Pou) else member.name
                previous = members.get(member_name)
                if previous is not None:
                    matches = (
                        self.same_interface_method_signature(previous, member)
                        if isinstance(previous, Pou) and isinstance(member, Pou)
                        else self.same_interface_property_signature(previous, member)
                        if isinstance(previous, Property) and isinstance(member, Property)
                        else False
                    )
                    if not matches:
                        self.fail(
                            f"Conflicting inherited interface member {name}.{member_name}",
                            interface.loc,
                        )
                else:
                    members[member_name] = member

            for base in interface.extends:
                for member in effective[base].values():
                    merge(member)
            for member in (*interface.methods, *interface.properties):
                merge(member)
            effective[name] = members
            for member_name, member in members.items():
                if isinstance(member, Pou):
                    self.pous.interface_methods[name, member_name] = member.name
                else:
                    self.pous.properties[name, member_name] = member

        for name, members in effective.items():
            for owner in sorted(self.pous.implementers[name]):
                for required in (m for m in members.values() if isinstance(m, Pou)):
                    actual = self.pous.method_for(owner, required.result_name)
                    if actual is None or actual.kind != "METHOD" or actual.access != "PUBLIC":
                        self.fail(
                            f"{owner} must implement PUBLIC method {required.name}",
                            self.pous[owner].loc,
                        )
                    if not same_type(actual.return_type, required.return_type):
                        self.fail(
                            f"Interface method {required.name} return type mismatch", actual.loc
                        )
                    parameters = tuple(
                        var
                        for var in actual.variables
                        if var.section in {"VAR_INPUT", "VAR_OUTPUT", "VAR_IN_OUT"}
                    )
                    if len(parameters) != len(required.variables):
                        self.fail(
                            f"Interface method {required.name} parameter mismatch", actual.loc
                        )
                    for wanted, given in zip(required.variables, parameters):
                        if (
                            wanted.name != given.name
                            or wanted.section != given.section
                            or not same_type(wanted.type_name, given.type_name)
                            or wanted.section == "VAR_INPUT"
                            and (
                                (wanted.initial is None) != (given.initial is None)
                                or wanted.default != given.default
                            )
                        ):
                            self.fail(
                                f"Interface method {required.name} parameter/default mismatch",
                                given.loc,
                            )
                for required in (m for m in members.values() if isinstance(m, Property)):
                    actual = self.pous.properties.get((owner, required.name))
                    if (
                        actual is None
                        or actual.access != "PUBLIC"
                        or not same_type(actual.type_name, required.type_name)
                    ):
                        self.fail(
                            f"Interface property {name}.{required.name} type/access mismatch",
                            self.pous[owner].loc,
                        )
                    for kind in ("getter", "setter"):
                        if getattr(required, kind) is not None:
                            accessor = getattr(actual, kind)
                            if accessor is None or accessor.access != "PUBLIC":
                                self.fail(
                                    f"Interface property {name}.{required.name} requires PUBLIC {kind}",
                                    actual.loc,
                                )

    @staticmethod
    def same_interface_method_signature(left: Pou, right: Pou) -> bool:
        return (
            left.result_name == right.result_name
            and same_type(left.return_type, right.return_type)
            and len(left.variables) == len(right.variables)
            and all(
                a.name == b.name
                and a.section == b.section
                and same_type(a.type_name, b.type_name)
                and (
                    a.section != "VAR_INPUT"
                    or (a.initial is None) == (b.initial is None)
                    and a.default == b.default
                )
                for a, b in zip(left.variables, right.variables)
            )
        )

    @staticmethod
    def same_interface_property_signature(left: Property, right: Property) -> bool:
        return (
            left.name == right.name
            and same_type(left.type_name, right.type_name)
            and (left.getter is None) == (right.getter is None)
            and (left.setter is None) == (right.setter is None)
        )

    @staticmethod
    def fail(message: str, loc: Location) -> None:
        raise ValidationError(message, loc)

    def declaration_scope(self, pou: Pou, var: VarDecl | None = None) -> Pou:
        """Property headers keep their lexical scope after copying into GET/SET."""
        scope = self.property_scopes.get(pou.name)
        if scope is not None and (var is None or var.name in self.variables[scope.name]):
            return scope
        return pou

    def resolve_bounds(self) -> None:
        """Resolve bounds without creating composite values, then preflight their sizes."""
        self.preflight_constants = True
        for scope in self.property_scopes.values():
            self.variables[scope.name] = {var.name: var for var in scope.variables}
        for pou in self.program.pous:
            variables = {}
            for var in pou.variables:
                if var.name in variables or (
                    var.name == pou.result_name and pou.kind in _RESULT_KINDS
                ):
                    self.fail(f"Duplicate variable or result name {var.name}", var.loc)
                if var.constant and (var.section != "VAR" or var.initial is None):
                    self.fail("Local VAR CONSTANT requires an initializer", var.loc)
                variables[var.name] = var
            self.variables[pou.name] = variables
        self.check_constant_dependencies()

        def prepare(spec, pou=None):
            if isinstance(spec, (ReferenceSpec, ReferenceType)):
                return ReferenceType(prepare(spec.target, pou))
            if isinstance(spec, StringBounds):
                return self.resolve_string_bounds(spec, pou)
            if isinstance(spec, (OpenArrayBounds, OpenArrayType)):
                return OpenArrayType(spec.rank, prepare(spec.element_type, pou))
            if isinstance(spec, ArrayBounds):
                return self.resolve_array_bounds(spec, pou)
            if isinstance(spec, ArrayType):
                return ArrayType(spec.bounds, prepare(spec.element_type, pou))
            if isinstance(spec, StructDecl):
                return replace(
                    spec,
                    fields=tuple(
                        replace(field, type_name=prepare(field.type_name)) for field in spec.fields
                    ),
                )
            return spec

        def prepare_variable(var, pou):
            scope = (
                self.pous[pou.owner]
                if var.section == "VAR_INST" and pou.owner
                else self.declaration_scope(pou, var)
            )
            kind = prepare(var.type_name, scope)
            if isinstance(kind, ArrayType) and self.is_fb_type(kind.element_type):
                kind = FBArrayType(kind.bounds, kind.element_type)
            if (
                isinstance(kind, ArrayType)
                and isinstance(kind.element_type, str)
                and kind.element_type in self.pous.interfaces
            ):
                kind = InterfaceArrayType(kind.bounds, InterfaceType(kind.element_type))
            if isinstance(kind, InterfaceArrayType):
                return self.interface_array_variable(replace(var, type_name=kind))
            if isinstance(kind, FBArrayType):
                if var.constant:
                    self.fail("FB arrays cannot be constant", var.loc)
                if var.section not in {"VAR", "VAR_TEMP", "VAR_INST"}:
                    self.fail("FB arrays require owned local or global storage", var.loc)
            if isinstance(kind, OpenArrayType):
                if pou.kind not in {"FUNCTION", "FUNCTION_BLOCK", "METHOD"} or (
                    var.section != "VAR_IN_OUT"
                ):
                    self.fail("Open arrays require direct VAR_IN_OUT parameters", var.loc)
                if var.initial is not None or var.constant:
                    self.fail("Open arrays cannot have an initializer or be constant", var.loc)
            return replace(var, type_name=kind)

        try:
            types = tuple(
                replace(decl, definition=prepare(decl.definition)) for decl in self.program.types
            )
            scopes = {item.name: item for item in self.property_scopes.values()}
            property_types = {
                scope.name: prepare(
                    self.pous.properties[scope.owner, scope.result_name].type_name, scope
                )
                for scope in scopes.values()
            }
            prepared_scopes = {
                name: replace(
                    scope, variables=tuple(prepare_variable(var, scope) for var in scope.variables)
                )
                for name, scope in scopes.items()
            }
            pous = tuple(
                replace(
                    pou,
                    return_type=(
                        property_types[self.property_scopes[pou.name].name]
                        if pou.name in self.property_scopes
                        else prepare(pou.return_type, pou)
                    ),
                    variables=tuple(prepare_variable(var, pou) for var in pou.variables),
                )
                for pou in self.program.pous
            )
        except RecursionError as error:
            raise ValidationError("Constant resolution nesting limit exceeded") from error
        self.program = replace(self.program, pous=pous, types=types)
        self.type_declarations = {decl.name: decl for decl in types}
        self.pous.update(
            (pou.name, self.pous[pou.name] if self.pous[pou.name] == pou else pou) for pou in pous
        )
        self.property_scopes = {
            name: prepared_scopes[scope.name] for name, scope in self.property_scopes.items()
        }
        self.variables = {
            pou.name: {var.name: var for var in pou.variables}
            for pou in (*pous, *prepared_scopes.values())
        }
        self.constant_values.clear()
        self.active_constants.clear()
        self.preflight_constants = False

    def variable_binding(
        self, ref: Reference, pou: Pou | None
    ) -> tuple[Pou, VarDecl, tuple[str, ...]] | None:
        """Resolve the storage root, applying the same namespace order as execution."""
        if not ref.parts:
            return None
        name, *fields = ref.parts
        if pou is not None and pou.kind != "GVL":
            var = self.variables[pou.name].get(name)
            if var is not None:
                scope = self.declaration_scope(pou, var)
                return scope, var, tuple(fields)
            if pou.kind == "FUNCTION_BLOCK":
                inherited = self.fb_variable(pou.name, name)
                if inherited is not None:
                    owner, var = inherited
                    return owner, var, tuple(fields)
            if name == pou.result_name and pou.kind in _RESULT_KINDS:
                return None
            if pou.kind in {*_MEMBER_KINDS, "PROPERTY_DECL", "ACTION"}:
                inherited = self.fb_variable(pou.owner, name)
                if inherited is not None:
                    owner, var = inherited
                    if pou.kind != "ACTION" and var.section in {"VAR_TEMP", "VAR_IN_OUT"}:
                        self.fail(
                            f"Owner {var.section} {name} is inaccessible from methods", ref.loc
                        )
                    return owner, var, tuple(fields)
        namespace = self.pous.get(name)
        if namespace is not None and namespace.kind in {"GVL", "PROGRAM"}:
            if not fields:
                return None
            var = self.variables[namespace.name].get(fields[0])
            if var is None:
                self.fail(f"Unknown field {fields[0]} on {name}", ref.loc)
            if namespace.kind == "PROGRAM" and var.section == "VAR_TEMP":
                self.fail(f"PROGRAM VAR_TEMP {var.name} is private", ref.loc)
            return namespace, var, tuple(fields[1:])
        candidates = self.pous.global_variables.get(name, ())
        if len(candidates) > 1:
            self.fail(f"Ambiguous global reference {name}", ref.loc)
        if candidates:
            owner = self.pous[candidates[0]]
            return owner, self.variables[owner.name][name], tuple(fields)
        return None

    def check_constant_dependencies(self, pou: Pou | None = None) -> None:
        """Reject cross-scope dependency errors before allocating aggregate defaults."""
        scopes = {
            item.name: item
            for item in ((pou,) if pou else (*self.program.pous, *self.property_scopes.values()))
        }
        edges = {
            (item.name, var.name): set()
            for item in scopes.values()
            for var in item.variables
            if var.constant and self.declaration_scope(item, var).name == item.name
        }

        def shape(spec):
            active = set()
            while isinstance(spec, (str, AliasType)):
                if isinstance(spec, AliasType):
                    spec = spec.target
                elif spec in self.type_declarations and spec not in active:
                    active.add(spec)
                    spec = self.type_declarations[spec].definition
                else:
                    break
            return spec

        def member(spec, name, loc, dependencies, pou):
            spec = shape(spec)
            if isinstance(spec, str) and spec in INTEGER_TYPES:
                inspect(Reference((name,), loc), dependencies, pou)
                return "BOOL"
            if isinstance(spec, (StructDecl, StructType)):
                return next((field.type_name for field in spec.fields if field.name == name), None)
            return None

        def location(initial, dependencies, pou):
            if isinstance(initial, Member) and isinstance(initial.base, (This, Super)):
                owner = self.constant_owner(pou, initial.loc, base=isinstance(initial.base, Super))
                return location(Reference((initial.name,), initial.loc), dependencies, owner)
            if isinstance(initial, (This, Super)):
                self.fail("THIS/SUPER requires a constant member", initial.loc)
            if isinstance(initial, Reference):
                binding = self.variable_binding(initial, pou)
                if binding is not None:
                    owner, var, fields = binding
                    if not var.constant:
                        self.fail(
                            f"Constant expression cannot depend on mutable {var.name}", initial.loc
                        )
                    dependencies.add((owner.name, var.name))
                    spec = var.type_name
                    for field in fields:
                        spec = member(spec, field, initial.loc, dependencies, pou)
                    return spec
                name = initial.parts[0]
                if len(initial.parts) == 1 and self.enum_candidates(name):
                    return None
                if len(initial.parts) != 2 or name not in self.type_declarations:
                    self.fail(f"Unknown constant {name}", initial.loc)
                return None
            spec = location(initial.base, dependencies, pou)
            if isinstance(initial, Member):
                return member(spec, initial.name, initial.loc, dependencies, pou)
            if isinstance(initial, BitAccess):
                inspect(initial.index, dependencies, pou)
                return "BOOL"
            for index in initial.indices:
                inspect(index, dependencies, pou)
            spec = shape(spec)
            return spec.element_type if isinstance(spec, (ArrayType, ArrayBounds)) else None

        def inspect(initial, dependencies, pou):
            if isinstance(initial, (Reference, Member, Index, BitAccess)):
                location(initial, dependencies, pou)
            elif isinstance(initial, Call):
                self.fail("Calls are not allowed in constant expressions", initial.loc)
            elif isinstance(initial, Unary):
                inspect(initial.operand, dependencies, pou)
            elif isinstance(initial, Binary):
                inspect(initial.left, dependencies, pou)
                inspect(initial.right, dependencies, pou)
            elif isinstance(initial, ArrayInitializer):
                for item in initial.items:
                    inspect(item.value, dependencies, pou)
            elif isinstance(initial, StructInitializer):
                for _, value in initial.fields:
                    inspect(value, dependencies, pou)

        def inspect_type(spec, dependencies, pou, active):
            # Bounds and type defaults can themselves lead back to a constant.
            # Named type declarations always resolve in global scope.
            if isinstance(spec, str) and spec in self.type_declarations:
                if spec in active:
                    return  # The independent type-graph check diagnoses type cycles.
                active.add(spec)
                declaration = self.type_declarations[spec]
                if not isinstance(declaration.definition, EnumDecl):
                    inspect(declaration.initial, dependencies, None)
                    inspect_type(declaration.definition, dependencies, None, active)
            elif isinstance(spec, ArrayBounds):
                for low, high in spec.bounds:
                    inspect(low, dependencies, pou)
                    inspect(high, dependencies, pou)
                inspect_type(spec.element_type, dependencies, pou, active)
            elif isinstance(spec, StringBounds):
                inspect(spec.length, dependencies, pou)
            elif isinstance(spec, (ArrayType, OpenArrayType, OpenArrayBounds)):
                inspect_type(spec.element_type, dependencies, pou, active)
            elif isinstance(spec, AliasType):
                inspect_type(spec.target, dependencies, pou, active)
            elif isinstance(spec, StructDecl):
                for field in spec.fields:
                    inspect(field.initial, dependencies, None)
                    inspect_type(field.type_name, dependencies, None, active)

        active, done = set(), set()

        def visit(key):
            if key in active:
                self.fail(
                    f"Constant dependency cycle involving {key[1]}",
                    self.variables[key[0]][key[1]].loc,
                )
            if key in done:
                return
            active.add(key)
            for dependency in edges[key]:
                visit(dependency)
            active.remove(key)
            done.add(key)

        try:
            for (owner, name), dependencies in edges.items():
                var = self.variables[owner][name]
                inspect(var.initial, dependencies, scopes[owner])
                inspect_type(var.type_name, dependencies, scopes[owner], set())
            for key in edges:
                visit(key)
        except RecursionError as error:
            raise ValidationError("Constant resolution nesting limit exceeded") from error

    def preflight_reference(
        self, expr: LValue, pou: Pou | None, path: tuple = ()
    ) -> tuple[Value, TypeSpec]:
        """Project only the scalar needed by a bound; never create its aggregate."""
        if isinstance(expr, Member) and isinstance(expr.base, (This, Super)):
            return self.preflight_reference(
                Reference((expr.name,), expr.loc),
                self.constant_owner(pou, expr.loc, base=isinstance(expr.base, Super)),
                path,
            )
        if isinstance(expr, (This, Super)):
            self.fail("THIS/SUPER requires a constant member", expr.loc)
        if isinstance(expr, Member):
            return self.preflight_reference(expr.base, pou, ((expr.name, pou), *path))
        if isinstance(expr, BitAccess):
            return self.preflight_reference(expr.base, pou, ((expr, pou), *path))
        if isinstance(expr, Index):
            return self.preflight_reference(expr.base, pou, ((expr.indices, pou), *path))
        binding = self.variable_binding(expr, pou)
        if binding is None:
            name = expr.parts[0]
            if path and len(expr.parts) != 2:
                self.fail("Array bounds require a local, global or enum constant", expr.loc)
            if name in self.type_declarations:
                self.preflight_scalar(name, expr.loc)
            value = self.enum_constant(expr, pou)
            if value is None:
                self.fail(f"Unknown constant {name}", expr.loc)
            return value, value.enum_type
        owner, var, fields = binding
        path = (*((field, pou) for field in fields), *path)
        pou = owner
        name = var.name
        key = pou.name, name
        if not var.constant or var.initial is None:
            self.fail(f"Constant expression requires a local constant, got {name}", expr.loc)
        if key in self.active_constants:
            self.fail(f"Constant dependency cycle involving {name}", expr.loc)
        if not path:
            return self.local_constant(name, pou, expr.loc)
        self.active_constants.add(key)
        try:
            return self.project_initializer(
                var.type_name, var.initial, path, pou, expr.loc, initial_scope=pou
            )
        finally:
            self.active_constants.remove(key)

    def project_initializer(
        self,
        spec,
        initial: Initializer | None,
        path: tuple,
        pou: Pou | None,
        loc: Location,
        *,
        initial_scope: Pou | None,
    ) -> tuple[Value, TypeSpec]:
        """Read one leaf from compact syntax, honoring aliases and field defaults."""
        candidates = [] if initial is None else [(initial, initial_scope)]
        active = set()
        while isinstance(spec, (str, AliasType)):
            if isinstance(spec, str):
                if spec in SCALAR_TYPES | {"STRING"}:
                    break
                if spec in active or len(active) >= 64:
                    self.fail("Cyclic or excessively deep constant type", loc)
                active.add(spec)
                declaration = self.type_declarations.get(spec)
                if declaration is None:
                    self.fail(f"Unknown value type {spec}", loc)
                if isinstance(declaration.definition, EnumDecl):
                    spec = self.preflight_scalar(spec, loc)
                    break
                if declaration.initial is not None:
                    candidates.append((declaration.initial, None))
                spec = declaration.definition
                pou = None
            else:
                # Resolved aliases can occur in caller-constructed syntax.
                if spec.default is not None:
                    self.fail("Resolved alias defaults cannot define expression bounds", loc)
                spec = spec.target
        if not path:
            kind = self.preflight_scalar(spec, loc, pou=pou)
            if candidates:
                candidate, candidate_scope = candidates[0]
                value, actual = self.constant_expression(candidate, candidate_scope)
                value = self.assignment_constant(value, actual, kind, candidate.loc)
                return check_value(kind, value), kind
            return check_value(
                kind,
                kind.default_member
                if isinstance(kind, EnumType)
                else False
                if kind == "BOOL"
                else ""
                if isinstance(kind, StringType)
                else 0,
            ), kind
        (first, selector_scope), *remaining = path
        if isinstance(spec, (str, EnumType)):
            kind = self.preflight_scalar(spec, loc)
            index = first.index if isinstance(first, BitAccess) else Reference((first,), loc)
            candidate, candidate_scope = candidates[0] if candidates else (None, pou)
            value, _ = self.project_initializer(
                kind, candidate, (), pou, loc, initial_scope=candidate_scope
            )
            position = self.bit_index(index, kind, selector_scope)
            if remaining:
                self.fail("A BOOL bit has no fields or indices", loc)
            return read_bit(value, kind, position), "BOOL"
        if isinstance(spec, StructDecl) and isinstance(first, str):
            field = next((item for item in spec.fields if item.name == first), None)
            if field is None:
                self.fail(f"Unknown constant structure field {first}", loc)
            for candidate, candidate_scope in candidates:
                if isinstance(candidate, (Reference, Index, Member, BitAccess)):
                    return self.preflight_reference(candidate, candidate_scope, path)
                if not isinstance(candidate, StructInitializer):
                    self.fail("Structure constant requires a structure initializer", candidate.loc)
                for name, value in candidate.fields:
                    if name == first:
                        return self.project_initializer(
                            field.type_name,
                            value,
                            tuple(remaining),
                            pou,
                            loc,
                            initial_scope=candidate_scope,
                        )
            return self.project_initializer(
                field.type_name, field.initial, tuple(remaining), pou, loc, initial_scope=pou
            )
        if isinstance(spec, (ArrayType, ArrayBounds)) and isinstance(first, tuple):
            array = self.resolve_array_bounds(spec, pou) if isinstance(spec, ArrayBounds) else spec
            if len(first) != len(array.bounds):
                self.fail("Constant array index has the wrong dimension", loc)
            offset = 0
            for index, (low, high) in zip(first, array.bounds):
                value, kind = self.constant_expression(index, selector_scope)
                self.require(kind, "INTEGER", index.loc)
                if not low <= value <= high:
                    self.fail("Constant array index outside bounds", index.loc)
                offset = offset * (high - low + 1) + value - low
            if candidates:
                candidate, candidate_scope = candidates[0]
                if isinstance(candidate, (Reference, Index, Member, BitAccess)):
                    return self.preflight_reference(candidate, candidate_scope, path)
                if not isinstance(candidate, ArrayInitializer):
                    self.fail("Array constant requires an array initializer", candidate.loc)
                for item in candidate.items:
                    if offset < item.count:
                        return self.project_initializer(
                            array.element_type,
                            item.value,
                            tuple(remaining),
                            pou,
                            loc,
                            initial_scope=candidate_scope,
                        )
                    offset -= item.count
            return self.project_initializer(
                array.element_type, None, tuple(remaining), pou, loc, initial_scope=pou
            )
        self.fail("Constant projection does not match its declared type", loc)
        raise AssertionError("unreachable")

    def resolve_array_bounds(self, spec: ArrayBounds, pou: Pou | None) -> ArrayType:
        bounds = []
        for low, high in spec.bounds:
            values = []
            for bound in (low, high):
                value, kind = self.constant_expression(bound, pou)
                self.require(kind, "INTEGER", bound.loc)
                values.append(value)
            bounds.append(tuple(values))
        try:
            element = spec.element_type
            if isinstance(element, StringBounds):
                element = self.resolve_string_bounds(element, pou)
            elif isinstance(element, ArrayBounds):
                element = self.resolve_array_bounds(element, pou)
            return ArrayType(tuple(bounds), element)
        except (TypeError, ValueError) as error:
            self.fail(str(error), spec.loc)
        raise AssertionError("unreachable")

    def resolve_string_bounds(self, spec: StringBounds, pou: Pou | None) -> StringType:
        value, kind = self.constant_expression(spec.length, pou)
        self.require(kind, "INTEGER", spec.length.loc)
        try:
            return StringType(value)
        except (TypeError, ValueError) as error:
            self.fail(str(error), spec.loc)
        raise AssertionError("unreachable")

    def preflight_scalar(
        self, spec: TypeSpec, loc: Location, active=None, pou: Pou | None = None
    ) -> TypeSpec:
        """Follow scalar aliases without evaluating defaults or allocating aggregates."""
        active = set() if active is None else active
        if isinstance(spec, StringBounds):
            return self.resolve_string_bounds(spec, pou)
        if isinstance(spec, StringType) or spec == "STRING":
            return StringType() if spec == "STRING" else spec
        if isinstance(spec, str) and spec in SCALAR_TYPES:
            return spec
        if isinstance(spec, str) and spec in self.type_declarations:
            if spec in active or len(active) >= 64:
                self.fail("Cyclic or excessively deep constant type", loc)
            active.add(spec)
            declaration = self.type_declarations[spec]
            if isinstance(declaration.definition, EnumDecl):
                return self.resolve_named(spec, loc)
            return self.preflight_scalar(declaration.definition, loc, active)
        if isinstance(spec, AliasType):
            return self.preflight_scalar(spec.target, loc, active, pou)
        if isinstance(spec, EnumType):
            return spec
        self.fail("Array bounds require scalar constants", loc)
        raise AssertionError("unreachable")

    def local_constant(self, name: str, pou: Pou, loc: Location) -> tuple[Value, TypeSpec]:
        var = self.variables[pou.name].get(name)
        if var is not None:
            pou = self.declaration_scope(pou, var)
        key = pou.name, name
        if key in self.active_constants:
            self.fail(f"Constant dependency cycle involving {name}", loc)
        if key in self.constant_values:
            return self.constant_values[key]
        var = self.variables[pou.name].get(name)
        if var is None or not var.constant:
            self.fail(f"Constant expression requires a local constant, got {name}", loc)
        if var.section != "VAR" or var.initial is None:
            self.fail("Local VAR CONSTANT requires an initializer", var.loc)
        self.active_constants.add(key)
        try:
            kind = (
                self.preflight_scalar(var.type_name, var.loc, pou=pou)
                if self.preflight_constants
                else self.resolve_spec(var.type_name, var.loc)
            )
            value = self.initializer(var.initial, kind, pou)
            result = value, kind
            self.constant_values[key] = result
            return result
        finally:
            self.active_constants.remove(key)

    def is_fb_type(self, kind: TypeSpec) -> bool:
        if not isinstance(kind, str):
            return False
        target = self.pous.get(kind)
        return kind in _BUILTIN_BLOCK_NAMES or (
            target is not None and target.kind == "FUNCTION_BLOCK"
        )

    def check_type_graph(self) -> None:
        """Check graph size and cycles before evaluating any allocating defaults."""
        measured: dict[str, tuple[int, int]] = {}
        active: set[str] = set()

        def measure(spec, loc: Location) -> tuple[int, int]:
            if isinstance(spec, str):
                if spec in SCALAR_TYPES | {"STRING"}:
                    return 1, 0
                if spec in active:
                    self.fail(f"Cyclic type definition involving {spec}", loc)
                if spec in measured:
                    return measured[spec]
                declaration = self.type_declarations.get(spec)
                if declaration is None:
                    self.fail(f"Unknown value type {spec}", loc)
                if len(active) >= 64:
                    self.fail("Type resolution depth exceeds 64 levels", loc)
                active.add(spec)
                leaves, depth = measure(declaration.definition, declaration.loc)
                active.remove(spec)
                depth += 1
                measured[spec] = leaves, depth
            elif isinstance(spec, (ArrayType, AliasType)):
                nested = spec.element_type if isinstance(spec, ArrayType) else spec.target
                leaves, depth = measure(nested, loc)
                leaves *= spec.size if isinstance(spec, ArrayType) else 1
                depth += isinstance(spec, AliasType)
            elif isinstance(spec, (StructDecl, StructType)):
                if not spec.fields:
                    self.fail("Structure requires at least one field", loc)
                fields = [
                    measure(field.type_name, field.loc if isinstance(field, VarDecl) else loc)
                    for field in spec.fields
                ]
                leaves = sum(count for count, _ in fields)
                depth = max((level for _, level in fields), default=0)
            elif isinstance(spec, (EnumDecl, EnumType, StringType)):
                leaves, depth = 1, 0
            else:
                self.fail(f"Unknown value type {spec}", loc)
            if leaves > 1_000_000:
                self.fail("Value type exceeds the 1000000 scalar leaf limit", loc)
            if depth > 64:
                self.fail("Type resolution depth exceeds 64 levels", loc)
            return leaves, depth

        for name, declaration in self.type_declarations.items():
            measure(name, declaration.loc)
        for pou in self.program.pous:
            if pou.return_type is not None:
                measure(pou.return_type, pou.loc)
            for variable in pou.variables:
                kind = variable.type_name
                if (
                    self.is_fb_type(kind)
                    or isinstance(kind, (FBArrayType, InterfaceArrayType, InterfaceType))
                    or isinstance(kind, str)
                    and kind in self.pous.interfaces
                ):
                    continue
                if isinstance(kind, ReferenceType):
                    measure(kind.target, variable.loc)
                elif isinstance(kind, OpenArrayType):
                    measure(kind.element_type, variable.loc)
                else:
                    measure(kind, variable.loc)

        # Measure expanded ownership before resolving any allocating defaults.
        # An IN_OUT location is an alias, so it contributes no owned storage.
        definitions = {
            item.name: item for item in (*timer_definitions(), *standard_block_definitions())
        }
        definitions.update(self.pous)
        totals: dict[str, tuple[int, int]] = {}
        visiting: set[str] = set()

        def storage(pou):
            if pou.name in visiting:
                self.fail(f"FB containment cycle involving {pou.name}", pou.loc)
            if pou.name in totals:
                return totals[pou.name]
            visiting.add(pou.name)
            instances = 0
            leaves = measure(pou.return_type, pou.loc)[0] if pou.return_type is not None else 0
            owned = list(pou.variables)
            if pou.kind == "FUNCTION_BLOCK":
                owned = [
                    var
                    for ancestor in self.pous.lineages.get(pou.name, (pou.name,))
                    for var in definitions[ancestor].variables
                ]
                owned.extend(
                    var
                    for method in self.pous.instance_methods(pou)
                    for var in method.variables
                    if var.section == "VAR_INST"
                )
            for var in owned:
                if var.section == "VAR_IN_OUT":
                    continue
                kind = var.type_name
                if isinstance(kind, FBArrayType) or self.is_fb_type(kind):
                    child_name = kind.element_type if isinstance(kind, FBArrayType) else kind
                    multiplier = kind.size if isinstance(kind, FBArrayType) else 1
                    child_instances, child_leaves = storage(definitions[child_name])
                    instances += multiplier * (1 + child_instances)
                    leaves += multiplier * child_leaves
                elif isinstance(kind, InterfaceArrayType):
                    leaves += kind.size
                elif isinstance(kind, (InterfaceType, ReferenceType)) or (
                    isinstance(kind, str) and kind in self.pous.interfaces
                ):
                    leaves += 1
                else:
                    leaves += measure(kind, var.loc)[0]
                if instances > 10_000:
                    self.fail("Expanded storage exceeds the 10000 FB instance limit", var.loc)
                if leaves > 1_000_000:
                    self.fail("Expanded storage exceeds the 1000000 scalar leaf limit", var.loc)
            visiting.remove(pou.name)
            totals[pou.name] = instances, leaves
            return totals[pou.name]

        for pou in self.program.pous:
            try:
                storage(pou)
            except RecursionError as error:
                raise ValidationError(
                    "FB containment validation nesting limit exceeded", pou.loc
                ) from error

    def bounded(self, type_name: TypeSpec, loc: Location) -> None:
        def depth(value: TypeSpec) -> int:
            if isinstance(value, AliasType):
                return 1 + depth(value.target)
            if isinstance(value, StructType):
                return 1 + max((depth(field.type_name) for field in value.fields), default=0)
            if isinstance(value, ArrayType):
                return depth(value.element_type)
            return int(isinstance(value, EnumType))

        if depth(type_name) > 64:
            self.fail("Type resolution depth exceeds 64 levels", loc)
        if value_leaf_count(type_name) > 1_000_000:
            self.fail("Value type exceeds the 1000000 scalar leaf limit", loc)

    def resolve_spec(self, definition: TypeSpec, loc: Location) -> TypeSpec:
        if definition == "STRING":
            return StringType()
        if isinstance(definition, str):
            if definition in SCALAR_TYPES:
                return definition
            return self.resolve_named(definition, loc)
        if isinstance(definition, ArrayType):
            result = ArrayType(definition.bounds, self.resolve_spec(definition.element_type, loc))
        elif is_value_type(definition):
            result = definition
        else:
            self.fail(f"Unknown value type {definition}", loc)
        self.bounded(result, loc)
        return result

    def resolve_named(self, name: str, loc: Location | None = None) -> TypeSpec:
        if name in self.resolving:
            self.fail(f"Cyclic type definition involving {name}", self.type_declarations[name].loc)
        if name in self.pous.types:
            return self.pous.types[name]
        declaration = self.type_declarations.get(name)
        if declaration is None:
            assert loc is not None
            self.fail(f"Unknown value type {name}", loc)
        if len(self.resolving) >= 64:
            self.fail("Type resolution depth exceeds 64 levels", declaration.loc)
        self.resolving.add(name)
        definition = declaration.definition
        try:
            if isinstance(definition, EnumDecl):
                if definition.base_type not in {"INT", "UINT", "DINT", "UDINT"}:
                    self.fail("Enum base type must be INT, UINT, DINT or UDINT", declaration.loc)
                members = []
                names, values = set(), set()
                current = -1
                for member in definition.members:
                    current = current + 1 if member.value is None else member.value
                    if member.name in names or current in values:
                        self.fail("Duplicate enum member name or value", member.loc)
                    check_value(definition.base_type, current)
                    names.add(member.name)
                    values.add(current)
                    members.append((member.name, current))
                if not members:
                    self.fail("Enum requires at least one member", declaration.loc)
                result = EnumType(
                    name,
                    tuple(members),
                    definition.base_type,
                    strict=definition.strict,
                    qualified_only=definition.qualified_only,
                )
                # Its own qualified default is legal while its definition is active.
                self.pous.types[name] = result
                if declaration.initial is not None:
                    value = self.initializer(declaration.initial, result, enum_scope=result)
                    result = replace(result, default_member=value.name)
            elif isinstance(definition, StructDecl):
                names = set()
                fields = []
                for field in definition.fields:
                    self.initialization_arguments(field)
                    if field.name in names:
                        self.fail(f"Duplicate structure field {field.name}", field.loc)
                    names.add(field.name)
                    fields.append(
                        StructField(field.name, self.resolve_spec(field.type_name, field.loc))
                    )
                result = StructType(name, tuple(fields))
                self.bounded(result, declaration.loc)
                prepared = tuple(
                    replace(field, default=self.initializer(raw.initial, field.type_name))
                    if raw.initial is not None
                    else field
                    for field, raw in zip(fields, definition.fields)
                )
                result = StructType(name, prepared)
                if declaration.initial is not None:
                    self.fail(
                        "STRUCT type defaults must be declared on fields", declaration.initial.loc
                    )
            else:
                target = self.resolve_spec(definition, declaration.loc)
                result = AliasType(name, target)
                self.bounded(result, declaration.loc)
                if declaration.initial is not None:
                    result = replace(result, default=self.initializer(declaration.initial, target))
            self.bounded(result, declaration.loc)
        except (TypeError, ValueError) as error:
            self.fail(str(error), declaration.loc)
        finally:
            self.resolving.remove(name)
        self.pous.types[name] = result
        return result

    def initialization_arguments(self, var: VarDecl, *, fb_instance: bool = False) -> None:
        """All declaration contexts must reject FB-only setup metadata on values."""
        if (
            var.init_arguments is not None or var.element_init_arguments is not None
        ) and not fb_instance:
            self.fail("Initialization arguments require a function-block instance", var.loc)

    def declarations(self, pou: Pou) -> None:
        original = pou
        if pou.implements and pou.kind != "FUNCTION_BLOCK":
            self.fail("IMPLEMENTS requires FUNCTION_BLOCK", pou.loc)
        if pou.kind not in {
            "FUNCTION",
            "FUNCTION_BLOCK",
            "PROGRAM",
            "GVL",
            "ACTION",
            *_MEMBER_KINDS,
        }:
            self.fail(f"Unsupported POU kind {pou.kind}", pou.loc)
        if pou.kind == "FUNCTION" or (pou.kind in _MEMBER_KINDS and pou.return_type is not None):
            try:
                return_type = self.resolve_spec(pou.return_type, pou.loc)
            except (TypeError, ValueError) as error:
                self.fail(str(error), pou.loc)
            pou = replace(pou, return_type=return_type)
        elif pou.return_type is not None:
            self.fail(f"{pou.kind} cannot have a return type", pou.loc)
        variables: dict[str, VarDecl] = {}
        # Install names before checking constants so local names shadow enum type names.
        self.variables[pou.name] = {var.name: var for var in pou.variables}
        for var in pou.variables:
            if var.name in variables or (var.name == pou.result_name and pou.kind in _RESULT_KINDS):
                self.fail(f"Duplicate variable or result name {var.name}", var.loc)
            if pou.kind.startswith("PROPERTY_") and var.section != "VAR":
                self.fail("Property accessors only support local VAR declarations", var.loc)
            if var.section == "VAR_INST" and (pou.kind != "METHOD" or var.constant):
                self.fail("VAR_INST requires an FB METHOD and cannot be CONSTANT", var.loc)
            if var.section not in _SECTIONS:
                self.fail(f"Unsupported variable section {var.section}", var.loc)
            if var.section == "VAR_TEMP" and pou.kind not in {"FUNCTION_BLOCK", "PROGRAM"}:
                self.fail("VAR_TEMP is only supported in FUNCTION_BLOCK or PROGRAM", var.loc)
            if pou.kind == "PROGRAM" and var.section == "VAR_IN_OUT":
                self.fail("PROGRAM does not support VAR_IN_OUT", var.loc)
            kind = var.type_name
            target_name = kind.element_type if isinstance(kind, FBArrayType) else kind
            target = self.pous.get(target_name) if isinstance(target_name, str) else None
            if isinstance(kind, InterfaceArrayType):
                var = self.interface_array_variable(var)
            elif isinstance(kind, ReferenceType):
                var = self.reference_variable(var)
            elif isinstance(kind, InterfaceType) or (
                isinstance(kind, str) and kind in self.pous.interfaces
            ):
                var = self.interface_variable(var)
            elif target is not None and target.kind == "FUNCTION_BLOCK":
                if var.constant:
                    self.fail("FB instances cannot be constant", var.loc)
                if var.section not in {"VAR", "VAR_TEMP", "VAR_INST"}:
                    self.fail("FB instances must be local VAR or FB VAR_TEMP", var.loc)
                self.contains[pou.name].add(target.name)
            elif isinstance(kind, OpenArrayType):
                var = replace(
                    var,
                    type_name=OpenArrayType(
                        kind.rank, self.resolve_spec(kind.element_type, var.loc)
                    ),
                )
            else:
                try:
                    var = replace(var, type_name=self.resolve_spec(var.type_name, var.loc))
                    if var.initial is not None:
                        if var.section == "VAR_IN_OUT":
                            self.fail("VAR_IN_OUT cannot have an initializer", var.loc)
                        var = replace(
                            var,
                            default=(
                                self.local_constant(var.name, pou, var.loc)[0]
                                if var.constant
                                else self.initializer(
                                    var.initial,
                                    var.type_name,
                                    self.pous[pou.owner]
                                    if var.section == "VAR_INST"
                                    else self.declaration_scope(pou, var),
                                )
                            ),
                        )
                except (TypeError, ValueError) as error:
                    self.fail(str(error), var.loc)
            self.initialization_arguments(
                var, fb_instance=target is not None and target.kind == "FUNCTION_BLOCK"
            )
            variables[var.name] = var
        self.variables[pou.name] = variables
        prepared = replace(pou, variables=tuple(variables.values()))
        self.pous[pou.name] = original if prepared == original else prepared

    def enum_candidates(self, member: str) -> tuple[str, ...]:
        """Count declarations, not transparent aliases, without resolving defaults."""
        return tuple(
            name
            for name, declaration in self.type_declarations.items()
            if (
                isinstance(declaration.definition, EnumDecl)
                and not declaration.definition.qualified_only
                and any(item.name == member for item in declaration.definition.members)
            )
        )

    def enum_constant(self, ref: Reference, pou: Pou | None = None) -> EnumValue | None:
        if not ref.parts:
            return None
        name = ref.parts[0]
        if self.variable_binding(ref, pou) is not None or (
            pou is not None and name == pou.result_name and pou.kind in _RESULT_KINDS
        ):
            return None
        member_name = ref.parts[-1]
        if len(ref.parts) == 1:
            candidates = self.enum_candidates(name)
            if len(candidates) > 1:
                self.fail(f"Ambiguous enum member {name}", ref.loc)
            if not candidates:
                return None
            name = candidates[0]
        declared = self.pous.types.get(name)
        if declared is None and name in self.type_declarations:
            declared = self.resolve_named(name, ref.loc)
        enum_type = canonical_type(declared) if declared is not None else None
        if not isinstance(enum_type, EnumType):
            return None
        if len(ref.parts) not in {1, 2}:
            self.fail("Enum constants require a qualified member name", ref.loc)
        for member, value in enum_type.members:
            if member == member_name:
                return EnumValue(enum_type, member, value)
        self.fail(f"Unknown enum member {member_name} on {name}", ref.loc)
        raise AssertionError("unreachable")

    def initializer(
        self,
        initial: Initializer,
        expected: TypeSpec,
        pou: Pou | None = None,
        enum_scope: EnumType | None = None,
    ) -> Value:
        # Unwrap only the container: element aliases carry their own defaults.
        target = expected
        while isinstance(target, AliasType):
            target = target.target
        try:
            if isinstance(initial, ArrayInitializer):
                if not isinstance(target, ArrayType):
                    self.fail("Array initializer requires an array type", initial.loc)
                if sum(item.count for item in initial.items) > target.size:
                    self.fail("Too many array initializer values", initial.loc)
                values = []
                for item in initial.items:
                    if item.count <= 0:
                        self.fail("Initializer repetition count must be positive", item.value.loc)
                    value = self.initializer(item.value, target.element_type, pou)
                    values.extend([value] * item.count)
                return array_initial_value(target, values)
            if isinstance(initial, StructInitializer):
                if not isinstance(target, StructType):
                    self.fail("Structure initializer requires a structure type", initial.loc)
                fields = {field.name: field for field in target.fields}
                values = {}
                for name, value in initial.fields:
                    if name in values:
                        self.fail(f"Duplicate structure initializer field {name}", value.loc)
                    if name not in fields:
                        self.fail(f"Unknown structure initializer field {name}", value.loc)
                    values[name] = self.initializer(value, fields[name].type_name, pou)
                return check_value(expected, values)
            if (
                isinstance(initial, Reference)
                and enum_scope is not None
                and len(initial.parts) == 1
                and initial.parts[0] in dict(enum_scope.members)
            ):
                initial = replace(initial, parts=(enum_scope.name, *initial.parts))
            value, actual = self.constant_expression(initial, pou)
            value = self.assignment_constant(value, actual, expected, initial.loc)
            return check_value(expected, value)
        except (TypeError, ValueError) as error:
            self.fail(str(error), initial.loc)
        raise AssertionError("unreachable")

    def constant(self, expr: Expr) -> Scalar:
        if isinstance(expr, Literal):
            if isinstance(expr.type_name, StringType) or type(expr.value) is str:
                try:
                    kind = expr.type_name or StringType(max(1, len(expr.value)))
                    return check_value(kind, expr.value)
                except (TypeError, ValueError) as exc:
                    self.fail(str(exc), expr.loc)
            if expr.type_name in INTEGER_TYPES:
                try:
                    return check_value(expr.type_name, expr.value)
                except (TypeError, ValueError) as exc:
                    self.fail(str(exc), expr.loc)
            if expr.type_name == "TIME":
                try:
                    return check_value("TIME", expr.value)
                except (TypeError, ValueError) as exc:
                    self.fail(str(exc), expr.loc)
            if expr.type_name in FLOAT_TYPES or type(expr.value) is float:
                try:
                    return check_float_literal(expr.type_name or "LREAL", expr.value, expr.raw_text)
                except (TypeError, ValueError) as exc:
                    self.fail(str(exc), expr.loc)
            if type(expr.value) is int:
                try:
                    if expr.type_name is not None:
                        return check_value(expr.type_name, expr.value)
                    checked_integer(expr.value)
                except (TypeError, ValueError) as exc:
                    self.fail(str(exc), expr.loc)
            return expr.value
        self.fail("Expected a literal", expr.loc)
        raise AssertionError("unreachable")

    def constant_owner(self, pou: Pou | None, loc: Location, *, base: bool = False) -> Pou:
        if pou is None or (
            pou.kind not in {"FUNCTION_BLOCK", "PROPERTY_DECL", "ACTION"}
            and pou.kind not in _MEMBER_KINDS
        ):
            self.fail("THIS/SUPER requires an owning FUNCTION_BLOCK", loc)
        owner = pou if pou.kind == "FUNCTION_BLOCK" else self.pous[pou.owner]
        if owner.kind != "FUNCTION_BLOCK":
            self.fail("THIS/SUPER requires an owning FUNCTION_BLOCK", loc)
        if base:
            parent = self.pous.bases.get(owner.name)
            if parent is None:
                self.fail("SUPER requires a lexical base FUNCTION_BLOCK", loc)
            owner = self.pous[parent]
        return owner

    def constant_expression(self, expr: Expr, pou: Pou | None = None) -> tuple[Value, TypeSpec]:
        """Evaluate only checked, side-effect-free declaration expressions."""
        try:
            if self.preflight_constants and isinstance(expr, (Reference, Index, Member, BitAccess)):
                return self.preflight_reference(expr, pou)
            if isinstance(expr, Literal):
                value = self.constant(expr)
                kind = expr.type_name or (
                    "BOOL"
                    if type(value) is bool
                    else "LREAL"
                    if type(value) is float
                    else StringType(max(1, len(expr.value)))
                    if type(value) is str
                    else "INTEGER"
                )
                return value, kind
            if isinstance(expr, Reference):
                binding = self.variable_binding(expr, pou)
                if binding is not None:
                    owner, var, fields = binding
                    value, kind = self.local_constant(var.name, owner, expr.loc)
                    for field in fields:
                        if canonical_type(kind) in INTEGER_TYPES:
                            position = self.bit_index(Reference((field,), expr.loc), kind, pou)
                            value, kind = read_bit(value, kind, position), "BOOL"
                        else:
                            kind = self.field_type(kind, field, expr.loc)
                            value = value[field]
                    return value, canonical_type(kind)
                value = self.enum_constant(expr, pou)
                if value is None:
                    self.fail(
                        "Constant expression requires a local, global or enum constant", expr.loc
                    )
                return value, value.enum_type
            if isinstance(expr, Member):
                if isinstance(expr.base, (This, Super)):
                    return self.constant_expression(
                        Reference((expr.name,), expr.loc),
                        self.constant_owner(pou, expr.loc, base=isinstance(expr.base, Super)),
                    )
                value, kind = self.constant_expression(expr.base, pou)
                if canonical_type(kind) in INTEGER_TYPES:
                    position = self.bit_index(Reference((expr.name,), expr.loc), kind, pou)
                    return read_bit(value, kind, position), "BOOL"
                field = self.field_type(kind, expr.name, expr.loc)
                return value[expr.name], canonical_type(field)
            if isinstance(expr, BitAccess):
                value, kind = self.constant_expression(expr.base, pou)
                return read_bit(value, kind, self.bit_index(expr.index, kind, pou)), "BOOL"
            if isinstance(expr, Index):
                value, kind = self.constant_expression(expr.base, pou)
                kind = canonical_type(kind)
                if not isinstance(kind, ArrayType) or len(expr.indices) != len(kind.bounds):
                    self.fail("Constant array index has the wrong type or dimension", expr.loc)
                for index, (low, high) in zip(expr.indices, kind.bounds):
                    offset, index_type = self.constant_expression(index, pou)
                    self.require(index_type, "INTEGER", index.loc)
                    if not low <= offset <= high:
                        self.fail("Constant array index outside bounds", index.loc)
                    value = value[offset - low]
                return value, canonical_type(kind.element_type)
            if isinstance(expr, Unary):
                if (
                    expr.op == "-"
                    and isinstance(expr.operand, Literal)
                    and expr.operand.type_name is None
                    and type(expr.operand.value) is int
                    and expr.operand.value == 2**63
                ):
                    return -(2**63), "INTEGER"
                value, kind = self.constant_expression(expr.operand, pou)
                result_type = self.unary_type(expr, canonical_type(kind))
                result = (
                    bitwise_value("NOT", value, None, result_type)
                    if expr.op == "NOT"
                    else -value
                    if expr.op == "-"
                    else value
                )
                return (
                    checked_integer(result)
                    if result_type == "INTEGER"
                    else check_value(result_type, result)
                ), result_type
            if isinstance(expr, Binary):
                if expr.op in {"AND_THEN", "OR_ELSE"}:
                    self.constant_expression_type(expr, pou)
                    left, _ = self.constant_expression(expr.left, pou)
                    if (expr.op == "AND_THEN" and not left) or (expr.op == "OR_ELSE" and left):
                        return left, "BOOL"
                    return self.constant_expression(expr.right, pou)[0], "BOOL"
                left, left_type = self.constant_expression(expr.left, pou)
                right, right_type = self.constant_expression(expr.right, pou)
                left_type, right_type = canonical_type(left_type), canonical_type(right_type)
                result_type = self.binary_type(expr, left_type, right_type)
                if expr.op in {"AND", "OR", "XOR"}:
                    return bitwise_value(expr.op, left, right, result_type), result_type
                if isinstance(left_type, EnumType):
                    left, right = left.value, right.value
                elif left_type == right_type == "TIME" or isinstance(left_type, StringType):
                    pass
                elif left_type != "BOOL" or right_type != "BOOL":
                    common = numeric_type(left_type, right_type)
                    if common in FLOAT_TYPES:
                        left, right = check_value(common, left), check_value(common, right)
                result = self.constant_binary(expr.op, left, right, result_type)
                return result, result_type
            self.fail("Calls and mutable values are not allowed in constant expressions", expr.loc)
        except (TypeError, ValueError, ZeroDivisionError, OverflowError) as error:
            self.fail(str(error), expr.loc)
        raise AssertionError("unreachable")

    def constant_expression_type(self, expr: Expr, pou: Pou | None) -> TypeSpec:
        """Check skipped constant operands without evaluating arithmetic operators."""
        if isinstance(expr, Index):
            kind = canonical_type(self.constant_expression_type(expr.base, pou))
            if not isinstance(kind, ArrayType) or len(expr.indices) != len(kind.bounds):
                self.fail("Constant array index has the wrong type or dimension", expr.loc)
            for index in expr.indices:
                self.require(self.constant_expression_type(index, pou), "INTEGER", index.loc)
            return canonical_type(kind.element_type)
        if isinstance(expr, Member):
            if isinstance(expr.base, (This, Super)):
                return self.constant_expression_type(
                    Reference((expr.name,), expr.loc),
                    self.constant_owner(pou, expr.loc, base=isinstance(expr.base, Super)),
                )
            kind = self.constant_expression_type(expr.base, pou)
            if canonical_type(kind) in INTEGER_TYPES:
                self.bit_index(Reference((expr.name,), expr.loc), kind, pou)
                return "BOOL"
            return canonical_type(self.field_type(kind, expr.name, expr.loc))
        if isinstance(expr, BitAccess):
            kind = self.constant_expression_type(expr.base, pou)
            self.bit_index(expr.index, kind, pou)
            return "BOOL"
        if isinstance(expr, Binary):
            return self.binary_type(
                expr,
                canonical_type(self.constant_expression_type(expr.left, pou)),
                canonical_type(self.constant_expression_type(expr.right, pou)),
            )
        if isinstance(expr, Unary):
            if (
                expr.op == "-"
                and isinstance(expr.operand, Literal)
                and expr.operand.type_name is None
                and type(expr.operand.value) is int
                and expr.operand.value == 2**63
            ):
                return "INTEGER"
            return self.unary_type(
                expr, canonical_type(self.constant_expression_type(expr.operand, pou))
            )
        return self.constant_expression(expr, pou)[1]

    @staticmethod
    def constant_binary(op: str, left: Value, right: Value, kind: TypeSpec) -> Value:
        if op == "+":
            value = left + right
        elif op == "-":
            value = left - right
        elif op == "*":
            value = left * right
        elif op == "/":
            value = left / right if kind in FLOAT_TYPES else trunc_div(left, right)
        elif op == "MOD":
            value = left - trunc_div(left, right) * right
        elif op == "=":
            return left == right
        elif op == "<>":
            return left != right
        elif op == "<":
            return left < right
        elif op == "<=":
            return left <= right
        elif op == ">":
            return left > right
        elif op == ">=":
            return left >= right
        elif op in {"AND", "OR", "XOR"}:
            return bitwise_value(op, left, right, kind)
        else:
            raise ValueError(f"Unsupported constant operator {op}")
        return checked_integer(value) if kind == "INTEGER" else check_value(kind, value)

    def field_type(self, type_name: TypeSpec, field: str, loc: Location) -> TypeSpec:
        target_type = canonical_type(type_name)
        if isinstance(target_type, StructType):
            for member in target_type.fields:
                if member.name == field:
                    return member.type_name
            self.fail(f"Unknown field {field} on {target_type.name}", loc)
        target = self.pous.get(type_name) if isinstance(type_name, str) else None
        if target is None or target.kind not in {"FUNCTION_BLOCK", "GVL", "PROGRAM"}:
            self.fail(f"Type {type_name} has no field {field}", loc)
        binding = self.fb_variable(target.name, field)
        var = binding[1] if binding is not None else None
        if var is None:
            self.fail(f"Unknown field {field} on {target.name}", loc)
        if target.kind == "FUNCTION_BLOCK" and var.section not in {"VAR_INPUT", "VAR_OUTPUT"}:
            self.fail(f"Private FB field {field}", loc)
        if target.kind == "PROGRAM" and var.section == "VAR_TEMP":
            self.fail(f"PROGRAM VAR_TEMP {field} is private", loc)
        return var.type_name

    def property_target(self, ref: LValue, pou: Pou) -> tuple[LValue | None, Property] | None:
        """Find a whole property without evaluating its receiver or its getter."""
        receiver = None
        if isinstance(ref, Member):
            receiver, name = ref.base, ref.name
        elif isinstance(ref, Reference):
            name = ref.parts[-1]
            if len(ref.parts) > 1:
                receiver = Reference(ref.parts[:-1], ref.loc)
        else:
            return None
        if receiver is None:
            owner = self.pous.lexical_owner(pou)
            if (
                owner is None
                or name in self.variables[pou.name]
                or pou.kind == "FUNCTION_BLOCK"
                and self.fb_variable(pou.name, name) is not None
                or (name == pou.result_name and pou.kind in _RESULT_KINDS)
            ):
                return None
        else:
            if not any(property_name == name for _, property_name in self.pous.properties):
                return None
            if isinstance(ref, Reference) and self.enum_constant(ref, pou) is not None:
                return None
            owner = self.reference(receiver, pou)
        if isinstance(owner, InterfaceType):
            owner = owner.name
        prop = self.pous.properties.get((owner, name)) if isinstance(owner, str) else None
        return (receiver, prop) if prop is not None else None

    def reference(
        self, ref: LValue, pou: Pou, *, writable: bool = False, allow_property: bool = False
    ) -> TypeSpec:
        kind = self.raw_reference(ref, pou, writable=writable, allow_property=allow_property)
        return kind.target if isinstance(kind, ReferenceType) else kind

    def raw_reference(
        self, ref: LValue, pou: Pou, *, writable: bool = False, allow_property: bool = False
    ) -> TypeSpec:
        if isinstance(ref, (This, Super)):
            owner = self.pous.lexical_owner(pou)
            if owner is None or self.pous[owner].kind != "FUNCTION_BLOCK":
                self.fail(
                    f"{'SUPER' if isinstance(ref, Super) else 'THIS'} requires an owning FUNCTION_BLOCK",
                    ref.loc,
                )
            if isinstance(ref, Super):
                owner = self.pous.bases.get(owner)
                if owner is None:
                    self.fail("SUPER requires a lexical base FUNCTION_BLOCK", ref.loc)
            return owner
        property_target = self.property_target(ref, pou)
        if property_target is not None:
            receiver, prop = property_target
            if not allow_property:
                self.fail("Property is not addressable storage", ref.loc)
            accessor = prop.setter if writable else prop.getter
            if accessor is None:
                self.fail(
                    f"Property {prop.name} has no {'SET' if writable else 'GET'} accessor", ref.loc
                )
            self.member_access(accessor, pou, ref.loc)
            targets = self.pous.property_writes if writable else self.pous.property_reads
            targets[id(ref)] = receiver, accessor.name
            static = isinstance(receiver, Super)
            if static:
                self.pous.static_dispatch.add(id(ref))
            self.call_edge(pou, accessor, static=static)
            return accessor.return_type
        if isinstance(ref, BitAccess):
            kind = self.reference(ref.base, pou, writable=writable)
            self.pous.bit_accesses[id(ref)] = ref.base, self.bit_index(ref.index, kind, pou)
            return "BOOL"
        if isinstance(ref, Index):
            base = canonical_type(self.reference(ref.base, pou, writable=writable))
            if not isinstance(base, (ArrayType, FBArrayType, InterfaceArrayType, OpenArrayType)):
                self.fail("Indexing requires an array", ref.loc)
            rank = base.rank if isinstance(base, OpenArrayType) else len(base.bounds)
            if len(ref.indices) != rank:
                self.fail(f"Array requires {rank} indices, got {len(ref.indices)}", ref.loc)
            for index in ref.indices:
                self.require(self.expression(index, pou), "INTEGER", index.loc)
            return base.element_type
        if isinstance(ref, Member):
            if isinstance(ref.base, (This, Super)):
                owner = self.reference(ref.base, pou)
                binding = self.fb_variable(owner, ref.name)
                if binding is None:
                    self.fail(f"Unknown field {ref.name} on {owner}", ref.loc)
                _, var = binding
                if isinstance(ref.base, Super) and var.section == "VAR_TEMP":
                    self.fail("SUPER cannot access another body's VAR_TEMP", ref.loc)
                if pou.kind in _MEMBER_KINDS and var.section in {"VAR_TEMP", "VAR_IN_OUT"}:
                    self.fail(
                        f"Owner {var.section} {var.name} is inaccessible from members", ref.loc
                    )
                if writable and var.constant:
                    self.fail(f"Constant {var.name} is not a writable reference", ref.loc)
                return var.type_name
            kind = self.reference(ref.base, pou, writable=writable)
            if canonical_type(kind) in INTEGER_TYPES:
                position = self.bit_index(Reference((ref.name,), ref.loc), kind, pou)
                self.pous.bit_accesses[id(ref)] = ref.base, position
                return "BOOL"
            return self.field_type(kind, ref.name, ref.loc)
        binding = self.variable_binding(ref, pou)
        if binding is not None and not binding[2]:
            _, var, _ = binding
            if writable and var.constant:
                self.fail(f"Constant {var.name} is not a writable reference", ref.loc)
            return var.type_name
        enum_value = self.enum_constant(ref, pou)
        if enum_value is not None:
            if writable:
                self.fail("Enum constant is not a writable reference", ref.loc)
            self.pous.enum_values[id(ref)] = enum_value
            return enum_value.enum_type
        if not ref.parts:
            self.fail("Empty reference", ref.loc)
        if len(ref.parts) > 1:
            base = Reference(ref.parts[:-1], ref.loc)
            kind = self.reference(base, pou, writable=writable)
            field = ref.parts[-1]
            if canonical_type(kind) in INTEGER_TYPES:
                position = self.bit_index(Reference((field,), ref.loc), kind, pou)
                self.pous.bit_accesses[id(ref)] = base, position
                return "BOOL"
            return self.field_type(kind, field, ref.loc)
        name, *fields = ref.parts
        if name == pou.result_name and pou.kind in _RESULT_KINDS:
            if pou.return_type is None:
                self.fail("Void method has no result value", ref.loc)
            type_name = pou.return_type
        else:
            namespace = self.pous.get(name)
            if namespace is None or namespace.kind not in {"GVL", "PROGRAM"}:
                self.fail(f"Unknown reference {name}", ref.loc)
            if writable:
                self.fail("Namespace is not a writable value", ref.loc)
            type_name = namespace.name
        for field in fields:
            type_name = self.field_type(type_name, field, ref.loc)
        assert type_name is not None
        return type_name

    def bit_index(self, index: Expr, kind: TypeSpec, pou: Pou | None) -> int:
        """Resolve a literal or local constant selector once at validation time."""
        try:
            width = bit_width(kind)
            if not isinstance(index, Literal) and not (
                isinstance(index, Reference) and self.variable_binding(index, pou) is not None
            ):
                self.fail("Bit index requires a literal or local/global scalar constant", index.loc)
            position, actual = self.constant_expression(index, pou)
            self.require(actual, "INTEGER", index.loc)
            if type(position) is not int or not 0 <= position < width:
                self.fail(f"Bit index must be in range 0..{width - 1}", index.loc)
            return position
        except (TypeError, ValueError) as error:
            self.fail(str(error), index.loc)
        raise AssertionError("unreachable")

    @staticmethod
    def compatible(target: TypeSpec, actual: TypeSpec) -> bool:
        target, actual = canonical_type(target), canonical_type(actual)
        if isinstance(target, StringType) or isinstance(actual, StringType):
            return isinstance(target, StringType) and isinstance(actual, StringType)
        if isinstance(target, (ArrayType, StructType, EnumType)) or isinstance(
            actual, (ArrayType, StructType, EnumType)
        ):
            return same_type(target, actual)
        return (
            (target == actual == "BOOL")
            or (target == actual == "TIME")
            or (target in _INTEGER_CATEGORIES and actual in _INTEGER_CATEGORIES)
            or (target in FLOAT_TYPES and actual in _NUMERIC_CATEGORIES)
            or (target == "NUMERIC" and actual in _NUMERIC_CATEGORIES)
        )

    def require(self, actual: TypeSpec, category: TypeSpec, loc: Location) -> None:
        if not self.compatible(category, actual):
            self.fail(f"Expected {category}, got {actual}", loc)

    def assignment_constant(
        self, value: Value, actual: TypeSpec, expected: TypeSpec, loc: Location
    ) -> Value:
        """Convert only validated integer constants into declared strict members."""
        target = canonical_type(expected)
        if (
            isinstance(target, EnumType)
            and target.strict
            and canonical_type(actual) in _INTEGER_CATEGORIES
            and type(value) is int
        ):
            for name, number in target.members:
                if number == value:
                    return EnumValue(target, name, number)
            self.fail(f"Integer constant {value} is not a member of {target}", loc)
        self.require(actual, expected, loc)
        return value

    def require_value(self, expr: Expr, expected: TypeSpec, pou: Pou) -> None:
        """Check a value boundary; writable bindings retain exact type checking."""
        actual = self.expression(expr, pou)
        target = canonical_type(expected)
        if (
            isinstance(target, EnumType)
            and target.strict
            and canonical_type(actual) in _INTEGER_CATEGORIES
        ):
            value, kind = self.constant_expression(expr, pou)
            converted = self.assignment_constant(value, kind, expected, expr.loc)
            self.pous.enum_values[id(expr)] = converted
        else:
            self.require(actual, expected, expr.loc)

    def expression(self, expr: Expr, pou: Pou) -> TypeSpec:
        if isinstance(expr, Literal):
            self.constant(expr)
            if isinstance(expr.type_name, StringType) or type(expr.value) is str:
                return expr.type_name or StringType(max(1, len(expr.value)))
            if expr.type_name == "TIME":
                return "TIME"
            if expr.type_name in FLOAT_TYPES or type(expr.value) is float:
                return expr.type_name or "LREAL"
            if type(expr.value) is bool:
                return "BOOL"
            return expr.type_name or "INTEGER"
        if isinstance(expr, (Reference, Index, Member, BitAccess)):
            type_name = self.reference(expr, pou, allow_property=True)
            if not is_value_type(type_name):
                self.fail("FB instance cannot be used as a scalar value", expr.loc)
            return type_name
        if isinstance(expr, Call):
            return self.call(expr, pou, as_expression=True)
        if isinstance(expr, Unary):
            if (
                expr.op == "-"
                and isinstance(expr.operand, Literal)
                and expr.operand.type_name is None
                and type(expr.operand.value) is int
                and expr.operand.value == 2**63
            ):
                return "INTEGER"
            return self.unary_type(expr, canonical_type(self.expression(expr.operand, pou)))
        if isinstance(expr, Binary):
            if expr.op in {"=", "<>"}:
                for reference, zero in ((expr.left, expr.right), (expr.right, expr.left)):
                    if self.literal_zero(zero) and isinstance(
                        reference, (Reference, Index, Member)
                    ):
                        kind = self.reference(reference, pou, allow_property=True)
                        if isinstance(kind, InterfaceType):
                            self.pous.interface_comparisons[id(expr)] = reference
                            return "BOOL"
            left = canonical_type(self.expression(expr.left, pou))
            right = canonical_type(self.expression(expr.right, pou))
            return self.binary_type(expr, left, right)
        self.fail("Unsupported expression", expr.loc)
        raise AssertionError("unreachable")

    def unary_type(self, expr: Unary, operand: TypeSpec) -> TypeSpec:
        if operand == "TIME":
            if expr.op == "+":
                return "TIME"
            self.fail("TIME only supports unary +", expr.loc)
        if expr.op == "NOT":
            try:
                return bitwise_result_type(expr.op, operand)
            except (TypeError, ValueError) as error:
                self.fail(str(error), expr.loc)
        if expr.op in {"+", "-"}:
            self.require(operand, "NUMERIC", expr.loc)
            return numeric_type(operand, operand)
        self.fail(f"Unsupported unary operator {expr.op}", expr.loc)
        raise AssertionError("unreachable")

    def binary_type(self, expr: Binary, left: TypeSpec, right: TypeSpec) -> TypeSpec:
        if expr.op in {"AND_THEN", "OR_ELSE"}:
            self.require(left, "BOOL", expr.left.loc)
            self.require(right, "BOOL", expr.right.loc)
            return "BOOL"
        if isinstance(left, StringType) or isinstance(right, StringType):
            if (
                isinstance(left, StringType)
                and isinstance(right, StringType)
                and expr.op in {"=", "<>", "<", "<=", ">", ">="}
            ):
                return "BOOL"
            self.fail("STRING operands require two strings and a comparison", expr.loc)
        if isinstance(left, EnumType) or isinstance(right, EnumType):
            if (
                isinstance(left, EnumType)
                and isinstance(right, EnumType)
                and same_type(left, right)
                and expr.op in {"=", "<>", "<", "<=", ">", ">="}
            ):
                return "BOOL"
            self.fail("Enum operands require the same enum type and a comparison", expr.loc)
        if "TIME" in (left, right):
            self.require(left, "TIME", expr.left.loc)
            self.require(right, "TIME", expr.right.loc)
            if expr.op in {"+", "-"}:
                return "TIME"
            if expr.op in {"=", "<>", "<", "<=", ">", ">="}:
                return "BOOL"
            self.fail(f"Unsupported TIME operator {expr.op}", expr.loc)
        if expr.op in {"AND", "OR", "XOR"}:
            try:
                return bitwise_result_type(expr.op, left, right)
            except (TypeError, ValueError) as error:
                self.fail(str(error), expr.loc)
        if expr.op in {"=", "<>"}:
            if not (
                left == right == "BOOL"
                or (left in _NUMERIC_CATEGORIES and right in _NUMERIC_CATEGORIES)
            ):
                self.fail("Comparison operands must have compatible types", expr.loc)
            return "BOOL"
        if expr.op in {"+", "-", "*", "/", "MOD", "<", "<=", ">", ">="}:
            category = "INTEGER" if expr.op == "MOD" else "NUMERIC"
            self.require(left, category, expr.left.loc)
            self.require(right, category, expr.right.loc)
            return "BOOL" if expr.op in {"<", "<=", ">", ">="} else numeric_type(left, right)
        self.fail(f"Unsupported binary operator {expr.op}", expr.loc)
        raise AssertionError("unreachable")

    def method_target(self, call: Call, pou: Pou) -> Pou | None:
        """Resolve instance dispatch without exposing methods as value fields."""
        receiver = None
        if isinstance(call.target, Member):
            receiver = call.target.base
            method_name = call.target.name
        elif isinstance(call.target, Reference):
            parts = call.target.parts
            method_name = parts[-1]
            if len(parts) > 1:
                receiver = Reference(parts[:-1], call.target.loc)
        else:
            return None
        if receiver is None:
            owner = pou.name if pou.kind == "FUNCTION_BLOCK" else pou.owner
            # Local storage shadows methods; globals are considered only after
            # the owner's method namespace has had a chance to resolve the call.
            if owner is None or method_name in self.variables[pou.name]:
                return None
            target = self.pous.method_for(owner, method_name)
        else:
            kind = self.reference(receiver, pou)
            target = (
                self.pous.interface_method_for(kind.name, method_name)
                if isinstance(kind, InterfaceType)
                else self.pous.method_for(kind, method_name)
                if isinstance(kind, str)
                else None
            )
        if target is None or target.kind != "METHOD":
            return None
        self.member_access(target, pou, call.loc)
        if isinstance(receiver, Super):
            self.pous.static_dispatch.add(id(call))
        self.pous.method_calls[id(call)] = receiver, target.name
        return target

    def action_target(self, call: Call, pou: Pou) -> Pou | None:
        """Resolve statement-only members independently of method-local storage."""
        receiver = None
        if isinstance(call.target, Member):
            receiver, name = call.target.base, call.target.name
        elif isinstance(call.target, Reference):
            name = call.target.parts[-1]
            if len(call.target.parts) > 1:
                receiver = Reference(call.target.parts[:-1], call.target.loc)
        else:
            return None
        if receiver is None:
            owner = self.pous.lexical_owner(pou)
            if owner is None or name in self.variables[pou.name]:
                return None
        else:
            owner = self.reference(receiver, pou)
        target = self.pous.action_for(owner, name) if isinstance(owner, str) else None
        if target is not None:
            self.pous.action_calls[id(call)] = receiver, target.name, owner
            if isinstance(receiver, Super):
                self.pous.static_dispatch.add(id(call))
        return target

    def call(self, call: Call, pou: Pou, *, as_expression: bool) -> TypeSpec:
        simple = isinstance(call.target, Reference) and len(call.target.parts) == 1
        name = call.target.parts[0] if simple else "instance"
        action = self.action_target(call, pou)
        target = action or self.method_target(call, pou)
        if action is not None:
            if as_expression:
                self.fail("Action cannot be used as an expression", call.loc)
            if (
                self.pous[self.pous.action_calls[id(call)][2]].kind == "PROGRAM"
                and pou.kind == "FUNCTION"
            ):
                self.fail("FUNCTION cannot directly call PROGRAM actions", call.loc)
        elif target is not None:
            if target.result_name == "FB_INIT":
                self.fail("Explicit FB_init calls are unsupported", call.loc)
            if as_expression and target.return_type is None:
                self.fail("Void method cannot be used as an expression", call.loc)
        elif simple and self.variable_binding(call.target, pou) is None:
            if name == "__ISVALIDREF":
                if len(call.arguments) != 1 or any(arg.name or arg.mode for arg in call.arguments):
                    self.fail("__ISVALIDREF requires one positional reference", call.loc)
                operand = call.arguments[0].value
                if not isinstance(operand, (Reference, Index, Member)) or not isinstance(
                    self.raw_reference(operand, pou), ReferenceType
                ):
                    self.fail("__ISVALIDREF requires a reference variable", operand.loc)
                self.pous.valid_reference_calls[id(call)] = operand
                return "BOOL"
            if name in _BOUND_OPERATORS:
                return self.bound_call(call, pou, name)
            if is_standard_function(name):
                try:
                    ordered = bind_arguments(name, call.arguments)
                    result = infer_result(
                        name, tuple(self.expression(arg.value, pou) for arg in ordered)
                    )
                except (TypeError, ValueError) as error:
                    self.fail(str(error), call.loc)
                self.pous.builtin_calls[id(call)] = result
                return result
            target = self.pous.get(name)
            if target is None:
                self.fail(f"Unknown call {name}", call.loc)
            if target.kind not in {"FUNCTION", "PROGRAM"}:
                self.fail("FUNCTION_BLOCK calls require an instance", call.loc)
            if target.kind == "PROGRAM" and pou.kind == "FUNCTION":
                self.fail("FUNCTION cannot directly call PROGRAM", call.loc)
        else:
            type_name = self.reference(call.target, pou)
            target = self.pous.get(type_name) if isinstance(type_name, str) else None
            if target is None or target.kind != "FUNCTION_BLOCK":
                self.fail(f"Call target {name} is not callable", call.loc)
        if isinstance(call.target, Super):
            self.pous.super_calls[id(call)] = target.name
        self.call_edge(pou, target, static=id(call) in self.pous.static_dispatch)
        if as_expression and target.kind not in {"FUNCTION", "METHOD"}:
            self.fail("FB and PROGRAM calls cannot be used as expressions", call.loc)
        parameter_owner = (
            self.pous[self.pous.action_calls[id(call)][2]] if action is not None else target
        )
        parameters = {
            var.name: var
            for var in self.pous.variables_for(parameter_owner)
            if var.section in {"VAR_INPUT", "VAR_OUTPUT", "VAR_IN_OUT"}
        }
        positional = [arg.name is None for arg in call.arguments]
        if any(positional) and not all(positional):
            self.fail("Cannot mix positional and named arguments", call.loc)
        if any(positional) and target.kind in {"FUNCTION_BLOCK", "PROGRAM", "ACTION"}:
            self.fail("FB and PROGRAM calls require named arguments", call.loc)
        ordered = [
            var
            for var in self.pous.variables_for(parameter_owner)
            if var.section in {"VAR_INPUT", "VAR_IN_OUT"}
        ]
        bound: set[str] = set()
        for index, arg in enumerate(call.arguments):
            if arg.name is None:
                if index >= len(ordered):
                    self.fail("Too many positional arguments", arg.loc)
                parameter = ordered[index]
            else:
                parameter = parameters.get(arg.name)
                if parameter is None:
                    self.fail(f"Unknown parameter {arg.name}", arg.loc)
            if parameter.name in bound:
                self.fail(f"Duplicate argument {parameter.name}", arg.loc)
            bound.add(parameter.name)
            expected_mode = "=>" if parameter.section == "VAR_OUTPUT" else ":="
            if arg.mode != ("" if arg.name is None else expected_mode):
                self.fail(f"Parameter {parameter.name} requires {expected_mode}", arg.loc)
            if parameter.section in {"VAR_IN_OUT", "VAR_OUTPUT"}:
                if not isinstance(arg.value, (Reference, Index, Member, BitAccess)):
                    self.fail(f"Parameter {parameter.name} requires a writable reference", arg.loc)
                actual = self.reference(arg.value, pou, writable=True)
                if parameter.section == "VAR_IN_OUT" and id(arg.value) in self.pous.bit_accesses:
                    self.fail("Bit locations cannot bind VAR_IN_OUT parameters", arg.loc)
                text_output = (
                    parameter.section == "VAR_OUTPUT"
                    and isinstance(canonical_type(actual), StringType)
                    and isinstance(canonical_type(parameter.type_name), StringType)
                )
                compatible = (
                    inout_compatible(parameter.type_name, actual)
                    if parameter.section == "VAR_IN_OUT"
                    else same_type(actual, parameter.type_name)
                )
                if not text_output and not compatible:
                    self.fail(
                        f"Parameter {parameter.name} requires exact type {parameter.type_name}",
                        arg.loc,
                    )
            elif isinstance(parameter.type_name, ReferenceType):
                self.reference_source(arg.value, parameter.type_name, pou)
            elif isinstance(parameter.type_name, InterfaceType):
                self.interface_source(arg.value, parameter.type_name, pou)
            else:
                self.require_value(arg.value, parameter.type_name, pou)
        receiver = self.pous.action_calls[id(call)][0] if action is not None else None
        local_action = action is not None and (
            receiver is None or isinstance(receiver, (This, Super))
        )
        for parameter in parameters.values():
            required = (parameter.section == "VAR_IN_OUT" and not local_action) or (
                parameter.section == "VAR_INPUT"
                and (
                    target.kind == "FUNCTION"
                    and not (
                        isinstance(parameter.type_name, ReferenceType)
                        and self.literal_zero(parameter.initial)
                    )
                    or (target.kind == "METHOD" and parameter.initial is None)
                )
            )
            if required and parameter.name not in bound:
                self.fail(f"Missing required parameter {parameter.name}", call.loc)
        return target.return_type or target.name

    def bound_call(self, call: Call, pou: Pou, name: str) -> TypeSpec:
        if len(call.arguments) != 2 or any(
            arg.name is not None or arg.mode for arg in call.arguments
        ):
            self.fail(f"{name} requires exactly two positional arguments", call.loc)
        array, dimension = (arg.value for arg in call.arguments)
        if not isinstance(array, (Reference, Index, Member)):
            self.fail(f"{name} requires an array storage location", array.loc)
        kind = canonical_type(self.reference(array, pou))
        if not isinstance(kind, (ArrayType, FBArrayType, InterfaceArrayType, OpenArrayType)):
            self.fail(f"{name} requires an array storage location", array.loc)
        self.require(self.expression(dimension, pou), "INTEGER", dimension.loc)
        self.pous.bound_calls[id(call)] = array, dimension, name == "UPPER_BOUND"
        return "DINT"

    def statements(self, body: tuple[Statement, ...], pou: Pou, loops: int) -> None:
        for statement in body:
            if isinstance(statement, RefAssign):
                target = self.raw_reference(statement.target, pou, writable=True)
                if not isinstance(target, ReferenceType):
                    self.fail("REF= requires a reference destination", statement.loc)
                self.reference_source(statement.value, target, pou)
            elif isinstance(statement, Assign):
                target = self.reference(statement.target, pou, writable=True, allow_property=True)
                if isinstance(target, InterfaceType):
                    self.interface_source(statement.value, target, pou)
                    continue
                if not is_value_type(target):
                    self.fail("Cannot assign an FB instance", statement.loc)
                self.require_value(statement.value, target, pou)
            elif isinstance(statement, CallStatement):
                self.call(statement.call, pou, as_expression=False)
            elif isinstance(statement, If):
                for condition, branch in statement.branches:
                    self.require(self.expression(condition, pou), "BOOL", condition.loc)
                    self.statements(branch, pou, loops)
                self.statements(statement.otherwise, pou, loops)
            elif isinstance(statement, Case):
                selector = canonical_type(self.expression(statement.selector, pou))
                if not isinstance(selector, EnumType):
                    self.require(selector, "INTEGER", statement.loc)
                seen: set[int] = set()
                for labels, branch in statement.arms:
                    for label in labels:
                        if isinstance(label, Reference):
                            value, actual = self.constant_expression(label, pou)
                            self.require(actual, selector, label.loc)
                            if isinstance(value, EnumValue):
                                self.pous.enum_values[id(label)] = value
                            key = (
                                value.value
                                if isinstance(value, EnumValue)
                                else checked_integer(value)
                            )
                        else:
                            if isinstance(selector, EnumType):
                                self.fail("Enum CASE requires qualified enum labels", statement.loc)
                            try:
                                key = checked_integer(label)
                            except (TypeError, ValueError) as exc:
                                self.fail(str(exc), statement.loc)
                        if key in seen:
                            self.fail(f"Duplicate CASE label {key}", statement.loc)
                        seen.add(key)
                    self.statements(branch, pou, loops)
                self.statements(statement.otherwise, pou, loops)
            elif isinstance(statement, For):
                self.require(
                    self.reference(statement.variable, pou, writable=True), "INTEGER", statement.loc
                )
                for expr in (statement.start, statement.stop, statement.step):
                    self.require(self.expression(expr, pou), "INTEGER", expr.loc)
                self.statements(statement.body, pou, loops + 1)
            elif isinstance(statement, While):
                self.require(self.expression(statement.condition, pou), "BOOL", statement.loc)
                self.statements(statement.body, pou, loops + 1)
            elif isinstance(statement, Exit):
                if loops == 0:
                    self.fail("EXIT is only valid inside a loop", statement.loc)
            elif not isinstance(statement, Return):
                self.fail("Unsupported statement", statement.loc)

    def reject_cycles(self, edges: dict[str, set[str]], description: str) -> None:
        done: set[str] = set()
        active: set[str] = set()

        def visit(name: str) -> None:
            if name in active:
                self.fail(
                    f"{description} cycle involving {name}",
                    self.pous[name.removeprefix("$INIT:")].loc,
                )
            if name in done:
                return
            active.add(name)
            for target in sorted(edges[name]):
                visit(target)
            active.remove(name)
            done.add(name)

        for name in edges:
            try:
                visit(name)
            except RecursionError as error:
                raise ValidationError(
                    f"{description} validation nesting limit exceeded",
                    self.pous[name.removeprefix("$INIT:")].loc,
                ) from error
