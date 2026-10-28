"""Enum pragma syntax, nominal values and checked constant conversions."""

import pytest

from tc_emulator import ArgumentError, Runtime
from tc_emulator.errors import ParseError, ValidationError
from tc_emulator.parser import parse
from tc_emulator.types import EnumType, EnumValue
from tc_emulator.validation import validate

STRICT = "{attribute 'strict'}"
QUALIFIED = "{attribute 'qualified_only'}"


@pytest.mark.parametrize("attributes", [STRICT, QUALIFIED, STRICT + QUALIFIED, QUALIFIED + STRICT])
def test_enum_pragmas_preserve_flags_and_only_mark_first_declaration(attributes):
    program = parse(attributes + "\nTYPE E : (Stop, Run := 2); Other : (Off, On); END_TYPE")
    first, other = program.types
    assert first.definition.strict is (STRICT in attributes)
    assert first.definition.qualified_only is (QUALIFIED in attributes)
    assert (other.definition.strict, other.definition.qualified_only) == (False, False)
    assert (first.loc.line, first.loc.column) == (2, 6)
    kind = validate(program).types["E"]
    assert (kind.strict, kind.qualified_only) == (
        STRICT in attributes,
        QUALIFIED in attributes,
    )


@pytest.mark.parametrize(
    "source",
    [
        STRICT + STRICT + " TYPE E : (Stop, Run); END_TYPE",
        QUALIFIED + QUALIFIED + " TYPE E : (Stop, Run); END_TYPE",
        "{attribute 'strict' := 'true'} TYPE E : (Stop, Run); END_TYPE",
        "{attribute 'unknown'} TYPE E : (Stop, Run); END_TYPE",
        STRICT + " FUNCTION F : INT END_FUNCTION TYPE E : (Stop, Run); END_TYPE",
        STRICT + " VAR_GLOBAL n : INT; END_VAR",
        STRICT + " INTERFACE I END_INTERFACE",
        "TYPE " + STRICT + " E : (Stop, Run); END_TYPE",
        "TYPE E : (Stop, Run); " + QUALIFIED + " Other : (Off, On); END_TYPE",
        "FUNCTION F : INT " + STRICT + " F := 1; END_FUNCTION",
        STRICT + " TYPE E : INT; END_TYPE",
        QUALIFIED + " TYPE E : STRUCT x : INT; END_STRUCT; END_TYPE",
        STRICT + " TYPE E : ARRAY[1..2] OF INT; END_TYPE",
        STRICT + " TYPE Alias : E; END_TYPE TYPE E : (Stop, Run); END_TYPE",
    ],
)
def test_enum_pragmas_reject_invalid_placement_targets_and_payloads(source):
    with pytest.raises(ParseError):
        parse(source)


def test_existing_gvl_and_lifecycle_pragmas_remain_supported():
    program = parse(
        QUALIFIED + " VAR_GLOBAL n : INT; END_VAR "
        "{attribute 'call_after_init'} FUNCTION_BLOCK B END_FUNCTION_BLOCK"
    )
    assert program.gvls[0].qualified_only
    assert program.pous[0].call_after_init


def enum_source(*, strict=True, qualified=False, default=""):
    return (
        (STRICT if strict else "")
        + (QUALIFIED if qualified else "")
        + " TYPE E : (Stop := 0, Run := 2)"
        + default
        + "; END_TYPE "
    )


@pytest.mark.parametrize("expr", ["2", "1 + 1", "INT#2", "limit", "G.limit"])
def test_strict_integer_constants_become_enum_values_before_execution(expr):
    source = enum_source() + "VAR_GLOBAL CONSTANT limit : INT := 2; END_VAR "
    source += "FUNCTION F : E F := " + expr + "; END_FUNCTION"
    # A different GVL name exercises qualified and exported constant paths.
    runtime = Runtime(parse(source, gvl_name="G"))
    result = runtime.call("F").value
    assert isinstance(result, EnumValue)
    assert (result.type_name, result.name, result.value) == ("E", "RUN", 2)


