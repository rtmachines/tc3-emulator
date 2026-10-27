"""Inheritance contracts are checked before any persistent instance is allocated."""

from dataclasses import replace

import pytest

from tc_emulator import Runtime, ValidationError
from tc_emulator.parser import parse
from tc_emulator.validation import validate


@pytest.mark.parametrize(
    "source",
    [
        "FUNCTION_BLOCK B EXTENDS Missing END_FUNCTION_BLOCK",
        "FUNCTION_BLOCK B EXTENDS TON END_FUNCTION_BLOCK",
        "FUNCTION F : INT END_FUNCTION FUNCTION_BLOCK B EXTENDS F END_FUNCTION_BLOCK",
        "PROGRAM P END_PROGRAM FUNCTION_BLOCK B EXTENDS P END_FUNCTION_BLOCK",
        "FUNCTION_BLOCK B EXTENDS B END_FUNCTION_BLOCK",
        "FUNCTION_BLOCK B EXTENDS C END_FUNCTION_BLOCK FUNCTION_BLOCK C EXTENDS B END_FUNCTION_BLOCK",
    ],
)
def test_invalid_bases_are_rejected(source):
    with pytest.raises(ValidationError, match="base|inherit|EXTENDS"):
        Runtime.from_source(source)


@pytest.mark.parametrize(
    "base,derived",
    [
        ("VAR n : INT; END_VAR", "VAR n : INT; END_VAR"),
        ("VAR_TEMP n : INT; END_VAR", "VAR n : INT; END_VAR"),
        ("METHOD M END_METHOD", "VAR M : INT; END_VAR"),
        ("VAR M : INT; END_VAR", "METHOD M END_METHOD"),
        ("METHOD M END_METHOD", "PROPERTY M : INT GET END_GET END_PROPERTY"),
        ("METHOD PRIVATE M END_METHOD", "METHOD PRIVATE M END_METHOD"),
    ],
)
def test_inherited_name_collisions_are_rejected(base, derived):
    with pytest.raises(ValidationError, match="collision|override|PRIVATE"):
        Runtime.from_source(
            f"FUNCTION_BLOCK A {base} END_FUNCTION_BLOCK "
            f"FUNCTION_BLOCK B EXTENDS A {derived} END_FUNCTION_BLOCK"
        )


@pytest.mark.parametrize(
    "derived",
    [
        "METHOD M : DINT VAR_INPUT x : INT := 2; END_VAR END_METHOD",
        "METHOD M : INT VAR_INPUT y : INT := 2; END_VAR END_METHOD",
        "METHOD M : INT VAR_INPUT x : DINT := 2; END_VAR END_METHOD",
        "METHOD M : INT VAR_INPUT x : INT; END_VAR END_METHOD",
        "METHOD M : INT VAR_INPUT x : INT := 3; END_VAR END_METHOD",
        "METHOD M : INT VAR_OUTPUT x : INT; END_VAR END_METHOD",
        "METHOD PROTECTED M : INT VAR_INPUT x : INT := 2; END_VAR END_METHOD",
    ],
)
def test_override_method_contract_must_match(derived):
    with pytest.raises(ValidationError, match="Override|override"):
        Runtime.from_source(
            "FUNCTION_BLOCK A METHOD M : INT VAR_INPUT x : INT := 2; END_VAR END_METHOD "
            f"END_FUNCTION_BLOCK FUNCTION_BLOCK B EXTENDS A {derived} END_FUNCTION_BLOCK"
        )


@pytest.mark.parametrize(
    "derived",
    [
        "PROPERTY P : DINT GET END_GET SET END_SET END_PROPERTY",
        "PROPERTY P : INT GET END_GET END_PROPERTY",
        "PROPERTY PROTECTED P : INT GET END_GET SET END_SET END_PROPERTY",
        "PROPERTY P : INT GET END_GET SET PRIVATE END_SET END_PROPERTY",
    ],
)
def test_override_property_contract_must_match(derived):
    with pytest.raises(ValidationError, match="Override|override"):
        Runtime.from_source(
            "FUNCTION_BLOCK A PROPERTY P : INT GET END_GET SET END_SET END_PROPERTY "
            f"END_FUNCTION_BLOCK FUNCTION_BLOCK B EXTENDS A {derived} END_FUNCTION_BLOCK"
        )


