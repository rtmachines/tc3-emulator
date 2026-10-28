"""Inherited interface contracts preserve nominal references and lexical owners."""

import pytest

from tc_emulator import ArgumentError, ParseError, Runtime, ValidationError
from tc_emulator.parser import parse
from tc_emulator.syntax import InterfaceDecl, Location


def test_interface_positional_constructor_keeps_empty_bases():
    assert InterfaceDecl("I", (), (), Location("old.st", 1, 1)).extends == ()


def test_interface_multiple_bases_are_normalized_in_source_order():
    interface = parse("INTERFACE I extends i_a, I_b END_INTERFACE").interfaces[0]
    assert interface.extends == ("I_A", "I_B")


@pytest.mark.parametrize("header", ["EXTENDS", "EXTENDS I,", "EXTENDS I, i", "EXTENDS I EXTENDS J"])
def test_interface_rejects_malformed_or_duplicate_bases(header):
    with pytest.raises(ParseError):
        parse(f"INTERFACE D {header} END_INTERFACE")


BASE = """
INTERFACE I_Base
METHOD Add : INT VAR_INPUT amount : INT := 2; END_VAR END_METHOD
PROPERTY Value : INT GET END_GET SET END_SET END_PROPERTY
END_INTERFACE
"""
DIAMOND = """
INTERFACE I_Left EXTENDS I_Base END_INTERFACE
INTERFACE I_Right EXTENDS I_Base END_INTERFACE
INTERFACE I_Derived EXTENDS I_Left, I_Right
METHOD Extra : INT END_METHOD
END_INTERFACE
"""
IMPLEMENTATION = """
FUNCTION_BLOCK Device IMPLEMENTS I_Derived
VAR n : INT; END_VAR
METHOD Add : INT VAR_INPUT amount : INT := 2; END_VAR
n := n + amount * 10; Add := n; END_METHOD
METHOD Extra : INT Extra := 99; END_METHOD
PROPERTY Value : INT GET Value := n; END_GET SET n := Value; END_SET END_PROPERTY
END_FUNCTION_BLOCK
"""


def test_diamond_upcast_preserves_identity_and_function_input():
    rt = Runtime.from_source(
        BASE
        + DIAMOND
        + IMPLEMENTATION
        + """
    FUNCTION Use : INT VAR_INPUT ref : I_Base; END_VAR Use := ref.Value; END_FUNCTION
    PROGRAM Main VAR device : Device; derived : I_Derived; base : I_Base;
    first, second, third : INT; END_VAR
    derived := device; base := derived;
    first := base.Add(); base.Value := 7; second := derived.Add(); third := Use(derived);
    END_PROGRAM
    """
    )
    rt.scan("Main")
    assert [rt.program_cell("Main", n).value for n in ("first", "second", "third")] == [20, 27, 27]
    registry = rt._registry
    assert registry.interface_ancestors["I_DERIVED"] == frozenset(
        {"I_DERIVED", "I_LEFT", "I_RIGHT", "I_BASE"}
    )
    assert registry.interface_method_for("I_DERIVED", "ADD").owner == "I_BASE"
    assert registry.properties["I_DERIVED", "VALUE"].getter.owner == "I_BASE"
    assert len(registry.interfaces["I_DERIVED"].methods) == 1


def test_upcast_during_fb_init_and_python_base_input_uses_dynamic_override():
    rt = Runtime.from_source(
        BASE
        + DIAMOND
        + IMPLEMENTATION
        + """
    FUNCTION_BLOCK Faster EXTENDS Device
    METHOD Add : INT VAR_INPUT amount : INT := 2; END_VAR
    n := n + amount * 100; Add := n; END_METHOD END_FUNCTION_BLOCK
    FUNCTION_BLOCK Holder
    VAR saved : I_Base; END_VAR
    METHOD FB_init : BOOL
    VAR_INPUT bInitRetains : BOOL; bInCopyCode : BOOL; target : I_Base; END_VAR
    saved := target; END_METHOD
    METHOD Read : INT Read := saved.Add(); END_METHOD END_FUNCTION_BLOCK
    FUNCTION Build : INT VAR_INPUT ref : I_Derived; END_VAR
    VAR holder : Holder(target := ref); END_VAR Build := holder.Read(); END_FUNCTION
    """
    )
    device = rt.instantiate("Faster")
    assert rt.call("Build", ref=device).value == 200
    holder = rt.instantiate("Holder", init={"target": device})
    assert holder.call_method("Read").value == 400