@pytest.mark.parametrize("strict", [True, False])
@pytest.mark.parametrize(
    "expr", ["3", "n", "Other.Run", "e + e", "-e", "TRUE", "REAL#2", "T#2ms", "Value()"]
)
def test_enum_rejects_nonmembers_mutable_integers_foreign_enums_and_arithmetic(strict, expr):
    source = enum_source(strict=strict)
    source += (
        "TYPE Other : (Stop, Run := 2); END_TYPE FUNCTION Value : INT Value := 2; END_FUNCTION "
    )
    source += "FUNCTION F : E VAR n : INT := 2; e : E; END_VAR F := " + expr + "; END_FUNCTION"
    with pytest.raises(ValidationError):
        Runtime.from_source(source)


def test_unmarked_enums_keep_conservative_integer_assignment_rule():
    with pytest.raises(ValidationError):
        Runtime.from_source(enum_source(strict=False) + "FUNCTION F : E F := 2; END_FUNCTION")


@pytest.mark.parametrize(
    "context", ["local", "gvl", "type", "alias", "array", "struct", "constant"]
)
def test_strict_constants_initialize_every_value_container(context):
    source = enum_source(default=" := 1 + 1" if context == "type" else "")
    extra = {
        "local": "FUNCTION F : E VAR x : E := 1 + 1; END_VAR F := x; END_FUNCTION",
        "gvl": "VAR_GLOBAL x : E := 1 + 1; END_VAR FUNCTION F : E F := x; END_FUNCTION",
        "type": "FUNCTION F : E END_FUNCTION",
        "alias": "TYPE A : E := 1 + 1; END_TYPE FUNCTION F : A END_FUNCTION",
        "array": "FUNCTION F : E VAR a : ARRAY[1..2] OF E := [2(1 + 1)]; END_VAR F := a[2]; END_FUNCTION",
        "struct": "TYPE S : STRUCT x : E := 1 + 1; END_STRUCT; END_TYPE FUNCTION F : E VAR s : S; END_VAR F := s.x; END_FUNCTION",
        "constant": "FUNCTION F : E VAR CONSTANT chosen : E := limit; limit : INT := 1 + 1; END_VAR F := chosen; END_FUNCTION",
    }[context]
    result = Runtime.from_source(source + extra).call("F").value
    assert (result.type_name, result.name, result.value) == ("E", "RUN", 2)


@pytest.mark.parametrize("expr", ["Run", "Alias.Run", "E.Run"])
def test_unique_short_and_qualified_alias_labels_keep_nominal_identity(expr):
    source = enum_source(strict=False) + "TYPE Alias : E; END_TYPE "
    source += "FUNCTION F : E VAR CONSTANT chosen : E := " + expr + "; END_VAR "
    source += "CASE chosen OF Stop: F := Stop; Run: F := chosen; END_CASE; END_FUNCTION"
    value = Runtime.from_source(source).call("F").value
    assert (value.type_name, value.name, value.value) == ("E", "RUN", 2)


def test_unqualified_enum_alias_default_is_legal_when_label_is_unique():
    value = (
        Runtime.from_source(
            enum_source(strict=False) + "TYPE A : E := Run; END_TYPE FUNCTION F : A END_FUNCTION"
        )
        .call("F")
        .value
    )
    assert value.name == "RUN"


@pytest.mark.parametrize("reverse", [False, True])
def test_ambiguous_short_enum_labels_are_rejected_independent_of_order(reverse):
    declarations = [enum_source(strict=False), "TYPE Other : (Stop, Run := 2); END_TYPE"]
    if reverse:
        declarations.reverse()
    with pytest.raises(ValidationError, match="[Aa]mbiguous"):
        Runtime.from_source("".join(declarations) + " FUNCTION F : E F := Run; END_FUNCTION")


@pytest.mark.parametrize(
    "declarations", ["VAR Run : INT := 9; END_VAR", "VAR CONSTANT Run : INT := 9; END_VAR"]
)
def test_storage_shadows_unqualified_enum_labels(declarations):
    result = (
        Runtime.from_source(
            enum_source(strict=False)
            + "FUNCTION F : INT "
            + declarations
            + " F := Run; END_FUNCTION"
        )
        .call("F")
        .value
    )
    assert result == 9


