"""Static contracts for instance arrays and open array aliases."""

import pytest

from tc_emulator.errors import ValidationError
from tc_emulator.parser import parse
from tc_emulator.syntax import Index
from tc_emulator.types import FBArrayType, OpenArrayType, StringType
from tc_emulator.validation import validate


def check(source):
    return validate(parse(source, source="array-extensions.st"))


def reject(source, match=None):
    with pytest.raises(ValidationError, match=match) as caught:
        check(source)
    assert caught.value.loc is not None
    assert caught.value.loc.source == "array-extensions.st"


def block(methods="", variables="", body=""):
    return f"FUNCTION_BLOCK B {variables} {body} {methods} END_FUNCTION_BLOCK\n"


def function(body="", variables="", name="F", result="INT"):
    return f"FUNCTION {name} : {result} {variables} {body} END_FUNCTION\n"


@pytest.mark.parametrize(
    "kind,section",
    [
        ("FUNCTION", "VAR"),
        ("FUNCTION_BLOCK", "VAR"),
        ("FUNCTION_BLOCK", "VAR_TEMP"),
        ("PROGRAM", "VAR"),
        ("PROGRAM", "VAR_TEMP"),
    ],
)
@pytest.mark.parametrize("element", ["B", "TON", "CTU"])
def test_fixed_fb_storage_is_classified_for_all_owned_contexts(kind, section, element):
    result = " : INT" if kind == "FUNCTION" else ""
    registry = check(
        block()
        + f"{kind} P{result} {section} a : ARRAY[-2..-1,4..6] OF {element}; END_VAR END_{kind}"
    )
    assert registry["P"].variables[0].type_name == FBArrayType(((-2, -1), (4, 6)), element)


def test_global_and_method_storage_resolve_constant_scopes():
    source = "VAR_GLOBAL CONSTANT N : INT := 7; END_VAR VAR_GLOBAL a : ARRAY[1..N] OF B; END_VAR\n"
    source += block(
        "METHOD M VAR CONSTANT N : INT := 2; END_VAR VAR a : ARRAY[1..N] OF TON; END_VAR a[1](IN := TRUE); END_METHOD"
    )
    registry = check(source)
    assert registry["B.M"].variables[1].type_name.bounds == ((1, 2),)
    assert next(p for p in registry.values() if p.kind == "GVL").variables[-1].type_name.bounds == (
        (1, 7),
    )


@pytest.mark.parametrize("section", ["VAR_INPUT", "VAR_OUTPUT", "VAR_IN_OUT"])
def test_fb_arrays_are_not_parameters(section):
    reject(block() + function(variables=f"{section} a : ARRAY[1..2] OF B; END_VAR"))


@pytest.mark.parametrize(
    "declaration",
    ["VAR a : ARRAY[1..2] OF B := []; END_VAR", "VAR CONSTANT a : ARRAY[1..2] OF B := []; END_VAR"],
)
def test_fb_arrays_have_no_initializer_or_constant_value(declaration):
    reject(block() + function(variables=declaration))


@pytest.mark.parametrize(
    "definition",
    [
        "A : ARRAY[1..2] OF B;",
        "A : STRUCT x : ARRAY[1..2] OF B; END_STRUCT;",
        "A : ARRAY[*] OF INT;",
        "A : STRUCT x : ARRAY[*] OF INT; END_STRUCT;",
    ],
)
def test_type_definitions_cannot_contain_instance_or_open_arrays(definition):
    reject(block() + f"TYPE {definition} END_TYPE")


@pytest.mark.parametrize("section", ["VAR", "VAR_INPUT", "VAR_OUTPUT"])
def test_open_arrays_only_exist_as_direct_inout(section):
    reject(function(variables=f"{section} a : ARRAY[*] OF INT; END_VAR"))


@pytest.mark.parametrize(
    "source",
    [
        "VAR_GLOBAL a : ARRAY[*] OF INT; END_VAR",
        "FUNCTION F : ARRAY[*] OF INT END_FUNCTION",
        "FUNCTION F : ARRAY[1..2] OF B END_FUNCTION",
        "FUNCTION F : INT VAR_IN_OUT a : ARRAY[*] OF TON; END_VAR END_FUNCTION",
        "FUNCTION F : INT VAR_IN_OUT a : ARRAY[*] OF INT := []; END_VAR END_FUNCTION",
    ],
)
def test_open_and_instance_arrays_reject_other_declaration_contexts(source):
    reject(block() + source)


