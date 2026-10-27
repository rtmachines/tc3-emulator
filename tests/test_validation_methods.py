"""Static method contracts, including methods that are never invoked."""

import pytest

from tc_emulator.errors import ValidationError
from tc_emulator.parser import parse
from tc_emulator.types import ArrayType, StringType
from tc_emulator.validation import validate


def block(methods, declarations="", body="", name="B"):
    return f"FUNCTION_BLOCK {name}\n{declarations}\n{body}\n{methods}\nEND_FUNCTION_BLOCK"


def method(body="", declarations="", name="M", result="INT", access=""):
    result = f" : {result}" if result else ""
    return f"METHOD {access} {name}{result}\n{declarations}\n{body}\nEND_METHOD\n"


def check(source):
    return validate(parse(source, source="methods.st"))


def reject(source, match):
    with pytest.raises(ValidationError, match=match) as caught:
        check(source)
    assert caught.value.loc is not None
    assert caught.value.loc.source == "methods.st"


def test_owner_and_external_calls_record_the_receiver_and_resolved_method():
    registry = check(
        block(method("M := count;"), "VAR count : INT; END_VAR", "M();")
        + "\nPROGRAM P VAR fb : B; x : INT; END_VAR x := fb.M(); END_PROGRAM"
    )
    assert registry["B.M"].owner == "B"
    assert registry.method_calls[id(registry["B"].body[0].call)] == (None, "B.M")
    call = registry["P"].body[0].value
    receiver, target = registry.method_calls[id(call)]
    assert receiver.parts == ("FB",)
    assert target == "B.M"


def test_sibling_private_calls_and_same_type_private_receiver_are_legal():
    registry = check(
        block(
            method("M := Hidden();")
            + method("Hidden := 4;", name="Hidden", access="PRIVATE")
            + method("Other := local.Hidden();", "VAR local : B; END_VAR", name="Other")
        )
    )
    assert {target for _, target in registry.method_calls.values()} == {"B.HIDDEN"}


def test_namespaces_and_method_local_constants_resolve_bounds_independently():
    source = block(
        method(
            "M := data[2];",
            "VAR CONSTANT N : INT := Limit; END_VAR "
            "VAR data : ARRAY[1..N] OF INT; text : STRING(N); END_VAR",
        ),
        "VAR CONSTANT Limit : INT := 2; END_VAR",
    )
    source += "\n" + block(
        method(
            "M := data[3];",
            "VAR CONSTANT N : INT := 3; END_VAR VAR data : ARRAY[1..N] OF INT; END_VAR",
        ),
        name="C",
    )
    registry = check(source)
    assert registry["B.M"].variables[1].type_name == ArrayType(((1, 2),), "INT")
    assert registry["B.M"].variables[2].type_name == StringType(2)
    assert registry["C.M"].variables[1].type_name == ArrayType(((1, 3),), "INT")


def test_method_local_names_shadow_inaccessible_owner_storage():
    check(
        block(
            method("M := x;", "VAR_INPUT x : INT := 5; END_VAR"),
            "VAR_TEMP x : BOOL; END_VAR",
            "M();",
        )
    )


@pytest.mark.parametrize("section", ["VAR_TEMP", "VAR_IN_OUT"])
@pytest.mark.parametrize("use", ["M := x;", "x := 1;", "M := x + 1;"])
def test_owner_transient_storage_is_inaccessible_even_in_unused_methods(section, use):
    reject(block(method(use), f"{section} x : INT; END_VAR"), section)


@pytest.mark.parametrize("call", ["M()", "M(a := 1)"])
def test_uninitialized_method_inputs_and_inout_are_required(call):
    reject(
        block(
            method("", "VAR_INPUT a : INT; END_VAR VAR_IN_OUT b : INT; END_VAR"), body=call + ";"
        ),
        "Missing required parameter",
    )