@pytest.mark.parametrize("order", [(0, 1, 2), (2, 1, 0), (1, 0, 2)])
def test_forward_bases_and_identical_sibling_local_contracts(order):
    parts = [
        "INTERFACE A METHOD M : Count VAR_INPUT x : INT := 1 + 1; END_VAR END_METHOD END_INTERFACE",
        "INTERFACE B METHOD M : INT VAR_INPUT x : Count := 2; END_VAR END_METHOD END_INTERFACE",
        "INTERFACE C EXTENDS A, B METHOD M : INT VAR_INPUT x : INT := 2; END_VAR END_METHOD END_INTERFACE",
    ]
    rt = Runtime.from_source(
        "TYPE Count : INT; END_TYPE "
        + " ".join(parts[i] for i in order)
        + """
    FUNCTION_BLOCK F IMPLEMENTS C
    METHOD M : INT VAR_INPUT x : INT := 2; END_VAR M := x; END_METHOD END_FUNCTION_BLOCK
    FUNCTION Use : INT VAR_INPUT ref : C; END_VAR Use := ref.M(); END_FUNCTION
    """
    )
    assert rt.call("Use", ref=rt.instantiate("F")).value == 2


@pytest.mark.parametrize(
    "source",
    [
        "INTERFACE I EXTENDS Missing END_INTERFACE",
        "FUNCTION_BLOCK F END_FUNCTION_BLOCK INTERFACE I EXTENDS F END_INTERFACE",
        "TYPE T : INT; END_TYPE INTERFACE I EXTENDS T END_INTERFACE",
        "INTERFACE I EXTENDS I END_INTERFACE",
        "INTERFACE I EXTENDS J END_INTERFACE INTERFACE J EXTENDS I END_INTERFACE",
    ],
)
def test_unused_invalid_base_graph_raises_validation_error(source):
    with pytest.raises(ValidationError):
        Runtime.from_source(source)


@pytest.mark.parametrize(
    "changed",
    [
        "METHOD M : DINT VAR_INPUT x : INT := 2; END_VAR END_METHOD",
        "METHOD M : INT VAR_INPUT y : INT := 2; END_VAR END_METHOD",
        "METHOD M : INT VAR_OUTPUT x : INT; END_VAR END_METHOD",
        "METHOD M : INT VAR_INPUT x : DINT := 2; END_VAR END_METHOD",
        "METHOD M : INT VAR_INPUT x : INT := 3; END_VAR END_METHOD",
        "METHOD M : INT VAR_INPUT x : INT; END_VAR END_METHOD",
        "PROPERTY M : INT GET END_GET END_PROPERTY",
    ],
)
@pytest.mark.parametrize("local", [False, True])
def test_conflicting_method_contracts_fail_without_implementer(changed, local):
    first = "INTERFACE A METHOD M : INT VAR_INPUT x : INT := 2; END_VAR END_METHOD END_INTERFACE"
    other = (
        f"INTERFACE B EXTENDS A {changed} END_INTERFACE"
        if local
        else f"INTERFACE B {changed} END_INTERFACE INTERFACE C EXTENDS A, B END_INTERFACE"
    )
    with pytest.raises(ValidationError):
        Runtime.from_source(first + " " + other)


@pytest.mark.parametrize(
    "other",
    [
        "PROPERTY P : DINT GET END_GET END_PROPERTY",
        "PROPERTY P : INT SET END_SET END_PROPERTY",
        "PROPERTY P : INT GET END_GET SET END_SET END_PROPERTY",
        "METHOD P : INT END_METHOD",
    ],
)
def test_conflicting_property_contracts_do_not_combine_accessors(other):
    with pytest.raises(ValidationError):
        Runtime.from_source(f"""
        INTERFACE A PROPERTY P : INT GET END_GET END_PROPERTY END_INTERFACE
        INTERFACE B {other} END_INTERFACE INTERFACE C EXTENDS A, B END_INTERFACE
        """)


