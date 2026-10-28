"""Lifecycle contracts are checked even for unused function blocks."""

import subprocess
import sys

import pytest

from tc_emulator import ValidationError
from tc_emulator.parser import parse
from tc_emulator.validation import validate

FLAGS = "VAR_INPUT bInitRetains : BOOL; bInCopyCode : BOOL; END_VAR"


def check(source):
    return validate(parse(source, "initialization.st"))


@pytest.mark.parametrize(
    "declaration",
    [
        "METHOD PRIVATE FB_init : BOOL " + FLAGS,
        "METHOD FB_init : INT " + FLAGS,
        "METHOD FB_init : BOOL VAR_INPUT wrong : BOOL; bInCopyCode : BOOL; END_VAR",
        "METHOD FB_init : BOOL VAR_INPUT bInitRetains : BOOL := TRUE; bInCopyCode : BOOL; END_VAR",
        "METHOD FB_init : BOOL VAR_INPUT bInitRetains : INT; bInCopyCode : BOOL; END_VAR",
        "METHOD FB_init : BOOL " + FLAGS + " VAR_OUTPUT out : INT; END_VAR",
        "METHOD FB_init : BOOL " + FLAGS + " VAR_IN_OUT n : INT; END_VAR",
    ],
)
def test_invalid_lifecycle_signature_is_rejected_in_unused_fb(declaration):
    with pytest.raises(ValidationError, match="FB_init signature") as caught:
        check(f"FUNCTION_BLOCK B {declaration} END_METHOD END_FUNCTION_BLOCK")
    assert caught.value.loc.source == "initialization.st"


@pytest.mark.parametrize(
    "extra",
    [
        "VAR_INPUT n : DINT := 1; END_VAR",
        "VAR_INPUT renamed : INT := 1; END_VAR",
        "VAR_INPUT n : INT := 2; END_VAR",
        "",
    ],
)
def test_derived_init_must_preserve_complete_base_prefix(extra):
    with pytest.raises(ValidationError, match="Override contract"):
        check(f"""FUNCTION_BLOCK A METHOD FB_init : BOOL {FLAGS}
        VAR_INPUT n : INT := 1; END_VAR END_METHOD END_FUNCTION_BLOCK
        FUNCTION_BLOCK B EXTENDS A METHOD FB_init : BOOL {FLAGS} {extra}
        END_METHOD END_FUNCTION_BLOCK""")


@pytest.mark.parametrize(
    "source",
    [
        "FUNCTION_BLOCK B {attribute 'call_after_init'} METHOD Hook END_METHOD END_FUNCTION_BLOCK",
        "{attribute 'call_after_init'} FUNCTION_BLOCK A END_FUNCTION_BLOCK FUNCTION_BLOCK B EXTENDS A END_FUNCTION_BLOCK",
        "{attribute 'call_after_init'} FUNCTION_BLOCK B {attribute 'call_after_init'} METHOD Hook VAR_INPUT n : INT; END_VAR END_METHOD END_FUNCTION_BLOCK",
        "{attribute 'call_after_init'} FUNCTION_BLOCK B {attribute 'call_after_init'} METHOD FB_init : BOOL "
        + FLAGS
        + " END_METHOD END_FUNCTION_BLOCK",
        "{attribute 'call_after_init'} FUNCTION_BLOCK A {attribute 'call_after_init'} METHOD Hook END_METHOD END_FUNCTION_BLOCK {attribute 'call_after_init'} FUNCTION_BLOCK B EXTENDS A METHOD Hook END_METHOD END_FUNCTION_BLOCK",
    ],
)
def test_invalid_hook_markers_are_rejected(source):
    with pytest.raises(ValidationError):
        check(source)


@pytest.mark.parametrize(
    "arguments",
    [
        "",
        "typo := 1",
        "n := 1, n := 2",
        "1, n := 2",
        "bInitRetains := TRUE, n := 1",
        "TRUE",
        "1, 2",
    ],
)
def test_declaration_constructor_arguments_are_checked(arguments):
    with pytest.raises(ValidationError):
        check(f"""FUNCTION_BLOCK B METHOD FB_init : BOOL {FLAGS}
        VAR_INPUT n : INT; END_VAR END_METHOD END_FUNCTION_BLOCK
        PROGRAM P VAR b : B({arguments}); END_VAR END_PROGRAM""")


