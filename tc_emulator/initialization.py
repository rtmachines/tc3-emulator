"""Checked metadata for the new-instance lifecycle profile."""

from __future__ import annotations

from typing import TYPE_CHECKING

from . import syntax as st
from .types import FBArrayType, InterfaceType, ReferenceType, same_type

if TYPE_CHECKING:
    from .validation import _Validator

SetupEntries = tuple[tuple[str, st.Expr], ...]
InstanceSetup = tuple[SetupEntries, SetupEntries]


def parameters(pou: st.Pou) -> tuple[st.VarDecl, ...]:
    return tuple(v for v in pou.variables if v.section in {"VAR_INPUT", "VAR_OUTPUT", "VAR_IN_OUT"})


def initialization_contracts(v: _Validator) -> None:
    for pou in v.pous.values():
        if pou.call_after_init and pou.kind not in {"FUNCTION_BLOCK", "METHOD"}:
            v.fail("call_after_init requires FUNCTION_BLOCK or METHOD", pou.loc)
        if pou.kind != "FUNCTION_BLOCK":
            continue
        lineage = v.pous.lineages.get(pou.name, (pou.name,))
        if any(v.pous[base].call_after_init for base in lineage[:-1]) and not pou.call_after_init:
            v.fail("Descendants must retain call_after_init", pou.loc)
        initializers = []
        hooks = {}
        for owner in lineage:
            for raw in v.pous[owner].methods:
                method = v.pous[raw.name]
                formal = parameters(method)
                if method.result_name == "FB_INIT":
                    valid = method.access == "PUBLIC" and same_type(method.return_type, "BOOL")
                    valid = (
                        valid
                        and len(formal) >= 2
                        and all(
                            var.name == name
                            and var.section == "VAR_INPUT"
                            and same_type(var.type_name, "BOOL")
                            and var.initial is None
                            and var.default is None
                            for var, name in zip(formal, ("BINITRETAINS", "BINCOPYCODE"))
                        )
                    )
                    valid = valid and all(var.section == "VAR_INPUT" for var in formal)
                    if not valid:
                        v.fail(
                            "Invalid lifecycle FB_init signature: PUBLIC BOOL and system BOOL inputs required",
                            method.loc,
                        )
                    if method.call_after_init:
                        v.fail("Lifecycle method cannot carry call_after_init", method.loc)
                    initializers.append(method)
                if method.call_after_init:
                    if not v.pous[owner].call_after_init:
                        v.fail("call_after_init method requires a marked owner", method.loc)
                    if formal:
                        v.fail("call_after_init hook cannot have formal parameters", method.loc)
                    hooks[method.result_name] = method
        v.pous.initialization_methods[pou.name] = tuple(initializers)
        v.pous.initialization_hooks[pou.name] = tuple(hooks.values())


