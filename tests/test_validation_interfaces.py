"""Interface contracts are exact and remain outside value semantics."""

import pytest

from tc_emulator import ParseError, Runtime, ValidationError


@pytest.mark.parametrize(
    "implementation",
    [
        "",
        "METHOD M : INT END_METHOD",
        "METHOD PRIVATE M : INT VAR_INPUT x : INT := 2; END_VAR END_METHOD",
        "METHOD M : DINT VAR_INPUT x : INT := 2; END_VAR END_METHOD",
        "METHOD M : INT VAR_INPUT y : INT := 2; END_VAR END_METHOD",
        "METHOD M : INT VAR_INPUT x : INT := 3; END_VAR END_METHOD",
        "METHOD M : INT VAR_INPUT x : INT; END_VAR END_METHOD",
    ],
)
def test_contract_rejects_missing_private_or_inexact_method(implementation):
    with pytest.raises(ValidationError):
        Runtime.from_source(f"""
        INTERFACE I METHOD M : INT VAR_INPUT x : INT := 2; END_VAR END_METHOD END_INTERFACE
        FUNCTION_BLOCK B IMPLEMENTS I {implementation} END_FUNCTION_BLOCK
        """)


def test_contract_resolves_aliases_defaults_and_forward_names():
    Runtime.from_source("""
    FUNCTION_BLOCK B IMPLEMENTS I
    METHOD M : Count VAR_INPUT x : INT := 1 + 1; END_VAR M := x; END_METHOD
    END_FUNCTION_BLOCK
    TYPE Count : INT; END_TYPE
    INTERFACE I METHOD M : INT VAR_INPUT x : Count := 2; END_VAR END_METHOD END_INTERFACE
    """)


@pytest.mark.parametrize(
    "storage",
    [
        "VAR CONSTANT ref : I := 0; END_VAR",
        "VAR_OUTPUT ref : I; END_VAR",
        "VAR_IN_OUT ref : I; END_VAR",
        "VAR ref : ARRAY[1..2] OF I; END_VAR",
        "VAR ref : I := 1; END_VAR",
        "VAR ref : I := FALSE; END_VAR",
        "VAR ref : I := -0; END_VAR",
        "VAR ref : I := 0 + 0; END_VAR",
    ],
)
def test_interface_nonvalue_storage_restrictions(storage):
    with pytest.raises(ValidationError):
        Runtime.from_source(
            f"INTERFACE I END_INTERFACE FUNCTION_BLOCK B {storage} END_FUNCTION_BLOCK"
        )


@pytest.mark.parametrize(
    "declaration",
    [
        "TYPE Alias : I; END_TYPE",
        "TYPE Box : STRUCT member : I; END_STRUCT; END_TYPE",
        "FUNCTION F : I END_FUNCTION",
        "FUNCTION_BLOCK B PROPERTY P : I GET END_GET END_PROPERTY END_FUNCTION_BLOCK",
    ],
)
def test_interfaces_cannot_be_value_types(declaration):
    with pytest.raises(ValidationError):
        Runtime.from_source("INTERFACE I END_INTERFACE " + declaration)


@pytest.mark.parametrize(
    "body",
    [
        "r := s;",
        "r := wrong;",
        "r := 1;",
        "r := FALSE;",
        "r := 0 + 0;",
        "r := SEL(TRUE, a, a);",
        "IF r THEN END_IF;",
        "ok := r = s;",
        "ok := r <> 1;",
        "ok := r = FALSE;",
        "a := r;",
        "r.hidden();",
        "r.private();",
        "r.P := 1;",
        "ok := __ISVALIDREF(r);",
    ],
)
def test_nominal_assignments_null_comparisons_and_contract_visibility(body):
    with pytest.raises(ValidationError):
        Runtime.from_source(f"""
        INTERFACE I PROPERTY P : INT GET END_GET END_PROPERTY END_INTERFACE
        INTERFACE J END_INTERFACE
        FUNCTION_BLOCK A IMPLEMENTS I, J
        METHOD Hidden END_METHOD
        METHOD PRIVATE Private END_METHOD
        PROPERTY P : INT GET END_GET SET END_SET END_PROPERTY
        END_FUNCTION_BLOCK
        FUNCTION_BLOCK Other END_FUNCTION_BLOCK
        PROGRAM Main VAR a : A; wrong : Other; r : I; s : J; ok : BOOL; END_VAR
        {body}
        END_PROGRAM
        """)


