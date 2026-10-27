"""Static bit access, checked literal typing and constant bit expressions."""

import pytest

from tc_emulator.errors import ParseError, ValidationError
from tc_emulator.parser import parse
from tc_emulator.validation import Registry, validate


def function(body="F := TRUE;", declarations="", result="BOOL"):
    return f"FUNCTION F : {result} {declarations} {body} END_FUNCTION"


def checked(source):
    return validate(parse(source, source="bits.st"))


def rejected(source, match=None):
    with pytest.raises(ValidationError, match=match):
        checked(source)


def test_registry_exposes_resolved_bit_accesses():
    assert Registry().bit_accesses == {}


def test_named_bits_cache_base_and_preserve_struct_field_ambiguity():
    registry = checked("""TYPE S : STRUCT flag : WORD; END_STRUCT; END_TYPE
    FUNCTION F : BOOL
    VAR CONSTANT flag : INT := 2; END_VAR
    VAR word : WORD; s : S; END_VAR
    word.flag := TRUE; s.flag.flag := word.flag; F := s.flag.flag;
    END_FUNCTION""")
    assert len(registry.bit_accesses) == 4
    assert {index for _, index in registry.bit_accesses.values()} == {2}


@pytest.mark.parametrize(
    "kind, index",
    [
        ("BYTE", 7),
        ("WORD", 15),
        ("DWORD", 31),
        ("INT", 15),
        ("UINT", 15),
        ("DINT", 31),
        ("UDINT", 31),
    ],
)
def test_numeric_bit_lvalues_accept_all_integer_storage(kind, index):
    registry = checked(function(f"w.{index} := TRUE; F := w.{index};", f"VAR w : {kind}; END_VAR"))
    assert len(registry.bit_accesses) == 2
    assert {position for _, position in registry.bit_accesses.values()} == {index}


@pytest.mark.parametrize(
    "kind, index", [("BYTE", 8), ("WORD", 16), ("DWORD", 32), ("INT", 16), ("BOOL", 0), ("TIME", 0)]
)
def test_numeric_bit_index_and_owner_types_are_checked(kind, index):
    rejected(function(f"F := w.{index};", f"VAR w : {kind}; END_VAR"))


@pytest.mark.parametrize(
    "declaration",
    [
        "",
        "VAR pos : INT := 1; END_VAR",
        "VAR CONSTANT pos : BOOL := TRUE; END_VAR",
        "VAR CONSTANT pos : INT := -1; END_VAR",
        "VAR CONSTANT pos : INT := 16; END_VAR",
    ],
)
def test_named_bit_selector_requires_local_in_range_integer_constant(declaration):
    rejected(function("F := w.pos;", f"VAR w : WORD; END_VAR {declaration}"))


def test_literal_typed_integer_is_preserved_in_expression_validation():
    from tc_emulator.syntax import Assign, Literal, Location, Pou, Program, Reference, Unary

    loc = Location("bits.st", 1, 1)
    # Typed signed integers must never silently become untyped bit operands.
    literal = Literal(1, loc, "INT")
    program = Program(
        (
            Pou(
                "FUNCTION",
                "F",
                "INT",
                (),
                (Assign(Reference(("F",), loc), Unary("NOT", literal, loc), loc),),
                loc,
            ),
        )
    )
    with pytest.raises(ValidationError):
        validate(program)


@pytest.mark.parametrize("literal", ["INT#32768", "BYTE#256", "DWORD#4294967296"])
def test_typed_literals_are_checked_even_when_assignment_target_is_wider(literal):
    with pytest.raises((ParseError, ValidationError)):
        checked(function(f"F := {literal};", result="UDINT"))


