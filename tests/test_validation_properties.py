"""Properties are checked computations, never aliasable storage."""

import pytest

from tc_emulator import Runtime, ValidationError


def test_validated_property_read_observes_setter_result():
    rt = Runtime.from_source("""
    FUNCTION_BLOCK B
    VAR stored : INT; END_VAR
    PROPERTY P : INT GET P := stored; END_GET SET stored := P + 1; END_SET END_PROPERTY
    END_FUNCTION_BLOCK
    PROGRAM Main VAR b : B; n : INT; END_VAR b.P := 2; n := b.P; END_PROGRAM
    """)
    rt.scan("Main")
    assert rt.program_cell("Main", "n").value == 3


@pytest.mark.parametrize("body", ["P := THIS^.P;", "P := Q;"])
def test_implicit_accessor_recursion_is_rejected(body):
    with pytest.raises(ValidationError, match="Recursive call"):
        Runtime.from_source(f"""
        FUNCTION_BLOCK B
        PROPERTY P : INT GET {body} END_GET END_PROPERTY
        PROPERTY Q : INT GET Q := P; END_GET END_PROPERTY
        END_FUNCTION_BLOCK
        """)


@pytest.mark.parametrize(
    "statement", ["F(b.P);", "b.P.0 := TRUE;", "FOR b.P := 0 TO 2 DO END_FOR;"]
)
def test_properties_cannot_be_used_as_storage(statement):
    with pytest.raises(ValidationError, match="[Pp]ropert|storage"):
        Runtime.from_source(f"""
        FUNCTION F : INT VAR_IN_OUT x : INT; END_VAR END_FUNCTION
        FUNCTION_BLOCK B
        PROPERTY P : INT GET END_GET SET END_SET END_PROPERTY
        END_FUNCTION_BLOCK
        PROGRAM Main VAR b : B; END_VAR {statement} END_PROGRAM
        """)


def test_var_inst_containment_is_checked_without_invocation():
    with pytest.raises(ValidationError, match="containment"):
        Runtime.from_source("""
        FUNCTION_BLOCK B METHOD M VAR_INST child : B; END_VAR END_METHOD END_FUNCTION_BLOCK
        """)


@pytest.mark.parametrize("section", ["VAR_TEMP", "VAR_IN_OUT"])
@pytest.mark.parametrize("reference", ["x", "THIS^.x"])
def test_accessor_cannot_access_owner_transient_storage(section, reference):
    with pytest.raises(ValidationError, match=section):
        Runtime.from_source(f"""
        FUNCTION_BLOCK B {section} x : INT; END_VAR
        PROPERTY P : INT GET P := {reference}; END_GET END_PROPERTY
        END_FUNCTION_BLOCK
        """)


def test_this_grants_only_direct_owner_privacy_and_keeps_constants_readonly():
    for fields, body, message in [
        ("VAR child : C; END_VAR", "P := THIS^.child.hidden;", "Private"),
        ("VAR CONSTANT x : INT := 1; END_VAR", "THIS^.x := 2;", "writable"),
    ]:
        with pytest.raises(ValidationError, match=message):
            Runtime.from_source(f"""
            FUNCTION_BLOCK C VAR hidden : INT; END_VAR END_FUNCTION_BLOCK
            FUNCTION_BLOCK B {fields}
            PROPERTY P : INT GET {body} END_GET END_PROPERTY
            END_FUNCTION_BLOCK
            """)


@pytest.mark.parametrize("operation", ["n := b.P;", "b.P := 1;"])
def test_private_property_is_rejected_outside_lexical_owner(operation):
    with pytest.raises(ValidationError, match="[Pp]rivate"):
        Runtime.from_source(f"""
        FUNCTION_BLOCK B PROPERTY PRIVATE P : INT GET END_GET SET END_SET END_PROPERTY END_FUNCTION_BLOCK
        PROGRAM Main VAR b : B; n : INT; END_VAR {operation} END_PROGRAM
        """)


@pytest.mark.parametrize(
    "accessor,operation", [("GET END_GET", "b.P := 1;"), ("SET END_SET", "n := b.P;")]
)
def test_missing_accessor_rejected_statically(accessor, operation):
    with pytest.raises(ValidationError, match="accessor"):
        Runtime.from_source(f"""
        FUNCTION_BLOCK B PROPERTY P : INT {accessor} END_PROPERTY END_FUNCTION_BLOCK
        PROGRAM Main VAR b : B; n : INT; END_VAR {operation} END_PROGRAM
        """)


@pytest.mark.parametrize("kind", ["ARRAY[1..2] OF INT", "S", "Alias"])
def test_aggregate_property_types_are_rejected_even_through_alias(kind):
    with pytest.raises(ValidationError, match="Property type"):
        Runtime.from_source(f"""
        TYPE S : STRUCT n : INT; END_STRUCT; Alias : S; END_TYPE
        FUNCTION_BLOCK B PROPERTY P : {kind} GET END_GET END_PROPERTY END_FUNCTION_BLOCK
        """)