def test_identical_properties_and_global_lexical_defaults_coalesce():
    rt = Runtime.from_source("""
    VAR_GLOBAL CONSTANT N : INT := 4; END_VAR
    INTERFACE A METHOD M : INT VAR_INPUT x : INT := N; END_VAR END_METHOD
    PROPERTY P : STRING(N) GET END_GET END_PROPERTY END_INTERFACE
    INTERFACE B METHOD M : INT VAR_INPUT x : INT := 4; END_VAR END_METHOD
    PROPERTY P : STRING(4) GET END_GET END_PROPERTY END_INTERFACE
    INTERFACE C EXTENDS A, B END_INTERFACE
    FUNCTION_BLOCK F IMPLEMENTS C VAR CONSTANT N : INT := 9; END_VAR
    METHOD M : INT VAR_INPUT x : INT := 4; END_VAR M := x; END_METHOD
    PROPERTY P : STRING(4) GET P := 'abcde'; END_GET END_PROPERTY END_FUNCTION_BLOCK
    FUNCTION Use : INT VAR_INPUT ref : C; END_VAR Use := ref.M(); END_FUNCTION
    """)
    assert rt.call("Use", ref=rt.instantiate("F")).value == 4


@pytest.mark.parametrize("member", ["", "METHOD PROTECTED M END_METHOD"])
def test_inherited_contract_requires_public_implementation(member):
    with pytest.raises(ValidationError):
        Runtime.from_source(f"""
        INTERFACE A METHOD M END_METHOD END_INTERFACE INTERFACE B EXTENDS A END_INTERFACE
        FUNCTION_BLOCK F IMPLEMENTS B {member} END_FUNCTION_BLOCK
        """)


@pytest.mark.parametrize(
    "statement",
    [
        "derived := base;",
        "derived := sibling;",
        "result := Use(base);",
        "result := Use(sibling);",
        "result := base.Extra();",
        "result := base = derived;",
        "base := FALSE;",
        "base := 0 + 0;",
    ],
)
def test_no_downcast_sibling_conversion_or_base_contract_widening(statement):
    with pytest.raises(ValidationError):
        Runtime.from_source(
            BASE
            + DIAMOND
            + IMPLEMENTATION
            + f"""
        INTERFACE I_Sibling EXTENDS I_Base END_INTERFACE
        FUNCTION Use : INT VAR_INPUT ref : I_Derived; END_VAR Use := ref.Extra(); END_FUNCTION
        PROGRAM Main VAR derived : I_Derived; base : I_Base; sibling : I_Sibling;
        result : INT; END_VAR {statement} END_PROGRAM
        """
        )


@pytest.mark.parametrize(
    "member,body",
    [
        ("METHOD M END_METHOD", "METHOD M ref.M(); END_METHOD"),
        (
            "PROPERTY P : INT GET END_GET END_PROPERTY",
            "PROPERTY P : INT GET P := ref.P; END_GET END_PROPERTY",
        ),
        (
            "PROPERTY P : INT SET END_SET END_PROPERTY",
            "PROPERTY P : INT SET ref.P := P; END_SET END_PROPERTY",
        ),
    ],
)
def test_base_callgraph_includes_unused_derived_implementers(member, body):
    with pytest.raises(ValidationError, match="Recursive call"):
        Runtime.from_source(f"""
        INTERFACE A {member} END_INTERFACE INTERFACE B EXTENDS A END_INTERFACE
        VAR_GLOBAL ref : A; END_VAR
        FUNCTION_BLOCK Unused IMPLEMENTS B {body} END_FUNCTION_BLOCK
        """)