def test_qualified_only_allows_own_short_default_but_rejects_external_short_label():
    source = enum_source(qualified=True, default=" := Run")
    value = (
        Runtime.from_source(
            source + "TYPE Alias : E; END_TYPE FUNCTION F : Alias F := Alias.Run; END_FUNCTION"
        )
        .call("F")
        .value
    )
    assert (value.enum_type.strict, value.enum_type.qualified_only, value.name) == (
        True,
        True,
        "RUN",
    )
    with pytest.raises(ValidationError):
        Runtime.from_source(source + "FUNCTION F : E F := Run; END_FUNCTION")


def test_strict_value_inputs_properties_actions_and_lifecycle_share_conversion():
    source = (
        enum_source(qualified=True)
        + """
    FUNCTION Echo : E VAR_INPUT x : E; END_VAR Echo := x; END_FUNCTION
    FUNCTION_BLOCK Base
    VAR_INPUT mode : E; END_VAR VAR_OUTPUT seen, initialized : E; END_VAR
    METHOD FB_init : BOOL
    VAR_INPUT bInitRetains : BOOL; bInCopyCode : BOOL; initial : E; END_VAR
    initialized := initial;
    END_METHOD
    METHOD Set : E VAR_INPUT x : E; END_VAR Set := x; END_METHOD
    PROPERTY P : E
    GET P := seen; END_GET SET seen := P; END_SET END_PROPERTY
    ACTION Apply: seen := mode; END_ACTION
    END_FUNCTION_BLOCK
    FUNCTION_BLOCK Derived EXTENDS Base
    ACTION Apply: SUPER^.Apply(mode := 1 + 1); END_ACTION
    END_FUNCTION_BLOCK
    PROGRAM Main
    VAR item : Derived(initial := 1 + 1) := (mode := 2, P := 1 + 1);
    a : ARRAY[1..1] OF E; END_VAR
    item.P := Echo(1 + 1); item.mode := item.Set(2);
    item.Apply(mode := 2); a[1] := 1 + 1;
    END_PROGRAM
    """
    )
    rt = Runtime.from_source(source)
    fb = rt.program_fb("Main", "item")
    assert fb.output("initialized").name == "RUN"
    assert fb.output("seen").name == "RUN"
    rt.scan("Main")
    assert fb.output("seen").name == "RUN"
    assert rt.program_cell("Main", "a").value[0].name == "RUN"
    for operation in [
        lambda: rt.call("Echo", x=2),
        lambda: fb.call_method("Set", x=2),
        lambda: fb.call_action("Apply", mode=2),
        lambda: fb.set_property("P", 2),
        lambda: rt.instantiate("Derived", init={"initial": 2}),
    ]:
        with pytest.raises(ArgumentError):
            operation()
    assert rt.call("Echo", x="Run").value.name == "RUN"
    fb.call_method("Set", x=fb.output("seen"))


@pytest.mark.parametrize("section,mode", [("VAR_IN_OUT", ":="), ("VAR_OUTPUT", "=>")])
def test_strict_enum_writable_parameters_require_enum_storage(section, mode):
    source = enum_source() + "FUNCTION G : BOOL " + section + " x : E; END_VAR END_FUNCTION "
    with pytest.raises(ValidationError, match="exact type"):
        Runtime.from_source(
            source + "FUNCTION F : BOOL VAR n : INT := 2; END_VAR G(x " + mode + " n); END_FUNCTION"
        )
    rt = Runtime.from_source(
        source
        + "TYPE A : E; END_TYPE FUNCTION F : E VAR e : A; END_VAR G(x "
        + mode
        + " e); F := e; END_FUNCTION"
    )
    assert rt.call("F").value.name == "STOP"