@pytest.mark.parametrize(
    "members",
    [
        "METHOD M : INT M := 1; END_METHOD",
        "METHOD PRIVATE M END_METHOD",
        "METHOD M VAR x : INT; END_VAR END_METHOD",
        "METHOD M VAR_INST x : INT; END_VAR END_METHOD",
        "METHOD M VAR CONSTANT x : INT := 1; END_VAR END_METHOD",
        "METHOD M VAR_OUTPUT x : INT := 1; END_VAR END_METHOD",
        "METHOD M VAR_IN_OUT ref : I; END_VAR END_METHOD",
        "PROPERTY P : INT GET P := 1; END_GET END_PROPERTY",
        "PROPERTY P : INT GET PRIVATE END_GET END_PROPERTY",
        "PROPERTY P : INT VAR x : INT; END_VAR GET END_GET END_PROPERTY",
    ],
)
def test_unused_prototypes_are_validated_strictly(members):
    with pytest.raises((ParseError, ValidationError)):
        Runtime.from_source(f"INTERFACE I {members} END_INTERFACE")


@pytest.mark.parametrize(
    "implementation",
    [
        "PROPERTY P : DINT GET END_GET END_PROPERTY",
        "PROPERTY P : INT SET END_SET END_PROPERTY",
        "PROPERTY PRIVATE P : INT GET END_GET END_PROPERTY",
        "PROPERTY P : INT GET PRIVATE END_GET END_PROPERTY",
    ],
)
def test_exact_property_contract(implementation):
    with pytest.raises(ValidationError):
        Runtime.from_source(f"""
        INTERFACE I PROPERTY P : INT GET END_GET END_PROPERTY END_INTERFACE
        FUNCTION_BLOCK B IMPLEMENTS I {implementation} END_FUNCTION_BLOCK
        """)


def test_interface_defaults_and_property_bounds_use_global_declaration_scope():
    Runtime.from_source("""
    VAR_GLOBAL CONSTANT N : INT := 4; END_VAR
    INTERFACE I
    METHOD M : INT VAR_INPUT x : INT := N; END_VAR END_METHOD
    PROPERTY P : STRING(N) GET END_GET END_PROPERTY
    END_INTERFACE
    FUNCTION_BLOCK B IMPLEMENTS I
    VAR CONSTANT N : INT := 9; END_VAR
    METHOD M : INT VAR_INPUT x : INT := 4; END_VAR END_METHOD
    PROPERTY P : STRING(4) GET VAR CONSTANT N : INT := 2; END_VAR END_GET END_PROPERTY
    END_FUNCTION_BLOCK
    """)


@pytest.mark.parametrize("actual", ["STRING(5)", "DINT", "E2", "S2"])
def test_contract_preserves_string_capacity_and_nominal_enum_struct_identity(actual):
    expected = {"STRING(5)": "STRING(4)", "DINT": "INT", "E2": "E1", "S2": "S1"}[actual]
    with pytest.raises(ValidationError):
        Runtime.from_source(f"""
        TYPE E1 : (A, B); E2 : (A, B); S1 : STRUCT x : INT; END_STRUCT; S2 : STRUCT x : INT; END_STRUCT; END_TYPE
        INTERFACE I METHOD M VAR_INPUT x : {expected}; END_VAR END_METHOD END_INTERFACE
        FUNCTION_BLOCK B IMPLEMENTS I METHOD M VAR_INPUT x : {actual}; END_VAR END_METHOD END_FUNCTION_BLOCK
        """)