def test_open_string_capacity_uses_parameter_scope():
    registry = check(
        function(
            "F := LOWER_BOUND(a, 1);",
            "VAR CONSTANT N : INT := 4; END_VAR VAR_IN_OUT a : ARRAY[*] OF STRING(N); END_VAR",
        )
    )
    assert registry["F"].variables[1].type_name == OpenArrayType(1, StringType(4))


@pytest.mark.parametrize(
    "element,prefix",
    [
        ("INT", ""),
        ("Number", "TYPE Number : INT; END_TYPE"),
        ("State", "TYPE State : (Idle,Run); END_TYPE"),
        ("Item", "TYPE Item : STRUCT x : INT; END_STRUCT; END_TYPE"),
        ("STRING(3)", ""),
    ],
)
def test_open_inout_accepts_fixed_and_forwarded_exact_elements(element, prefix):
    source = prefix + "\n" + function("G(a);", f"VAR_IN_OUT a : ARRAY[*,*] OF {element}; END_VAR")
    source += function(
        "G := UPPER_BOUND(a, 2);", f"VAR_IN_OUT a : ARRAY[*,*] OF {element}; END_VAR", name="G"
    )
    source += function("F(a);", f"VAR a : ARRAY[-3..2,7..9] OF {element}; END_VAR", name="Caller")
    check(source)


@pytest.mark.parametrize(
    "actual", ["ARRAY[1..2] OF DINT", "ARRAY[1..2,1..2] OF INT", "INT", "ARRAY[1..2] OF B"]
)
def test_open_inout_rejects_rank_or_element_mismatch(actual):
    reject(
        block()
        + function(variables="VAR_IN_OUT a : ARRAY[*] OF INT; END_VAR")
        + function("F(a);", f"VAR a : {actual}; END_VAR", name="Caller")
    )


def test_readonly_arrays_cannot_bind_open_inout():
    reject(
        function(variables="VAR_IN_OUT a : ARRAY[*] OF INT; END_VAR")
        + function("F(a);", "VAR CONSTANT a : ARRAY[1..2] OF INT := []; END_VAR", name="Caller"),
        "writable",
    )


@pytest.mark.parametrize("body", ["a := a;", "F := a;", "IF a = a THEN END_IF;", "G(a);"])
def test_open_arrays_do_not_have_whole_values_or_bind_fixed_formals(body):
    reject(
        function(body, "VAR_IN_OUT a : ARRAY[*] OF INT; END_VAR")
        + function(variables="VAR_IN_OUT a : ARRAY[1..2] OF INT; END_VAR", name="G")
    )


def test_indexed_instance_and_method_calls_record_full_receiver():
    source = block(
        "METHOD Reset : INT Reset := 2; END_METHOD",
        "VAR_INPUT x : INT; END_VAR VAR_OUTPUT y : INT; END_VAR",
    )
    source += function(
        "a[1](x := 2); a[2].x := 3; F := a[1].Reset() + a[2].y;",
        "VAR a : ARRAY[1..2] OF B; END_VAR",
    )
    registry = check(source)
    receiver, target = next(iter(registry.method_calls.values()))
    assert isinstance(receiver, Index)
    assert receiver.base.parts == ("A",)
    assert target == "B.RESET"


def test_indexed_private_method_is_rejected():
    reject(
        block("METHOD PRIVATE Hidden END_METHOD")
        + function("a[1].Hidden();", "VAR a : ARRAY[1..2] OF B; END_VAR"),
        "Private",
    )


@pytest.mark.parametrize(
    "body", ["a();", "a[1] := a[2];", "F := a[1];", "a[TRUE]();", "a[1,2]();", "F := a[1].hidden;"]
)
def test_instance_array_misuse_is_source_aware(body):
    reject(
        block(variables="VAR hidden : INT; END_VAR")
        + function(body, "VAR a : ARRAY[1..2] OF B; END_VAR")
    )


@pytest.mark.parametrize("kind", ["INT", "TON"])
def test_bounds_metadata_accepts_fixed_storage_without_value_reads(kind):
    registry = check(
        function(
            "F := LOWER_BOUND(a, 1) + UPPER_BOUND(a, 1);",
            f"VAR a : ARRAY[-2..3] OF {kind}; END_VAR",
        )
    )
    calls = list(registry.bound_calls.values())
    assert [upper for _, _, upper in calls] == [False, True]
    assert all(array.parts == ("A",) for array, _, _ in calls)


@pytest.mark.parametrize(
    "call",
    [
        "LOWER_BOUND(a)",
        "LOWER_BOUND(a,1,2)",
        "LOWER_BOUND(a := a, dimension := 1)",
        "LOWER_BOUND(1,1)",
        "LOWER_BOUND(a,TRUE)",
        "LOWER_BOUND(a,1.0)",
    ],
)
def test_bounds_operator_signature_is_strict(call):
    reject(function(f"F := {call};", "VAR a : ARRAY[1..2] OF INT; END_VAR"))