def test_constant_bit_operations_and_typed_defaults():
    registry = checked("""TYPE A : WORD := NOT WORD#16#FF00;
        S : STRUCT x : DWORD := BYTE#16#F0 OR DWORD#16#100; END_STRUCT; END_TYPE
    FUNCTION F : BOOL
    VAR CONSTANT mask : WORD := WORD#16#8001; sign : BOOL := mask.15;
        pos : INT := 0; low : BOOL := mask.pos; inverted : BYTE := NOT BYTE#0;
        widened : DWORD := BYTE#16#FF XOR DWORD#16#100; END_VAR
    F := sign AND low; END_FUNCTION""")
    values = {var.name: var.default for var in registry["F"].variables}
    assert values == {
        "MASK": 32769,
        "SIGN": True,
        "POS": 0,
        "LOW": True,
        "INVERTED": 255,
        "WIDENED": 511,
    }
    assert registry.types["A"].default == 255
    assert registry.types["S"].fields[0].default == 496


@pytest.mark.parametrize(
    "expression",
    [
        "TRUE AND WORD#1",
        "NOT INT#1",
        "INT#1 OR WORD#1",
        "WORD#1 AND -1",
        "BYTE#1 OR 256",
        "4294967296 AND 1",
        "NOT -1",
    ],
)
def test_constant_bit_operands_reject_mixed_boolean_signed_and_width_overflow(expression):
    rejected(function(declarations=f"VAR CONSTANT value : DWORD := {expression}; END_VAR"))


def test_preflight_projects_constant_bits_through_aggregate_defaults_and_aliases():
    from tc_emulator.validation import _Validator

    source = """TYPE W : WORD := WORD#16#8000;
        S : STRUCT w : W; END_STRUCT; END_TYPE
    FUNCTION F : BOOL
    VAR CONSTANT pos : INT := 15; a : ARRAY[0..0] OF S := [(w := WORD#16#8000)];
      b : S := (w := WORD#16#8000); defaults : S := (); END_VAR
    F := a[0].w.pos AND b.w.15 AND defaults.w.pos; END_FUNCTION"""
    # Run the actual bound projection phase without resolving any named defaults.
    validator = _Validator(parse(source))
    validator.type_declarations = {decl.name: decl for decl in validator.program.types}
    pou = validator.program.pous[0]
    validator.variables[pou.name] = {var.name: var for var in pou.variables}
    validator.preflight_constants = True
    expr = pou.body[0].value
    assert validator.constant_expression(expr, pou) == (True, "BOOL")
    assert validator.pous.types == {}


def test_preflight_bit_read_is_usable_in_comparison_bound_expression():
    # A BOOL bit can determine a BOOL constant consumed by a following declaration.
    registry = checked(
        function(
            declarations="""VAR CONSTANT bits : WORD := WORD#1;
        pos : INT := 0; enabled : BOOL := bits.pos;
        yes : BOOL := enabled = TRUE; END_VAR
        VAR data : ARRAY[0..(WORD#7 AND 3)] OF INT; END_VAR"""
        )
    )
    assert registry["F"].variables[3].default is True
    assert registry["F"].variables[4].type_name.bounds == ((0, 3),)


@pytest.mark.parametrize("target", ["w.0", "w.pos", "s.w.0", "a[0].0"])
def test_recursive_constant_bit_owners_remain_read_only(target):
    rejected(
        "TYPE S : STRUCT w : WORD; END_STRUCT; END_TYPE "
        + function(
            f"{target} := TRUE;",
            """VAR CONSTANT pos : INT := 0; w : WORD := 0;
        s : S := (w := 0); a : ARRAY[0..0] OF WORD := [0]; END_VAR""",
        ),
        "writable",
    )


@pytest.mark.parametrize("actual", ["w.0", "w.pos", "s.w.0", "a[0].0"])
@pytest.mark.parametrize("binding", ["positional", "named", "fb"])
def test_bit_locations_cannot_bind_var_in_out(actual, binding):
    declaration = """VAR CONSTANT pos : INT := 0; END_VAR
        VAR w : WORD; s : S; a : ARRAY[0..0] OF WORD; b : B; END_VAR"""
    call = f"G({actual})" if binding == "positional" else f"G(value := {actual})"
    if binding == "fb":
        call = f"b(value := {actual}); F := TRUE"
    else:
        call = "F := " + call
    source = """TYPE S : STRUCT w : WORD; END_STRUCT; END_TYPE
        FUNCTION G : BOOL VAR_IN_OUT value : BOOL; END_VAR G := value; END_FUNCTION
        FUNCTION_BLOCK B VAR_IN_OUT value : BOOL; END_VAR END_FUNCTION_BLOCK """
    rejected(source + function(call + ";", declaration), "bit|Bit")


