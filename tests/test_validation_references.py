"""Addressability and exact-type rules for data references."""

import pytest

from tc_emulator import Runtime, ValidationError


@pytest.mark.parametrize("statement", ["r REF= n;", "r REF= 1;", "r REF= TRUE;", "r REF= n + 1;"])
def test_binding_requires_exact_addressable_type(statement):
    with pytest.raises(ValidationError):
        Runtime.from_source(
            f"PROGRAM Main VAR r : REFERENCE TO INT; n : DINT; END_VAR {statement} END_PROGRAM"
        )


@pytest.mark.parametrize("section", ["VAR_OUTPUT", "VAR_IN_OUT", "VAR CONSTANT"])
def test_reference_storage_sections_are_bounded(section):
    with pytest.raises(ValidationError):
        Runtime.from_source(
            f"FUNCTION_BLOCK B {section} r : REFERENCE TO INT := 0; END_VAR END_FUNCTION_BLOCK"
        )


@pytest.mark.parametrize(
    "expected,target",
    [
        ("INT", "DINT"),
        ("STRING(4)", "STRING(8)"),
        ("ARRAY[1..2] OF INT", "ARRAY[0..1] OF INT"),
        ("Config", "Other"),
    ],
)
def test_binding_preserves_storage_type_capacity_bounds_and_nominal_identity(expected, target):
    with pytest.raises(ValidationError, match="exact type"):
        Runtime.from_source(f"""
        TYPE Config : STRUCT x : INT; END_STRUCT; Other : STRUCT x : INT; END_STRUCT END_TYPE
        PROGRAM Main VAR r : REFERENCE TO {expected}; x : {target}; END_VAR r REF= x; END_PROGRAM
        """)


@pytest.mark.parametrize(
    "declaration",
    [
        "FUNCTION F : REFERENCE TO INT END_FUNCTION",
        "FUNCTION_BLOCK B PROPERTY P : REFERENCE TO INT GET END_GET END_PROPERTY END_FUNCTION_BLOCK",
        "FUNCTION_BLOCK B VAR r : REFERENCE TO B; END_VAR END_FUNCTION_BLOCK",
        "INTERFACE I END_INTERFACE FUNCTION_BLOCK B VAR r : REFERENCE TO I; END_VAR END_FUNCTION_BLOCK",
        "FUNCTION_BLOCK B VAR r : REFERENCE TO REFERENCE TO INT; END_VAR END_FUNCTION_BLOCK",
        "FUNCTION_BLOCK B VAR r : REFERENCE TO ARRAY[*] OF INT; END_VAR END_FUNCTION_BLOCK",
        "TYPE R : REFERENCE TO INT; END_TYPE",
        "TYPE S : STRUCT r : REFERENCE TO INT; END_STRUCT END_TYPE",
    ],
)
def test_unsupported_reference_shapes_rejected(declaration):
    with pytest.raises(ValidationError):
        Runtime.from_source(declaration)


@pytest.mark.parametrize(
    "declaration,statement",
    [
        ("VAR CONSTANT x : INT := 1; END_VAR", "r REF= x;"),
        ("VAR x : WORD; END_VAR", "r REF= x.0;"),
        ("VAR x : INT; END_VAR", "x REF= r;"),
        ("", "r REF= F();"),
    ],
)
def test_readonly_bits_ordinary_destinations_and_call_results_rejected(declaration, statement):
    with pytest.raises(ValidationError):
        Runtime.from_source(f"""
        FUNCTION F : INT F := 1; END_FUNCTION
        PROGRAM Main VAR r : REFERENCE TO INT; END_VAR {declaration} {statement} END_PROGRAM
        """)


@pytest.mark.parametrize(
    "source",
    [
        "PROGRAM Main VAR r : REFERENCE TO INT := other; other : REFERENCE TO INT; END_VAR END_PROGRAM",
        "PROGRAM Main VAR r : REFERENCE TO INT := a[i]; a : ARRAY[1..2] OF INT; i : INT := 1; END_VAR END_PROGRAM",
        "FUNCTION_BLOCK B VAR r : REFERENCE TO INT := temp; END_VAR VAR_TEMP temp : INT; END_VAR END_FUNCTION_BLOCK",
        "FUNCTION_BLOCK B VAR r : REFERENCE TO INT := arg; END_VAR VAR_IN_OUT arg : INT; END_VAR END_FUNCTION_BLOCK",
        "FUNCTION_BLOCK B METHOD M VAR x : INT; END_VAR VAR_INST r : REFERENCE TO INT := x; END_VAR END_METHOD END_FUNCTION_BLOCK",
        "FUNCTION F : INT VAR_INPUT r : REFERENCE TO INT := x; END_VAR VAR x : INT; END_VAR END_FUNCTION",
    ],
)
def test_initializer_paths_are_direct_constant_and_lifetime_safe(source):
    with pytest.raises(ValidationError):
        Runtime.from_source(source)


@pytest.mark.parametrize(
    "expression",
    [
        "__ISVALIDREF(0)",
        "__ISVALIDREF(x)",
        "__ISVALIDREF()",
        "__ISVALIDREF(r, r)",
        "__ISVALIDREF(r := r)",
    ],
)
def test_validity_operator_requires_one_reference_location(expression):
    with pytest.raises(ValidationError):
        Runtime.from_source(
            f"FUNCTION F : BOOL VAR x : INT; r : REFERENCE TO INT; END_VAR F := {expression}; END_FUNCTION"
        )


def test_reference_to_property_is_not_addressable():
    with pytest.raises(ValidationError, match="addressable"):
        Runtime.from_source("""
        FUNCTION_BLOCK B
        PROPERTY P : INT GET P := 1; END_GET SET END_SET END_PROPERTY
        END_FUNCTION_BLOCK
        PROGRAM Main VAR b : B; r : REFERENCE TO INT; END_VAR r REF= b.P; END_PROGRAM
        """)


def test_reference_input_omission_rejected_statically():
    with pytest.raises(ValidationError, match="Missing required"):
        Runtime.from_source(
            "FUNCTION F : INT VAR_INPUT r : REFERENCE TO INT; END_VAR END_FUNCTION PROGRAM Main F(); END_PROGRAM"
        )


def test_var_inst_initializer_cannot_capture_method_result_storage():
    with pytest.raises(ValidationError, match="invocation storage"):
        Runtime.from_source("""
        FUNCTION_BLOCK B METHOD M : INT
        VAR_INST ref : REFERENCE TO INT := M; END_VAR
        END_METHOD END_FUNCTION_BLOCK
        """)