def test_bounds_dimension_range_is_checked_at_execution_time():
    check(
        function("F := LOWER_BOUND(a,0) + UPPER_BOUND(a,9);", "VAR a : ARRAY[1..2] OF INT; END_VAR")
    )


@pytest.mark.parametrize("name", ["LOWER_BOUND", "UPPER_BOUND"])
def test_bounds_operator_names_are_reserved_but_local_storage_shadows_them(name):
    reject(function(name=name), "reserved")
    reject(f"TYPE {name} : INT; END_TYPE", "reserved")
    reject(
        function(f"F := {name}(a,1);", f"VAR {name} : INT; a : ARRAY[1..2] OF INT; END_VAR"),
        "callable",
    )


def test_bound_queries_stay_forbidden_in_constant_expressions():
    reject(
        function(
            variables="VAR a : ARRAY[1..2] OF INT; END_VAR VAR CONSTANT n : INT := LOWER_BOUND(a,1); END_VAR"
        ),
        "constant",
    )


def test_fb_array_containment_cycles_are_rejected():
    reject(block(variables="VAR a : ARRAY[1..2] OF B; END_VAR"), "containment.*cycle")


@pytest.mark.parametrize("count", [10000, 10001])
def test_expanded_instance_budget_includes_array_multiplicity(count):
    source = block() + function(variables=f"VAR a : ARRAY[1..{count}] OF B; END_VAR")
    if count == 10000:
        check(source)
    else:
        reject(source, "10000|instance.*limit")


def test_nested_instance_budget_is_expanded_per_root():
    source = block(variables="VAR a : ARRAY[1..100] OF TON; END_VAR")
    reject(
        source + function(variables="VAR a : ARRAY[1..100] OF B; END_VAR"), "10000|instance.*limit"
    )


def test_expanded_scalar_budget_accounts_for_all_fields_and_array_multiplicity():
    source = block(variables="VAR a,b : ARRAY[1..6000] OF INT; END_VAR")
    reject(
        source + function(variables="VAR a : ARRAY[1..100] OF B; END_VAR"), "1000000|leaf.*limit"
    )


def test_inout_aliases_do_not_consume_expanded_owned_storage():
    check(function(variables="VAR_IN_OUT a,b : ARRAY[1..600000] OF INT; END_VAR"))


def test_constructed_program_open_inout_is_rejected():
    from dataclasses import replace

    program = parse(
        function(variables="VAR_IN_OUT a : ARRAY[*] OF INT; END_VAR"), source="array-extensions.st"
    )
    pou = replace(program.pous[0], kind="PROGRAM", return_type=None)
    with pytest.raises(ValidationError, match="Open arrays|VAR_IN_OUT") as caught:
        validate(replace(program, pous=(pou,)))
    assert caught.value.loc.source == "array-extensions.st"


@pytest.mark.parametrize("section", ["VAR_IN_OUT", "VAR_INPUT"])
def test_open_array_cannot_be_forwarded_to_any_fixed_formal(section):
    reject(
        function("G(a);", "VAR_IN_OUT a : ARRAY[*] OF INT; END_VAR")
        + function(variables=f"{section} a : ARRAY[1..2] OF INT; END_VAR", name="G")
    )


def test_fb_and_method_open_parameters_support_forwarding_and_indexed_access():
    source = function("a[1] := 2;", "VAR_IN_OUT a : ARRAY[*] OF INT; END_VAR")
    source += block(
        "METHOD M VAR_IN_OUT a : ARRAY[*] OF INT; END_VAR F(a); END_METHOD",
        "VAR_IN_OUT a : ARRAY[*] OF INT; END_VAR",
        "M(a);",
    )
    source += "PROGRAM P VAR b : B; a : ARRAY[-2..4] OF INT; END_VAR b(a := a); b.M(a); END_PROGRAM"
    check(source)


@pytest.mark.parametrize(
    "element,prefix",
    [
        (
            "Other",
            "TYPE Item : STRUCT x : INT; END_STRUCT; Other : STRUCT x : INT; END_STRUCT; END_TYPE",
        ),
        ("Other", "TYPE Item : (A,B); Other : (A,B); END_TYPE"),
        ("STRING(4)", "TYPE Item : STRING(3); END_TYPE"),
    ],
)
def test_open_parameters_preserve_nominal_types_and_exact_string_capacity(element, prefix):
    reject(
        prefix
        + "\n"
        + function(variables="VAR_IN_OUT a : ARRAY[*] OF Item; END_VAR")
        + function("F(a);", f"VAR a : ARRAY[1..2] OF {element}; END_VAR", name="Caller")
    )