def test_property_is_not_output_connection_storage():
    with pytest.raises(ValidationError, match="Property.*storage"):
        Runtime.from_source("""
        FUNCTION F : INT VAR_OUTPUT n : INT; END_VAR END_FUNCTION
        FUNCTION_BLOCK B PROPERTY P : INT SET END_SET END_PROPERTY END_FUNCTION_BLOCK
        PROGRAM Main VAR b : B; END_VAR F(n => b.P); END_PROGRAM
        """)


@pytest.mark.parametrize(
    "declaration",
    [
        "VAR_INPUT N : INT; END_VAR VAR_INST x : INT := N; END_VAR",
        "VAR CONSTANT N : INT := 2; END_VAR VAR_INST x : INT := N; END_VAR",
        "VAR CONSTANT N : INT := 2; END_VAR VAR_INST x : ARRAY[1..N] OF INT; END_VAR",
        "VAR_INST N : INT := 2; x : INT := N; END_VAR",
    ],
)
def test_var_inst_initializer_and_bounds_cannot_see_method_locals(declaration):
    with pytest.raises(ValidationError, match="constant|reference"):
        Runtime.from_source(
            f"FUNCTION_BLOCK B METHOD M {declaration} END_METHOD END_FUNCTION_BLOCK"
        )


def test_indirect_var_inst_containment_and_expanded_limits_are_preflighted():
    with pytest.raises(ValidationError, match="containment"):
        Runtime.from_source("""
        FUNCTION_BLOCK B METHOD M VAR_INST child : C; END_VAR END_METHOD END_FUNCTION_BLOCK
        FUNCTION_BLOCK C METHOD M VAR_INST child : B; END_VAR END_METHOD END_FUNCTION_BLOCK
        """)
    for declaration, message in [
        ("children : ARRAY[1..10001] OF C;", "10000 FB"),
        ("data : ARRAY[1..1000000] OF INT; extra : INT;", "1000000 scalar"),
    ]:
        with pytest.raises(ValidationError, match=message):
            Runtime.from_source(f"""
            FUNCTION_BLOCK C END_FUNCTION_BLOCK
            FUNCTION_BLOCK B METHOD M VAR_INST {declaration} END_VAR END_METHOD END_FUNCTION_BLOCK
            """)


def test_method_instance_storage_is_private_to_its_method():
    for use in ["M := THIS^.n;", "M := Other.n;"]:
        with pytest.raises(ValidationError, match="Unknown"):
            Runtime.from_source(f"""
            FUNCTION_BLOCK B
            METHOD Other VAR_INST n : INT; END_VAR END_METHOD
            METHOD M : INT {use} END_METHOD
            END_FUNCTION_BLOCK
            """)


@pytest.mark.parametrize(
    "source",
    [
        "PROPERTY P : INT GET P := M(); END_GET END_PROPERTY METHOD M : INT M := P; END_METHOD",
        "PROPERTY P : INT GET THIS^.P := 1; END_GET SET P := THIS^.P; END_SET END_PROPERTY",
    ],
)
def test_cycles_crossing_accessors_and_methods_are_rejected(source):
    with pytest.raises(ValidationError, match="Recursive call"):
        Runtime.from_source(f"FUNCTION_BLOCK B {source} END_FUNCTION_BLOCK")


@pytest.mark.parametrize(
    "type_name,header",
    [
        ("STRING(N)", ""),
        ("INT", "VAR value : INT := N; END_VAR"),
        ("INT", "VAR values : ARRAY[1..N] OF INT; END_VAR"),
        ("INT", "VAR CONSTANT K : INT := N; END_VAR"),
    ],
)
def test_property_declaration_cannot_capture_getter_only_constant(type_name, header):
    with pytest.raises(ValidationError, match="constant|reference") as error:
        Runtime.from_source(
            f"""
        FUNCTION_BLOCK B
        PROPERTY P : {type_name}
        {header}
        GET VAR CONSTANT N : INT := 2; END_VAR END_GET
        END_PROPERTY
        END_FUNCTION_BLOCK
        """,
            source="property-scope.st",
        )
    assert error.value.loc.source == "property-scope.st"
    assert error.value.loc.line in (3, 4)


def test_property_header_dependency_cycle_is_rejected_before_allocating_defaults():
    with pytest.raises(ValidationError, match="Constant dependency cycle"):
        Runtime.from_source("""
        FUNCTION_BLOCK B
        VAR CONSTANT N : INT := 5; END_VAR
        PROPERTY P : INT
        VAR CONSTANT K : INT := Other; Other : INT := K; END_VAR
        VAR values : ARRAY[1..1000000] OF INT; END_VAR
        GET VAR CONSTANT N : INT := 2; END_VAR END_GET
        END_PROPERTY
        END_FUNCTION_BLOCK
        """)
