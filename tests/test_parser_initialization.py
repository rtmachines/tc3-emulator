"""Declaration initialization metadata stays separate from post-init values."""

import pytest

from tc_emulator.errors import ParseError
from tc_emulator.parser import parse
from tc_emulator.syntax import ArrayInitializer, Location, Reference, StructInitializer
from tc_emulator.types import StringType


def test_call_after_init_marks_only_the_following_fb_or_method_and_keeps_keyword_locations():
    owner = parse(
        """{ATTRIBUTE 'CALL_AFTER_INIT'}
FUNCTION_BLOCK Motor
VAR count : INT; END_VAR
count := 1;
{attribute 'call_after_init'}
METHOD PUBLIC Ready : BOOL
VAR scratch : INT; END_VAR
Ready := TRUE;
END_METHOD
METHOD Plain
END_METHOD
{attribute 'call_after_init'}
METHOD Last
END_METHOD
END_FUNCTION_BLOCK
FUNCTION_BLOCK Plain END_FUNCTION_BLOCK""",
        "hooks.st",
    ).pous
    assert owner[0].call_after_init is True
    assert [method.call_after_init for method in owner[0].methods] == [True, False, True]
    assert owner[1].call_after_init is False
    assert owner[0].loc == Location("hooks.st", 2, 1)
    assert owner[0].methods[0].loc == Location("hooks.st", 6, 1)
    assert owner[0].methods[0].body[0].loc == Location("hooks.st", 8, 1)
    assert len(owner[0].body) == 1


@pytest.mark.parametrize(
    "arguments,names,values",
    [
        ("id := 1, enabled := TRUE", ("ID", "ENABLED"), (1, True)),
        ("1, TRUE", (None, None), (1, True)),
        ("", (), ()),
    ],
)
def test_instance_declaration_records_named_positional_and_empty_argument_lists(
    arguments, names, values
):
    declaration = (
        parse(f"FUNCTION_BLOCK Owner VAR motor : FB_Motor({arguments}); END_VAR END_FUNCTION_BLOCK")
        .pous[0]
        .variables[0]
    )
    assert tuple(argument.name for argument in declaration.init_arguments) == names
    assert tuple(argument.value.value for argument in declaration.init_arguments) == values
    assert tuple(argument.mode for argument in declaration.init_arguments) == tuple(
        ":=" if name else "" for name in names
    )
    assert declaration.element_init_arguments is None
    assert declaration.initial is None


def test_argument_expression_and_declaration_locations_use_original_source_mapping():
    declaration = (
        parse(
            "FUNCTION_BLOCK Owner\nVAR\n  motor : FB_Motor(\n    id := config.axis,\n    enabled := TRUE);\nEND_VAR\nEND_FUNCTION_BLOCK",
            "generated.st",
            locations={3: Location("original.st", 20, 4), 4: Location("original.st", 21, 4)},
        )
        .pous[0]
        .variables[0]
    )
    assert declaration.loc == Location("original.st", 20, 6)
    first, second = declaration.init_arguments
    assert first.loc == Location("original.st", 21, 8)
    assert isinstance(first.value, Reference)
    assert first.value.parts == ("CONFIG", "AXIS")
    assert first.value.loc == Location("original.st", 21, 14)
    assert second.loc == Location("generated.st", 5, 5)


def test_shared_array_arguments_and_post_init_values_are_independent():
    declarations = (
        parse(
            """PROGRAM Main VAR
motors : ARRAY[-1..0, 2..3] OF Motor(id := 5) := [(input := 2), (input := 3)];
first, second : Motor(1) := (input := 4, Speed := 6);
plain : Motor := (input := 8);
END_VAR END_PROGRAM"""
        )
        .pous[0]
        .variables
    )
    motors, first, second, plain = declarations
    assert motors.init_arguments[0].name == "ID"
    assert motors.init_arguments[0].value.value == 5
    assert motors.element_init_arguments is None
    assert isinstance(motors.initial, ArrayInitializer)
    assert [item.value.fields[0][1].value for item in motors.initial.items] == [2, 3]
    for declaration in (first, second):
        assert declaration.init_arguments[0].value.value == 1
        assert isinstance(declaration.initial, StructInitializer)
        assert tuple(name for name, _ in declaration.initial.fields) == ("INPUT", "SPEED")
    assert plain.init_arguments is None
    assert plain.element_init_arguments is None
    assert plain.initial.fields[0][1].value == 8