@pytest.mark.parametrize("expr", ["3", "n", "Other.Run", "Value()"])
@pytest.mark.parametrize(
    "context",
    [
        "local",
        "gvl",
        "type",
        "alias",
        "array",
        "struct",
        "field",
        "function",
        "method",
        "action",
        "property",
        "init",
        "post-input",
        "post-property",
    ],
)
def test_strict_rejections_apply_at_every_value_boundary(context, expr):
    prefix = (
        enum_source()
        + """
    TYPE Other : (Stop, Run := 2); S : STRUCT x : E; END_STRUCT; END_TYPE
    VAR_GLOBAL n : INT := 2; END_VAR
    FUNCTION Value : INT Value := 2; END_FUNCTION
    FUNCTION Echo : E VAR_INPUT x : E; END_VAR Echo := x; END_FUNCTION
    FUNCTION_BLOCK B
    VAR_INPUT x : E; END_VAR
    METHOD FB_init : BOOL
    VAR_INPUT bInitRetains : BOOL; bInCopyCode : BOOL; initial : E := E.Stop; END_VAR
    END_METHOD
    METHOD M : E VAR_INPUT x : E; END_VAR M := x; END_METHOD
    PROPERTY P : E GET P := x; END_GET SET x := P; END_SET END_PROPERTY
    ACTION A: x := x; END_ACTION
    END_FUNCTION_BLOCK
    """
    )
    code = {
        "local": f"FUNCTION F : E VAR x : E := {expr}; END_VAR END_FUNCTION",
        "gvl": f"VAR_GLOBAL x : E := {expr}; END_VAR",
        "type": "",  # handled separately to attach the pragma
        "alias": f"TYPE A : E := {expr}; END_TYPE",
        "array": f"FUNCTION F : E VAR a : ARRAY[1..1] OF E := [{expr}]; END_VAR END_FUNCTION",
        "struct": f"TYPE C : STRUCT x : E := {expr}; END_STRUCT; END_TYPE",
        "field": f"PROGRAM Main VAR s : S; END_VAR s.x := {expr}; END_PROGRAM",
        "function": f"FUNCTION F : E F := Echo({expr}); END_FUNCTION",
        "method": f"PROGRAM Main VAR b : B; END_VAR b.M({expr}); END_PROGRAM",
        "action": f"PROGRAM Main VAR b : B; END_VAR b.A(x := {expr}); END_PROGRAM",
        "property": f"PROGRAM Main VAR b : B; END_VAR b.P := {expr}; END_PROGRAM",
        "init": f"PROGRAM Main VAR b : B(initial := {expr}); END_VAR END_PROGRAM",
        "post-input": f"PROGRAM Main VAR b : B := (x := {expr}); END_VAR END_PROGRAM",
        "post-property": f"PROGRAM Main VAR b : B := (P := {expr}); END_VAR END_PROGRAM",
    }[context]
    if context == "type":
        prefix += STRICT + f" TYPE Marked : (Off, On := 2) := {expr}; END_TYPE"
    with pytest.raises(ValidationError):
        Runtime.from_source(prefix + code)


def test_enum_constant_projection_and_nested_defaults_keep_final_nominal_type():
    source = (
        enum_source(qualified=True, default=" := 2")
        + """
    TYPE Alias : E; S : STRUCT state : Alias; n : INT; END_STRUCT;
    Records : ARRAY[1..1] OF S; END_TYPE
    FUNCTION F : E
    VAR CONSTANT cfg : S := (state := 2, n := 2);
    records : Records := [(state := 1 + 1, n := 2)]; END_VAR
    VAR values : ARRAY[1..cfg.n] OF E; END_VAR
    values[2] := records[1].state; F := values[2];
    END_FUNCTION
    """
    )
    value = Runtime.from_source(source).call("F").value
    assert (value.name, value.value, value.enum_type.default_member) == ("RUN", 2, "RUN")
    assert (value.enum_type.strict, value.enum_type.qualified_only) == (True, True)