@pytest.mark.parametrize(
    "declaration",
    [
        "b : ARRAY[1..2] OF B[(1)];",
        "b : ARRAY[1..2] OF B(1) := [(n := 1)];",
        "b : B(1) := (hidden := 1);",
        "b : B(1) := (out := 1);",
        "b : B(1) := (ReadOnly := 1);",
        "b : B(1) := (n := TRUE);",
        "b : B(1) := (n := 1, n := 2);",
        "value : INT(1);",
    ],
)
def test_array_coverage_and_public_post_init_targets_are_checked(declaration):
    with pytest.raises(ValidationError):
        check(f"""FUNCTION_BLOCK B VAR hidden : INT; END_VAR VAR_INPUT n : INT; END_VAR
        VAR_OUTPUT out : INT; END_VAR METHOD FB_init : BOOL {FLAGS}
        VAR_INPUT value : INT; END_VAR END_METHOD
        PROPERTY ReadOnly : INT GET ReadOnly := 1; END_GET END_PROPERTY
        END_FUNCTION_BLOCK PROGRAM P VAR {declaration} END_VAR END_PROGRAM""")


@pytest.mark.parametrize(
    "call", ["FB_init(TRUE, FALSE)", "THIS^.FB_init(TRUE, FALSE)", "SUPER^.FB_init(TRUE, FALSE)"]
)
def test_explicit_lifecycle_calls_in_st_are_rejected(call):
    with pytest.raises(ValidationError, match="Explicit FB_init"):
        check(f"""FUNCTION_BLOCK A METHOD FB_init : BOOL {FLAGS}
        END_METHOD END_FUNCTION_BLOCK FUNCTION_BLOCK B EXTENDS A {call}; END_FUNCTION_BLOCK""")


@pytest.mark.parametrize("expression", ["F()", "reader.Value"])
def test_side_effecting_declaration_expressions_are_rejected(expression):
    with pytest.raises(ValidationError, match="declaration initialization expressions"):
        check(f"""FUNCTION F : INT F := 1; END_FUNCTION
        FUNCTION_BLOCK R PROPERTY Value : INT GET Value := 1; END_GET END_PROPERTY END_FUNCTION_BLOCK
        FUNCTION_BLOCK B METHOD FB_init : BOOL {FLAGS} VAR_INPUT n : INT; END_VAR END_METHOD END_FUNCTION_BLOCK
        PROGRAM P VAR reader : R; b : B({expression}); END_VAR END_PROGRAM""")


def test_implicit_constructor_function_local_fb_cycle_is_rejected():
    with pytest.raises(ValidationError, match="Recursive call cycle"):
        check(f"""FUNCTION_BLOCK B METHOD FB_init : BOOL {FLAGS} F(); END_METHOD END_FUNCTION_BLOCK
        FUNCTION F : INT VAR b : B; END_VAR F := 1; END_FUNCTION""")


@pytest.mark.parametrize("section", ["VAR_TEMP", "VAR_IN_OUT"])
def test_persistent_constructor_arguments_cannot_capture_transient_storage(section):
    with pytest.raises(ValidationError, match="invocation storage"):
        check(f"""FUNCTION_BLOCK B METHOD FB_init : BOOL {FLAGS}
        VAR_INPUT ref : REFERENCE TO INT; END_VAR END_METHOD END_FUNCTION_BLOCK
        FUNCTION_BLOCK A {section} value : INT; END_VAR VAR b : B(value); END_VAR END_FUNCTION_BLOCK""")


def test_hook_function_local_fb_construction_cycle_is_rejected():
    with pytest.raises(ValidationError, match="Recursive call cycle"):
        check("""{attribute 'call_after_init'} FUNCTION_BLOCK B
        {attribute 'call_after_init'} METHOD Hook F(); END_METHOD END_FUNCTION_BLOCK
        FUNCTION F : INT VAR b : B; END_VAR F := 1; END_FUNCTION""")