def test_bit_locations_allow_input_and_copyout():
    checked(
        """FUNCTION G : BOOL VAR_INPUT x : BOOL; END_VAR G := x; END_FUNCTION
        FUNCTION_BLOCK B VAR_OUTPUT x : BOOL; END_VAR x := TRUE; END_FUNCTION_BLOCK """
        + function("b(x => w.0); F := G(w.0);", "VAR w : WORD; b : B; END_VAR")
    )


@pytest.mark.parametrize("expression", ["SHL(WORD#1, 1)", "TO_WORD(1)"])
def test_standard_calls_still_rejected_in_constants(expression):
    rejected(function(declarations=f"VAR CONSTANT x : WORD := {expression}; END_VAR"))


@pytest.mark.parametrize("initial", ["word.pos", "arr[0].pos"])
def test_preflight_dependency_walk_includes_named_bit_selector(initial):
    from tc_emulator.validation import _Validator

    program = parse(
        function(
            declarations=f"""VAR CONSTANT word : WORD := 1;
        arr : ARRAY[0..0] OF WORD := [1]; enabled : BOOL := {initial};
        pos : INT := enabled; END_VAR"""
        )
    )
    validator = _Validator(program)
    pou = program.pous[0]
    validator.variables[pou.name] = {var.name: var for var in pou.variables}
    with pytest.raises(ValidationError, match="cycle"):
        validator.check_constant_dependencies(pou)


@pytest.mark.parametrize("path", ["field", "field.pos", "field.0"])
def test_constant_struct_with_aggregate_defaults_can_be_projected(path):
    checked(
        """TYPE S : STRUCT field : WORD; END_STRUCT;
        Outer : STRUCT inner : S := (field := 1); END_STRUCT; END_TYPE """
        + function(
            f"F := value.inner.{path};",
            """VAR CONSTANT pos : INT := 0;
          value : Outer := (); END_VAR""",
            result="WORD" if path == "field" else "BOOL",
        )
    )


@pytest.mark.parametrize("value", [True, 1.0, 32768])
def test_caller_constructed_typed_integer_literals_check_declared_storage(value):
    from tc_emulator.syntax import Literal, Location, Program
    from tc_emulator.validation import _Validator

    validator = _Validator(Program(()))
    with pytest.raises(ValidationError):
        validator.constant(Literal(value, Location("bits.st", 1, 1), "INT"))


@pytest.mark.parametrize("kind, value, index", [("INT", -32768, 15), ("DINT", -1, 31)])
def test_signed_integer_constant_bit_reads_use_twos_complement(kind, value, index):
    registry = checked(
        function(
            declarations=f"""VAR CONSTANT word : {kind} := {value};
        top : BOOL := word.{index}; END_VAR"""
        )
    )
    assert registry["F"].variables[1].default is True


@pytest.mark.parametrize("base", ["BYTE", "WORD", "DWORD"])
def test_enum_base_cannot_be_bitstring(base):
    rejected(f"TYPE E : (A, B) {base}; END_TYPE " + function())


def test_struct_field_with_mutable_selector_spelling_keeps_struct_meaning():
    checked(
        "TYPE S : STRUCT pos : BOOL; END_STRUCT; END_TYPE "
        + function("F := s.pos;", "VAR s : S; pos : INT; END_VAR")
    )


def test_local_constant_selector_can_shadow_an_enum_type_name():
    registry = checked(
        "TYPE Pos : (A, B); END_TYPE "
        + function("F := w.Pos;", "VAR CONSTANT Pos : INT := 0; END_VAR VAR w : WORD; END_VAR")
    )
    assert {index for _, index in registry.bit_accesses.values()} == {0}