@pytest.mark.parametrize(
    "body",
    ["SUPER^();", "SUPER^.M();", "THIS^.P := SUPER^.P;"],
)
def test_super_requires_a_lexical_base(body):
    with pytest.raises(ValidationError, match="SUPER"):
        Runtime.from_source(
            f"FUNCTION_BLOCK B VAR_OUTPUT P : INT; END_VAR {body} END_FUNCTION_BLOCK"
        )


def test_explicit_ast_extends_on_non_fb_is_rejected():
    program = parse("FUNCTION F : INT END_FUNCTION")
    program = replace(program, pous=(replace(program.pous[0], extends="F"),))
    with pytest.raises(ValidationError, match="EXTENDS"):
        validate(program)


@pytest.mark.parametrize("access", ["PRIVATE", "PROTECTED"])
def test_external_st_cannot_call_restricted_inherited_members(access):
    with pytest.raises(ValidationError, match="inaccessible"):
        Runtime.from_source(f"""
        FUNCTION_BLOCK A METHOD {access} M END_METHOD END_FUNCTION_BLOCK
        FUNCTION_BLOCK B EXTENDS A END_FUNCTION_BLOCK
        PROGRAM Main VAR b : B; END_VAR b.M(); END_PROGRAM
        """)


def test_inherited_containment_cycle_is_rejected():
    with pytest.raises(ValidationError, match="containment"):
        Runtime.from_source("""
        FUNCTION_BLOCK A VAR child : B; END_VAR END_FUNCTION_BLOCK
        FUNCTION_BLOCK B EXTENDS A END_FUNCTION_BLOCK
        """)


def test_ancestor_method_banks_contribute_to_aggregate_storage_limit():
    with pytest.raises(ValidationError, match="1000000 scalar"):
        Runtime.from_source("""
        FUNCTION_BLOCK A METHOD M VAR_INST n : ARRAY[1..600000] OF INT; END_VAR
        END_METHOD END_FUNCTION_BLOCK
        FUNCTION_BLOCK B EXTENDS A METHOD M
        VAR_INST n : ARRAY[1..600000] OF INT; END_VAR END_METHOD END_FUNCTION_BLOCK
        """)


def test_virtual_recursion_through_base_hook_is_rejected():
    with pytest.raises(ValidationError, match="Recursive call"):
        Runtime.from_source("""
        FUNCTION_BLOCK A
        METHOD Run Hook(); END_METHOD METHOD Hook END_METHOD END_FUNCTION_BLOCK
        FUNCTION_BLOCK B EXTENDS A METHOD Hook Run(); END_METHOD END_FUNCTION_BLOCK
        """)


@pytest.mark.parametrize("use", ["n := hidden;", "n := THIS^.hidden;", "n := SUPER^.hidden;"])
def test_ancestor_var_temp_is_not_visible_in_derived_body(use):
    with pytest.raises(ValidationError, match="Unknown|VAR_TEMP"):
        Runtime.from_source(f"""
        FUNCTION_BLOCK A VAR_TEMP hidden : INT; END_VAR END_FUNCTION_BLOCK
        FUNCTION_BLOCK B EXTENDS A VAR_OUTPUT n : INT; END_VAR {use} END_FUNCTION_BLOCK
        """)


@pytest.mark.parametrize("use", ["SUPER^ := 0;", "n := SUPER^;", "ref := SUPER^;"])
def test_super_cannot_be_used_as_a_value_or_assignment_target(use):
    with pytest.raises(ValidationError):
        Runtime.from_source(f"""
        INTERFACE I METHOD M END_METHOD END_INTERFACE
        FUNCTION_BLOCK A IMPLEMENTS I METHOD M END_METHOD END_FUNCTION_BLOCK
        FUNCTION_BLOCK B EXTENDS A VAR n : INT; ref : I; END_VAR {use} END_FUNCTION_BLOCK
        """)