def test_initialized_input_defaults_are_optional_but_outputs_are_not_inputs():
    registry = check(
        block(
            method("M := a;", "VAR_INPUT a : INT := 7; END_VAR VAR_OUTPUT out : INT; END_VAR"),
            body="M(); M(3);",
        )
    )
    assert registry["B.M"].variables[0].default == 7


@pytest.mark.parametrize(
    "call, message",
    [
        ("fb.M(TRUE)", "Expected"),
        ("fb.M(1, a := 2)", "mix positional"),
        ("fb.M(a := 1, a := 2)", "Duplicate argument"),
        ("fb.M(z := 1)", "Unknown parameter"),
        ("fb.M(a => x)", "requires :="),
        ("fb.M(1, 2)", "Too many"),
    ],
)
def test_method_arguments_are_checked(call, message):
    reject(
        block(method("M := a;", "VAR_INPUT a : INT; END_VAR"))
        + f"\nPROGRAM P VAR fb : B; x : INT; END_VAR {call}; END_PROGRAM",
        message,
    )


@pytest.mark.parametrize(
    "actual, declaration",
    [("1", ""), ("x", "VAR x : DINT; END_VAR"), ("x", "VAR CONSTANT x : INT := 2; END_VAR")],
)
def test_method_inout_requires_exact_mutable_storage(actual, declaration):
    reject(
        block(
            method("x := 2;", "VAR_IN_OUT x : INT; END_VAR", result=""),
            declaration,
            f"M({actual});",
        ),
        "writable|exact type",
    )


def test_method_own_inout_is_supported():
    check(
        block(
            method("x := 2;", "VAR_IN_OUT x : INT; END_VAR", result=""),
            "VAR x : INT; END_VAR",
            "M(x);",
        )
    )


def test_private_method_cannot_be_called_outside_owner_scope():
    reject(
        block(method("M := 1;", access="PRIVATE"))
        + "\nPROGRAM P VAR fb : B; END_VAR fb.M(); END_PROGRAM",
        "[Pp]rivate|PRIVATE",
    )


def test_void_method_cannot_be_used_as_value():
    reject(block(method(result=""), "VAR x : INT; END_VAR", "x := M();"), "[Vv]oid|expression")


@pytest.mark.parametrize("body", ["missing := 1;", "M := TRUE;", "missing();"])
def test_unused_methods_are_validated(body):
    reject(block(method(body)), "Unknown|Expected")


@pytest.mark.parametrize(
    "methods",
    [method("M := M();"), method("M := Other();") + method("Other := M();", name="Other")],
)
def test_recursive_method_call_cycles_are_rejected(methods):
    reject(block(methods), "Recursive call")


def test_cycle_through_function_and_method_is_rejected():
    reject(
        block(method("M := F();"))
        + "\nFUNCTION F : INT VAR fb : B; END_VAR F := fb.M(); END_FUNCTION",
        "Recursive call",
    )


@pytest.mark.parametrize(
    "methods, declarations",
    [
        (method() + method(), ""),
        (method(), "VAR M : INT; END_VAR"),
        (method(name="B"), ""),
        (method(name="FB_INIT"), ""),
    ],
)
def test_duplicate_or_reserved_method_names_are_rejected(methods, declarations):
    reject(block(methods, declarations), "[Dd]uplicate|[Cc]ollision|[Rr]eserved|[Ll]ifecycle")


def test_method_result_name_is_reserved_even_though_registry_key_is_qualified():
    reject(block(method(declarations="VAR M : INT; END_VAR")), "result name")


def test_owner_constants_remain_readonly_in_methods():
    reject(block(method("Limit := 2;"), "VAR CONSTANT Limit : INT := 1; END_VAR"), "not a writable")


def test_method_is_not_a_value_field_or_global_function():
    reject(block(method()) + "\nFUNCTION F : INT F := M(); END_FUNCTION", "Unknown call")
    reject(
        block(method()) + "\nFUNCTION F : INT VAR fb : B; END_VAR F := fb.M; END_FUNCTION",
        "Unknown field",
    )