def test_method_bank_construction_cycle_is_rejected_before_allocation():
    with pytest.raises(ValidationError, match="cycle"):
        check("""FUNCTION_BLOCK B METHOD M VAR_INST b : B; END_VAR END_METHOD END_FUNCTION_BLOCK""")


@pytest.mark.parametrize("section", ["VAR_TEMP", "VAR_IN_OUT"])
def test_persistent_constructor_cannot_capture_explicit_this_transient(section):
    with pytest.raises(ValidationError, match="invocation storage"):
        check(f"""FUNCTION_BLOCK B METHOD FB_init : BOOL {FLAGS}
        VAR_INPUT ref : REFERENCE TO INT; END_VAR END_METHOD END_FUNCTION_BLOCK
        FUNCTION_BLOCK A {section} value : INT; END_VAR
        VAR b : B(THIS^.value); END_VAR END_FUNCTION_BLOCK""")


def test_oversized_fb_post_initializer_repeat_is_rejected_before_expansion():
    source = """FUNCTION_BLOCK B VAR_INPUT input : INT; END_VAR END_FUNCTION_BLOCK
    PROGRAM P VAR b : ARRAY[1..1] OF B := [1000000000000((input := 1))]; END_VAR END_PROGRAM"""
    # Bound the subprocess so a regression cannot consume the test runner's memory.
    script = f"""
import resource
from tc_emulator import Runtime, ValidationError
resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024, 256 * 1024 * 1024))
try:
    Runtime.from_source({source!r})
except ValidationError:
    pass
else:
    raise AssertionError('oversized initializer accepted')
"""
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, timeout=5
    )
    assert result.returncode == 0, result.stderr


def test_inherited_post_init_setter_cycle_is_rejected_before_execution():
    with pytest.raises(ValidationError, match="Recursive call cycle"):
        check("""FUNCTION_BLOCK Leaf
        PROPERTY P : INT SET F(); END_SET END_PROPERTY END_FUNCTION_BLOCK
        FUNCTION_BLOCK A VAR child : Leaf := (P := 1); END_VAR END_FUNCTION_BLOCK
        FUNCTION_BLOCK B EXTENDS A END_FUNCTION_BLOCK
        FUNCTION F : INT VAR b : B; END_VAR F := 1; END_FUNCTION""")


@pytest.mark.parametrize("expression", ["Read", "Read + 1"])
@pytest.mark.parametrize("phase", ["init", "post"])
def test_var_inst_cannot_capture_implicit_method_result(expression, phase):
    declaration = (
        f"Leaf(seed := {expression})" if phase == "init" else f"Leaf := (n := {expression})"
    )
    with pytest.raises(ValidationError, match="invocation storage"):
        check(f"""FUNCTION_BLOCK Leaf VAR_INPUT n : INT; END_VAR
        METHOD FB_init : BOOL {FLAGS} VAR_INPUT seed : INT := 0; END_VAR END_METHOD
        END_FUNCTION_BLOCK
        FUNCTION_BLOCK B METHOD Read : INT VAR_INST child : {declaration}; END_VAR
        Read := 1; END_METHOD END_FUNCTION_BLOCK""")


@pytest.mark.parametrize(
    "kind", ["INT(7)", "INT()", "INT(DoesNotExist())", "ARRAY[1..1] OF INT[(7)]"]
)
@pytest.mark.parametrize("context", ["struct", "interface"])
def test_unused_non_fb_declaration_contexts_reject_initialization_arguments(kind, context):
    source = (
        f"TYPE Unused : STRUCT n : {kind}; END_STRUCT END_TYPE"
        if context == "struct"
        else f"INTERFACE I METHOD M VAR_INPUT n : {kind}; END_VAR END_METHOD END_INTERFACE"
    )
    with pytest.raises(ValidationError, match="Initialization arguments require"):
        check(source)