@pytest.mark.parametrize(
    "member", ["METHOD M END_METHOD", "PROPERTY P : INT GET END_GET END_PROPERTY"]
)
def test_descendant_cannot_access_inherited_private_member(member):
    declaration = member.replace("METHOD M", "METHOD PRIVATE M").replace(
        "PROPERTY P", "PROPERTY PRIVATE P"
    )
    use = "M();" if member.startswith("METHOD") else "n := P;"
    with pytest.raises(ValidationError, match="inaccessible"):
        Runtime.from_source(f"""
        FUNCTION_BLOCK A {declaration} END_FUNCTION_BLOCK
        FUNCTION_BLOCK B EXTENDS A VAR_OUTPUT n : INT; END_VAR {use} END_FUNCTION_BLOCK
        """)


def test_inherited_var_inst_fb_containment_is_checked():
    with pytest.raises(ValidationError, match="containment"):
        Runtime.from_source("""
        FUNCTION_BLOCK A METHOD M VAR_INST child : B; END_VAR END_METHOD END_FUNCTION_BLOCK
        FUNCTION_BLOCK B EXTENDS A END_FUNCTION_BLOCK
        """)


def test_interface_contract_implemented_by_an_ancestor_requires_matching_override():
    with pytest.raises(ValidationError, match="Override|override"):
        Runtime.from_source("""
        INTERFACE I METHOD M : INT END_METHOD END_INTERFACE
        FUNCTION_BLOCK A IMPLEMENTS I METHOD M : INT M := 1; END_METHOD END_FUNCTION_BLOCK
        FUNCTION_BLOCK B EXTENDS A METHOD M : DINT M := 2; END_METHOD END_FUNCTION_BLOCK
        """)


@pytest.mark.parametrize("member", ["M", "P"])
def test_protected_methods_and_properties_are_accessible_in_descendants_only(member):
    source = """
    FUNCTION_BLOCK A
    METHOD PROTECTED M : INT M := 2; END_METHOD
    PROPERTY PROTECTED P : INT GET P := 3; END_GET SET END_SET END_PROPERTY
    END_FUNCTION_BLOCK
    FUNCTION_BLOCK B EXTENDS A METHOD Run : INT Run := M() + P; END_METHOD END_FUNCTION_BLOCK
    """
    assert Runtime.from_source(source).instantiate("B").call_method("Run").value == 5
    use = "b.M()" if member == "M" else "b.P"
    with pytest.raises(ValidationError, match="inaccessible"):
        Runtime.from_source(
            source + f"PROGRAM Main VAR b : B; n : INT; END_VAR n := {use}; END_PROGRAM"
        )


def test_explicit_ast_accessor_cannot_widen_protected_property_access():
    program = parse(
        "FUNCTION_BLOCK A PROPERTY PROTECTED P : INT GET END_GET END_PROPERTY END_FUNCTION_BLOCK"
    )
    owner = program.pous[0]
    prop = owner.properties[0]
    prop = replace(prop, getter=replace(prop.getter, access="PUBLIC"))
    program = replace(program, pous=(replace(owner, properties=(prop,)),))
    with pytest.raises(ValidationError, match="accessor"):
        validate(program)


def test_interface_prototype_ast_cannot_carry_extends():
    program = parse("INTERFACE I METHOD M END_METHOD END_INTERFACE")
    interface = program.interfaces[0]
    interface = replace(interface, methods=(replace(interface.methods[0], extends="A"),))
    with pytest.raises(ValidationError, match="declaration-only"):
        validate(replace(program, interfaces=(interface,)))


@pytest.mark.parametrize("base_section", ["VAR", "VAR_TEMP"])
def test_ancestor_body_storage_and_derived_storage_share_the_leaf_budget(base_section):
    with pytest.raises(ValidationError, match="1000000 scalar"):
        Runtime.from_source(f"""
        FUNCTION_BLOCK A {base_section} large : ARRAY[1..999999] OF INT; END_VAR END_FUNCTION_BLOCK
        FUNCTION_BLOCK B EXTENDS A VAR x, y : INT; END_VAR SUPER^(); END_FUNCTION_BLOCK
        """)