def test_method_bound_projects_an_owner_aggregate_constant_without_losing_scope():
    source = "TYPE Limits : STRUCT count : INT; END_STRUCT END_TYPE\n"
    source += block(
        method("M := items[2];", "VAR items : ARRAY[1..Config.count] OF INT; END_VAR"),
        "VAR CONSTANT Config : Limits := (count := 2); END_VAR",
    )
    assert check(source)["B.M"].variables[0].type_name == ArrayType(((1, 2),), "INT")


@pytest.mark.parametrize(
    "declarations, message",
    [
        ("VAR CONSTANT N : INT := N; END_VAR", "Constant dependency cycle"),
        ("VAR CONSTANT N : INT := mutable; END_VAR", "mutable"),
        ("VAR a : ARRAY[0..1000000 + 0] OF INT; END_VAR", "1000000"),
        ("VAR_INPUT a : INT := TRUE; END_VAR", "Expected"),
        ("VAR_IN_OUT a : INT := 1; END_VAR", "initializer"),
    ],
)
def test_unused_method_declarations_are_fully_validated(declarations, message):
    reject(block(method(declarations=declarations), "VAR mutable : INT; END_VAR"), message)


def test_method_local_constants_shadow_owner_and_global_constants():
    source = "VAR_GLOBAL CONSTANT N : INT := 9; END_VAR\n"
    source += block(
        method(
            "M := a[2];", "VAR CONSTANT N : INT := 2; END_VAR VAR a : ARRAY[1..N] OF INT; END_VAR"
        ),
        "VAR CONSTANT N : INT := 4; END_VAR",
    )
    assert check(source)["B.M"].variables[1].type_name == ArrayType(((1, 2),), "INT")


def test_owner_fields_shadow_global_values_in_method_expressions():
    source = "VAR_GLOBAL x : BOOL; END_VAR\n"
    source += block(method("M := x;"), "VAR x : INT; END_VAR")
    check(source)


def test_global_and_program_receivers_keep_full_dispatch_path():
    source = "VAR_GLOBAL global_fb : B; END_VAR\n" + block(method("M := 2;"))
    source += "\nPROGRAM P VAR fb : B; END_VAR END_PROGRAM"
    source += "\nFUNCTION F : INT F := global_fb.M() + P.fb.M(); END_FUNCTION"
    registry = check(source)
    assert {receiver.parts for receiver, _ in registry.method_calls.values()} == {
        ("GLOBAL_FB",),
        ("P", "FB"),
    }


def test_nested_owner_receiver_and_method_outputs_are_validated():
    source = block(method("M := 3;", "VAR_OUTPUT value : INT; END_VAR"), name="Child")
    source += "\n" + block(
        method("M := nested.M(value => value);"), "VAR nested : Child; value : INT; END_VAR"
    )
    registry = check(source)
    receiver, target = next(iter(registry.method_calls.values()))
    assert receiver.parts == ("NESTED",)
    assert target == "CHILD.M"


def test_value_method_result_can_be_an_array_with_owner_constant_bounds():
    registry = check(
        block(method(result="ARRAY[1..N] OF INT"), "VAR CONSTANT N : INT := 2; END_VAR")
    )
    assert registry["B.M"].return_type == ArrayType(((1, 2),), "INT")


def test_method_input_named_like_a_global_function_shadows_the_callable():
    source = block(method("M := helper();", "VAR_INPUT helper : INT; END_VAR"))
    source += "\nFUNCTION helper : INT helper := 1; END_FUNCTION"
    reject(source, "not callable")


def test_standalone_method_ast_is_rejected_without_an_owner_instance_scope():
    from dataclasses import replace

    program = parse(block(method("M := 1;")), source="methods.st")
    standalone = replace(program, pous=program.pous[0].methods)
    with pytest.raises(ValidationError, match="METHOD.*FUNCTION_BLOCK"):
        validate(standalone)


def test_method_local_scalar_still_shadows_same_named_owner_method():
    reject(
        block(method(result="") + method("M();", "VAR M : INT; END_VAR", name="Run")),
        "Call target M is not callable",
    )