def test_implementer_ancestry_excludes_unrelated_function_blocks():
    rt = Runtime.from_source("""
    INTERFACE A END_INTERFACE INTERFACE B EXTENDS A END_INTERFACE
    FUNCTION_BLOCK F IMPLEMENTS B END_FUNCTION_BLOCK
    FUNCTION_BLOCK Child EXTENDS F END_FUNCTION_BLOCK
    FUNCTION_BLOCK Other END_FUNCTION_BLOCK
    FUNCTION Use : BOOL VAR_INPUT ref : A; END_VAR Use := ref <> 0; END_FUNCTION
    """)
    assert rt.call("Use", ref=rt.instantiate("Child")).value is True
    assert rt._registry.implementers["A"] == {"F", "CHILD"}
    with pytest.raises(ArgumentError):
        rt.call("Use", ref=rt.instantiate("Other"))


@pytest.mark.parametrize("reverse", [False, True])
def test_identical_inherited_siblings_work_without_local_redeclaration(reverse):
    parts = [
        "INTERFACE A METHOD M : INT END_METHOD END_INTERFACE",
        "INTERFACE B METHOD M : INT END_METHOD END_INTERFACE",
        "INTERFACE C EXTENDS A, B END_INTERFACE",
    ]
    if reverse:
        parts.reverse()
    rt = Runtime.from_source(
        " ".join(parts)
        + """
    FUNCTION_BLOCK F IMPLEMENTS C METHOD M : INT M := 7; END_METHOD END_FUNCTION_BLOCK
    FUNCTION Use : INT VAR_INPUT ref : C; END_VAR Use := ref.M(); END_FUNCTION
    """
    )
    assert rt.call("Use", ref=rt.instantiate("F")).value == 7


@pytest.mark.parametrize(
    "other",
    [
        "PROPERTY P : DINT GET END_GET END_PROPERTY",
        "PROPERTY P : INT SET END_SET END_PROPERTY",
        "PROPERTY P : INT GET END_GET SET END_SET END_PROPERTY",
    ],
)
def test_local_property_redeclaration_must_match_inherited_accessor_set(other):
    with pytest.raises(ValidationError):
        Runtime.from_source(f"""
        INTERFACE A PROPERTY P : INT GET END_GET END_PROPERTY END_INTERFACE
        INTERFACE B EXTENDS A {other} END_INTERFACE
        """)


@pytest.mark.parametrize("different", ["I_Child", "E2", "STRING(5)", "S2"])
def test_inherited_signatures_keep_nominal_identity_and_no_interface_covariance(different):
    expected = {"I_Child": "I_Parent", "E2": "E1", "STRING(5)": "STRING(4)", "S2": "S1"}[different]
    with pytest.raises(ValidationError):
        Runtime.from_source(f"""
        TYPE E1 : (One); E2 : (One); S1 : STRUCT n : INT; END_STRUCT;
        S2 : STRUCT n : INT; END_STRUCT; END_TYPE
        INTERFACE I_Parent END_INTERFACE INTERFACE I_Child EXTENDS I_Parent END_INTERFACE
        INTERFACE A METHOD M VAR_INPUT x : {expected}; END_VAR END_METHOD END_INTERFACE
        INTERFACE B EXTENDS A METHOD M VAR_INPUT x : {different}; END_VAR END_METHOD END_INTERFACE
        """)


def test_duplicate_bases_are_validated_for_programmatic_ast():
    from dataclasses import replace

    from tc_emulator.validation import validate

    program = parse("INTERFACE A END_INTERFACE INTERFACE B EXTENDS A END_INTERFACE")
    base, derived = program.interfaces
    with pytest.raises(ValidationError, match="Duplicate"):
        validate(replace(program, interfaces=(base, replace(derived, extends=("A", "A")))))


def test_deep_interface_chain_does_not_recurse_on_python_stack():
    source = "INTERFACE I0 METHOD M : INT END_METHOD END_INTERFACE\n"
    source += "\n".join(f"INTERFACE I{i} EXTENDS I{i - 1} END_INTERFACE" for i in range(1, 1050))
    rt = Runtime.from_source(source)
    assert rt._registry.interface_method_for("I1049", "M").name == "I0.M"
    assert len(rt._registry.interface_ancestors["I1049"]) == 1050