def initialization_declarations(v: _Validator, pou: st.Pou) -> None:
    for var in pou.variables:
        kind = var.type_name
        name = kind.element_type if isinstance(kind, FBArrayType) else kind
        target = v.pous.get(name) if isinstance(name, str) else None
        if target is None or target.kind != "FUNCTION_BLOCK":
            continue
        size = kind.size if isinstance(kind, FBArrayType) else 1
        if var.element_init_arguments is not None:
            if not isinstance(kind, FBArrayType) or var.init_arguments is not None:
                v.fail("Per-element initialization requires an FB array", var.loc)
            argument_lists = var.element_init_arguments
            if len(argument_lists) != size:
                v.fail("Per-element initialization must cover every array element", var.loc)
        else:
            argument_lists = (var.init_arguments or (),) * size
        if var.initial is None:
            post_values = (None,) * size
        elif isinstance(kind, FBArrayType):
            if not isinstance(var.initial, st.ArrayInitializer):
                v.fail("FB array post-init values require an array initializer", var.loc)
            if sum(item.count for item in var.initial.items) != size:
                v.fail("FB array post-init values must cover every element", var.loc)
            post_values = tuple(item.value for item in var.initial.items for _ in range(item.count))
        else:
            post_values = (var.initial,)
        methods = v.pous.initialization_methods.get(name, ())
        formal = parameters(methods[-1])[2:] if methods else ()
        scope = v.declaration_scope(pou, var)
        visible = {
            name
            for name, item in v.variables[scope.name].items()
            if var.section != "VAR_INST" or item.section == "VAR_INST"
        }
        if (
            var.section != "VAR_INST"
            and scope.return_type is not None
            and scope.kind in {"FUNCTION", "METHOD", "PROPERTY_GET", "PROPERTY_SET"}
        ):
            visible.add(scope.result_name)
        setups = []
        for arguments, post in zip(argument_lists, post_values):
            named = [arg.name is not None for arg in arguments]
            if any(named) and not all(named):
                v.fail("Cannot mix positional and named initialization arguments", var.loc)
            bound = {}
            for index, arg in enumerate(arguments):
                parameter = (
                    next((p for p in formal if p.name == arg.name), None)
                    if arg.name is not None
                    else formal[index]
                    if index < len(formal)
                    else None
                )
                if parameter is None:
                    v.fail("Unknown or too many initialization arguments", arg.loc)
                if parameter.name in bound:
                    v.fail(f"Duplicate initialization argument {parameter.name}", arg.loc)
                if arg.mode != (":=" if arg.name is not None else ""):
                    v.fail("Initialization arguments require :=", arg.loc)
                scoped_setup_expression(v, arg.value, parameter.type_name, pou, var)
                bound[parameter.name] = arg.value
            for parameter in formal:
                if parameter.name not in bound and parameter.initial is None:
                    v.fail(f"Missing required initialization parameter {parameter.name}", var.loc)
            posts = []
            if post is not None:
                if not isinstance(post, st.StructInitializer):
                    v.fail("FB post-init values require named input/property assignments", post.loc)
                seen = set()
                for field, expr in post.fields:
                    if field in seen:
                        v.fail(f"Duplicate post-init assignment {field}", post.loc)
                    seen.add(field)
                    parameter = next(
                        (
                            p
                            for p in v.pous.variables_for(target)
                            if p.name == field and p.section == "VAR_INPUT" and not p.constant
                        ),
                        None,
                    )
                    prop = v.pous.properties.get((name, field))
                    if parameter is not None:
                        expected = parameter.type_name
                    elif (
                        prop is not None
                        and prop.access == "PUBLIC"
                        and prop.setter is not None
                        and prop.setter.access == "PUBLIC"
                    ):
                        expected = prop.type_name
                    else:
                        v.fail(
                            f"Unknown writable public post-init input/property {field}", post.loc
                        )
                    scoped_setup_expression(v, expr, expected, pou, var)
                    posts.append((field, expr))
            setups.append((tuple(bound.items()), tuple(posts)))
        v.pous.instance_initializers[pou.name, var.name] = tuple(setups)
        v.pous.initialization_scopes[pou.name, var.name] = scope, frozenset(visible)


def scoped_setup_expression(
    v: _Validator, expr: st.Expr, expected, pou: st.Pou, var: st.VarDecl
) -> None:
    """Use resolved types while retaining the declaration's lexical visibility."""
    scope = v.declaration_scope(pou, var)
    original = v.variables[scope.name]
    if var.section == "VAR_INST":
        v.variables[scope.name] = {
            name: item for name, item in original.items() if item.section == "VAR_INST"
        }
    else:
        # PROPERTY headers are copied into both accessors. Keep header names
        # only, but take their resolved declarations from the current accessor.
        v.variables[scope.name] = {name: v.variables[pou.name][name] for name in original}
    try:
        setup_expression(v, expr, expected, scope, var)
    finally:
        v.variables[scope.name] = original