def test_conservative_dynamic_callgraph_rejects_unreachable_implementation_cycle():
    with pytest.raises(ValidationError, match="Recursive call"):
        Runtime.from_source("""
        INTERFACE I METHOD M END_METHOD END_INTERFACE
        VAR_GLOBAL r : I; END_VAR
        FUNCTION_BLOCK Safe IMPLEMENTS I METHOD M END_METHOD END_FUNCTION_BLOCK
        FUNCTION_BLOCK Unreachable IMPLEMENTS I METHOD M r.M(); END_METHOD END_FUNCTION_BLOCK
        PROGRAM Main VAR a : Safe; END_VAR r := a; r.M(); END_PROGRAM
        """)


def test_multiple_contracts_and_reference_inputs_with_optional_null():
    rt = Runtime.from_source("""
    INTERFACE I METHOD Bind VAR_INPUT other : I := 0; END_VAR END_METHOD END_INTERFACE
    INTERFACE J PROPERTY P : INT GET END_GET END_PROPERTY END_INTERFACE
    FUNCTION_BLOCK B IMPLEMENTS I, J
    VAR held : I; END_VAR
    METHOD Bind VAR_INPUT other : I := 0; END_VAR held := other; END_METHOD
    PROPERTY P : INT GET P := 3; END_GET END_PROPERTY
    END_FUNCTION_BLOCK
    PROGRAM Main VAR b : B; r : I; j : J; n : INT; END_VAR
    r := b; j := b; r.Bind(); r.Bind(b); n := j.P;
    END_PROGRAM
    """)
    rt.scan("Main")
    assert rt.program_cell("Main", "n").value == 3


@pytest.mark.parametrize(
    "extra",
    [
        "INTERFACE I END_INTERFACE",
        "FUNCTION_BLOCK I END_FUNCTION_BLOCK",
        "TYPE I : INT; END_TYPE",
        "VAR_GLOBAL x : INT; END_VAR",
    ],
)
def test_interface_namespace_collisions(extra):
    name = "GVL" if extra.startswith("VAR_GLOBAL") else "I"
    with pytest.raises(ValidationError):
        Runtime.from_source(f"INTERFACE {name} END_INTERFACE " + extra)


@pytest.mark.parametrize("interface", ["TON", "INT", "MAX", "LOWER_BOUND"])
def test_interface_reserved_names(interface):
    with pytest.raises((ValidationError, ParseError)):
        Runtime.from_source(f"INTERFACE {interface} END_INTERFACE")


@pytest.mark.parametrize("accessor,body", [("GET", "P := r.P;"), ("SET", "r.P := P;")])
def test_conservative_property_dispatch_cycle(accessor, body):
    with pytest.raises(ValidationError, match="Recursive call"):
        Runtime.from_source(f"""
        INTERFACE I PROPERTY P : INT {accessor} END_{accessor} END_PROPERTY END_INTERFACE
        VAR_GLOBAL r : I; END_VAR
        FUNCTION_BLOCK B IMPLEMENTS I PROPERTY P : INT {accessor} {body} END_{accessor}
        END_PROPERTY END_FUNCTION_BLOCK
        """)


def test_owned_interface_slots_count_toward_expanded_scalar_budget():
    names = ", ".join(f"r{i}" for i in range(100))
    with pytest.raises(ValidationError, match="1000000 scalar leaf"):
        Runtime.from_source(f"""
        INTERFACE I END_INTERFACE
        FUNCTION_BLOCK Leaf VAR {names} : I; END_VAR END_FUNCTION_BLOCK
        PROGRAM Main VAR leaves : ARRAY[1..10000] OF Leaf; one : INT; END_VAR END_PROGRAM
        """)


def test_unused_interface_open_array_return_is_rejected():
    with pytest.raises(ValidationError):
        Runtime.from_source("INTERFACE I METHOD M : ARRAY[*] OF INT END_METHOD END_INTERFACE")