def test_flat_array_argument_lists_keep_per_element_arguments_order_and_locations():
    declaration = (
        parse(
            """PROGRAM Main VAR
motors : ARRAY[0..1, 1..2] OF Motor[
  (id := 1),
  (2, TRUE),
  (),
  (id := config.axis)] := [(input := 3)];
END_VAR END_PROGRAM""",
            "arrays.st",
        )
        .pous[0]
        .variables[0]
    )
    assert declaration.init_arguments is None
    first, second, third, fourth = declaration.element_init_arguments
    assert first[0].name == "ID" and first[0].value.value == 1
    assert first[0].loc == Location("arrays.st", 3, 4)
    assert tuple(argument.name for argument in second) == (None, None)
    assert tuple(argument.value.value for argument in second) == (2, True)
    assert second[1].loc == Location("arrays.st", 4, 7)
    assert third == ()
    assert fourth[0].value.parts == ("CONFIG", "AXIS")
    assert isinstance(declaration.initial, ArrayInitializer)
    assert declaration.initial.items[0].value.fields[0][1].value == 3


def test_global_and_method_declarations_retain_initialization_arguments():
    program = parse(
        """VAR_GLOBAL shared : Motor(id := 1); END_VAR
FUNCTION_BLOCK Owner
METHOD Run
VAR local : Motor(2); END_VAR
VAR_INST retained : Motor(id := 3); END_VAR
END_METHOD END_FUNCTION_BLOCK"""
    )
    assert program.gvls[0].variables[0].init_arguments[0].value.value == 1
    variables = program.pous[0].methods[0].variables
    assert [declaration.init_arguments[0].value.value for declaration in variables] == [2, 3]


def test_string_capacity_syntax_and_plain_declarations_remain_unchanged():
    variables = (
        parse(
            "PROGRAM Main VAR a : STRING(12); b : STRING[7]; c : ARRAY[1..2] OF STRING(5); plain : INT := 2; END_VAR END_PROGRAM"
        )
        .pous[0]
        .variables
    )
    assert variables[0].type_name == StringType(12)
    assert variables[1].type_name == StringType(7)
    assert variables[2].type_name.element_type == StringType(5)
    assert all(declaration.init_arguments is None for declaration in variables)
    assert all(declaration.element_init_arguments is None for declaration in variables)
    assert variables[3].initial.value == 2


@pytest.mark.parametrize(
    "source",
    [
        "{attribute 'call_after_init'} PROGRAM Main END_PROGRAM",
        "{attribute 'call_after_init'} FUNCTION F : BOOL END_FUNCTION",
        "{attribute 'call_after_init'} TYPE T : INT; END_TYPE",
        "{attribute 'call_after_init'} VAR_GLOBAL x : INT; END_VAR",
        "{attribute 'call_after_init'} INTERFACE I END_INTERFACE",
        "{attribute 'call_after_init'} METHOD Hook END_METHOD",
        "{attribute 'call_after_init'} {attribute 'call_after_init'} FUNCTION_BLOCK F END_FUNCTION_BLOCK",
        "FUNCTION_BLOCK F {attribute 'call_after_init'} END_FUNCTION_BLOCK",
        "FUNCTION_BLOCK F {attribute 'call_after_init'} VAR x : INT; END_VAR END_FUNCTION_BLOCK",
        "FUNCTION_BLOCK F {attribute 'call_after_init'} x := 1; END_FUNCTION_BLOCK",
        "FUNCTION_BLOCK F {attribute 'call_after_init'} PROPERTY P : INT GET END_GET END_PROPERTY END_FUNCTION_BLOCK",
        "FUNCTION_BLOCK F METHOD M {attribute 'call_after_init'} END_METHOD END_FUNCTION_BLOCK",
        "INTERFACE I {attribute 'call_after_init'} METHOD M END_METHOD END_INTERFACE",
        "{attribute 'not_supported'} FUNCTION_BLOCK F END_FUNCTION_BLOCK",
        "{attribute 'call_after_init' := 'true'} FUNCTION_BLOCK F END_FUNCTION_BLOCK",
    ],
)
def test_unsupported_or_misplaced_attributes_are_rejected(source):
    with pytest.raises(ParseError):
        parse(source)


@pytest.mark.parametrize(
    "declaration",
    [
        "motor : Motor(id :=);",
        "motor : Motor(1,);",
        "motor : Motor(id := 1;",
        "motors : ARRAY[1..2] OF Motor[(id := 1),];",
        "motors : ARRAY[1..2] OF Motor[id := 1];",
        "motors : ARRAY[1..2] OF Motor[[(id := 1)]];",
        "motors : ARRAY[1..2] OF Motor[(id := 1) (id := 2)];",
        "motors : ARRAY[1..2] OF Motor(id := 1)[(id := 2)];",
        "motor : Motor[(id := 1)];",
    ],
)
def test_malformed_initialization_argument_syntax_is_rejected(declaration):
    with pytest.raises(ParseError):
        parse(f"PROGRAM Main VAR {declaration} END_VAR END_PROGRAM")