def test_label_shadowing_in_gvl_owner_and_result_slots():
    source = (
        enum_source(strict=False)
        + """
    VAR_GLOBAL Run : INT := 7; END_VAR
    FUNCTION ReadGlobal : INT ReadGlobal := Run; END_FUNCTION
    FUNCTION Stop : INT Stop := 8; END_FUNCTION
    FUNCTION_BLOCK Base VAR Run : INT := 9; END_VAR
    METHOD Read : INT Read := Run; END_METHOD END_FUNCTION_BLOCK
    FUNCTION_BLOCK Child EXTENDS Base END_FUNCTION_BLOCK
    """
    )
    rt = Runtime.from_source(source)
    assert rt.call("ReadGlobal").value == 7
    assert rt.call("Stop").value == 8
    assert rt.instantiate("Child").call_method("Read").value == 9


def test_qualified_only_candidates_do_not_make_public_short_label_ambiguous():
    source = enum_source(strict=False) + QUALIFIED + " TYPE Hidden : (Stop, Run := 5); END_TYPE "
    value = Runtime.from_source(source + "FUNCTION F : E F := Run; END_FUNCTION").call("F").value
    assert (value.type_name, value.value) == ("E", 2)


def test_enum_metadata_positional_compatibility_and_python_values():
    old = EnumType("E", (("Stop", 0), ("Run", 2)), "INT", "RUN")
    assert (old.strict, old.qualified_only) == (False, False)
    rt = Runtime.from_source(
        enum_source(qualified=True)
        + """
    FUNCTION_BLOCK B VAR_INPUT x : E; END_VAR VAR_OUTPUT seen : E; END_VAR
    METHOD FB_init : BOOL VAR_INPUT bInitRetains : BOOL; bInCopyCode : BOOL; x : E; END_VAR
    seen := x; END_METHOD
    PROPERTY P : E GET P := seen; END_GET SET seen := P; END_SET END_PROPERTY
    END_FUNCTION_BLOCK
    """
    )
    fb = rt.instantiate("B", init={"x": "Run"}, inputs={"x": "Stop"})
    assert fb.output("seen").name == "RUN"
    assert fb.inspect()["X"].name == "STOP"
    for value in [2, True, EnumValue(EnumType("Other", (("Run", 2),)), "Run", 2)]:
        with pytest.raises(ArgumentError):
            fb.set_property("P", value)
        with pytest.raises(ArgumentError):
            rt.instantiate("B", init={"x": "Run"}, inputs={"x": value})
    fb.set_property("P", "E.Run")
    assert fb.get_property("P").name == "RUN"


@pytest.mark.parametrize(
    "body", ["IF e = 2 THEN END_IF;", "CASE e OF 2: END_CASE;", "e := +e;", "e := e - E.Stop;"]
)
def test_strict_enums_keep_nominal_comparison_case_and_arithmetic_rules(body):
    with pytest.raises(ValidationError):
        Runtime.from_source(
            enum_source() + "FUNCTION F : BOOL VAR e : E; END_VAR " + body + " END_FUNCTION"
        )


@pytest.mark.parametrize("section,mode", [("VAR_IN_OUT", ":="), ("VAR_OUTPUT", "=>")])
@pytest.mark.parametrize("argument", ["2", "E.Run", "chosen"])
def test_strict_enum_constants_cannot_bind_writable_parameters(section, mode, argument):
    source = enum_source() + f"FUNCTION G : BOOL {section} x : E; END_VAR END_FUNCTION "
    source += f"FUNCTION F : BOOL VAR CONSTANT chosen : E := 2; END_VAR G(x {mode} {argument}); END_FUNCTION"
    with pytest.raises(ValidationError, match="writable|constant"):
        Runtime.from_source(source)


@pytest.mark.parametrize("qualified", [False, True])
def test_strict_type_default_accepts_named_integer_constant(qualified):
    source = "VAR_GLOBAL CONSTANT limit : INT := 1 + 1; END_VAR "
    source += enum_source(qualified=qualified, default=" := limit")
    source += "FUNCTION F : E END_FUNCTION"
    value = Runtime.from_source(source).call("F").value
    assert (value.name, value.value, value.enum_type.default_member) == ("RUN", 2, "RUN")