def setup_expression(
    v: _Validator, expr: st.Expr, expected, scope: st.Pou, var: st.VarDecl
) -> None:
    """Allow constants and direct storage, keeping setup free of implicit user calls."""
    persistent = var.section == "VAR_INST" or (
        scope.kind in {"FUNCTION_BLOCK", "PROGRAM", "GVL"} and var.section != "VAR_TEMP"
    )

    def check_storage(owner, target, loc):
        if persistent and (
            target.section in {"VAR_TEMP", "VAR_IN_OUT"}
            or owner.kind in {"FUNCTION", "METHOD", "PROPERTY_GET", "PROPERTY_SET"}
            and target.section != "VAR_INST"
        ):
            v.fail("Persistent initialization cannot capture invocation storage", loc)

    def inspect(node):
        if isinstance(node, st.Call):
            v.fail("Calls are unsupported in declaration initialization expressions", node.loc)
        if isinstance(node, (st.Reference, st.Index, st.Member, st.BitAccess)):
            if v.property_target(node, scope) is not None:
                v.fail(
                    "Property reads are unsupported in declaration initialization expressions",
                    node.loc,
                )
            if isinstance(node, st.Reference):
                binding = v.variable_binding(node, scope)
                if binding is not None:
                    owner, target, _ = binding
                    check_storage(owner, target, node.loc)
                elif (
                    persistent
                    and scope.kind in {"FUNCTION", "METHOD", "PROPERTY_GET", "PROPERTY_SET"}
                    and node.parts[0] == scope.result_name
                ):
                    v.fail("Persistent initialization cannot capture invocation storage", node.loc)
            elif isinstance(node, st.Index):
                inspect(node.base)
                for index in node.indices:
                    inspect(index)
            elif isinstance(node, st.Member) and isinstance(node.base, (st.This, st.Super)):
                owner = v.reference(node.base, scope)
                binding = v.fb_variable(owner, node.name)
                if binding is not None:
                    check_storage(binding[0], binding[1], node.loc)
            else:
                inspect(node.base)
        elif isinstance(node, st.Unary):
            inspect(node.operand)
        elif isinstance(node, st.Binary):
            inspect(node.left)
            inspect(node.right)
        elif not isinstance(node, (st.Literal, st.This, st.Super)):
            v.fail("Unsupported declaration initialization expression", node.loc)

    inspect(expr)
    if isinstance(expected, ReferenceType):
        v.reference_source(expr, expected, scope)
    elif isinstance(expected, InterfaceType):
        v.interface_source(expr, expected, scope)
    else:
        v.require(v.expression(expr, scope), expected, expr.loc)


def initialization_edges(v: _Validator) -> None:
    """Keep construction separate from body invocation when detecting recursion."""
    for name, pou in v.pous.items():
        if pou.kind == "FUNCTION_BLOCK":
            node = f"$INIT:{name}"
            v.calls[node] = {
                method.name
                for method in (
                    *v.pous.initialization_methods.get(name, ()),
                    *v.pous.initialization_hooks.get(name, ()),
                )
            }
    for pou in v.pous.values():
        declaration = v.pous[pou.owner] if pou.kind == "ACTION" else pou
        for var in v.pous.variables_for(declaration):
            if pou.kind == "ACTION" and var.section != "VAR_TEMP":
                continue
            kind = var.type_name
            target = kind.element_type if isinstance(kind, FBArrayType) else kind
            if not isinstance(target, str) or f"$INIT:{target}" not in v.calls:
                continue
            if var.section == "VAR_INST":
                callers = [
                    f"$INIT:{owner}"
                    for owner, lineage in v.pous.lineages.items()
                    if pou.owner in lineage
                ]
            elif pou.kind == "FUNCTION_BLOCK" and var.section != "VAR_TEMP":
                callers = [f"$INIT:{pou.name}"]
            else:
                callers = [pou.name]
            declaration_owner = (
                v.fb_variable(declaration.name, var.name)[0].name
                if declaration.kind == "FUNCTION_BLOCK"
                else declaration.name
            )
            for caller in callers:
                v.calls[caller].add(f"$INIT:{target}")
                for setup in v.pous.instance_initializers.get((declaration_owner, var.name), ()):
                    for field, _ in setup[1]:
                        prop = v.pous.properties.get((target, field))
                        if prop is not None:
                            v.calls[caller].add(prop.setter.name)