def test_transparent_alias_elements_bind_to_their_canonical_type():
    check(
        "TYPE Number : INT; END_TYPE\n"
        + function(variables="VAR_IN_OUT a : ARRAY[*] OF INT; END_VAR")
        + function("F(a);", "VAR a : ARRAY[-4..2] OF Number; END_VAR", name="Caller")
    )


def test_nested_indexed_private_method_uses_current_owner_scope():
    registry = check(
        block(
            "METHOD PRIVATE Hidden : INT Hidden := 1; END_METHOD "
            "METHOD M : INT VAR local : ARRAY[-1..0] OF B; END_VAR M := local[-1].Hidden(); END_METHOD"
        )
    )
    receiver, target = next(iter(registry.method_calls.values()))
    assert isinstance(receiver, Index)
    assert target == "B.HIDDEN"


def test_external_access_to_nested_private_fb_array_is_rejected():
    reject(
        block(variables="VAR items : ARRAY[1..2] OF TON; END_VAR")
        + function("b.items[1](IN := TRUE);", "VAR b : B; END_VAR"),
        "Private FB field",
    )


def test_global_and_program_indexed_method_receivers_are_kept_intact():
    registry = check(
        "VAR_GLOBAL a : ARRAY[1..2] OF B; END_VAR\n"
        + block("METHOD M : INT M := 1; END_METHOD")
        + "PROGRAM P VAR a : ARRAY[1..2] OF B; END_VAR END_PROGRAM\n"
        + function("F := a[1].M() + P.a[2].M();")
    )
    receivers = [receiver for receiver, _ in registry.method_calls.values()]
    assert {receiver.base.parts for receiver in receivers} == {("A",), ("P", "A")}


def test_owner_method_shadows_a_global_named_like_a_bound_operator():
    registry = check(
        "VAR_GLOBAL LOWER_BOUND : INT; END_VAR\n"
        + block("METHOD LOWER_BOUND : INT LOWER_BOUND := 7; END_METHOD", body="LOWER_BOUND();")
    )
    assert next(iter(registry.method_calls.values())) == (None, "B.LOWER_BOUND")
    assert not registry.bound_calls


def test_bounds_queries_accept_nested_array_storage_and_readonly_constants():
    registry = check(
        "TYPE Row : ARRAY[-2..3] OF INT; END_TYPE\n"
        + function(
            "F := LOWER_BOUND(a[1],1);", "VAR CONSTANT a : ARRAY[1..2] OF Row := []; END_VAR"
        )
    )
    receiver, dimension, upper = next(iter(registry.bound_calls.values()))
    assert isinstance(receiver, Index)
    assert dimension.value == 1
    assert upper is False


@pytest.mark.parametrize("body", ["F := a[1];", "F := a[TRUE,2];", "F := a[1,1.0];"])
def test_open_indexing_checks_rank_and_integer_selectors(body):
    reject(function(body, "VAR_IN_OUT a : ARRAY[*,*] OF INT; END_VAR"))


def test_nested_containment_cycle_through_arrays_is_rejected_before_initializers():
    reject(
        block(variables="VAR a : ARRAY[1..2] OF C; END_VAR")
        + "FUNCTION_BLOCK C VAR b : B; invalid : INT := TRUE; END_VAR END_FUNCTION_BLOCK",
        "containment.*cycle",
    )


def test_expanded_budget_preflight_runs_before_allocating_type_defaults():
    reject(
        "TYPE Item : STRUCT a : ARRAY[1..6000] OF INT := [TRUE]; END_STRUCT; END_TYPE\n"
        + block(variables="VAR a,b : Item; END_VAR")
        + function(variables="VAR a : ARRAY[1..100] OF B; END_VAR"),
        "1000000.*leaf limit",
    )


@pytest.mark.parametrize("count", [500000, 500001])
def test_owned_value_storage_budget_is_inclusive_across_variables(count):
    source = f"PROGRAM P VAR a,b : ARRAY[1..{count}] OF INT; END_VAR END_PROGRAM"
    if count == 500000:
        check(source)
    else:
        reject(source, "1000000.*leaf limit")


def test_expanded_instance_budget_is_per_root_not_global():
    source = block()
    source += "PROGRAM P VAR a : ARRAY[1..10000] OF B; END_VAR END_PROGRAM\n"
    source += "PROGRAM Q VAR a : ARRAY[1..10000] OF B; END_VAR END_PROGRAM"
    check(source)
