"""TYPE grammar, declaration aggregates, and mixed field/index paths."""

import pytest

from tc_emulator import syntax
from tc_emulator.errors import ParseError
from tc_emulator.parser import parse, parse_type


def test_types_can_precede_follow_and_share_blocks_with_forward_references():
    program = parse(
        """TYPE
        Config : STRUCT speed, limit : INT := 7; state : State; END_STRUCT;
        Samples : ARRAY[-1..2] OF Config;
        END_TYPE
        FUNCTION F : State F := State.Run; END_FUNCTION
        TYPE State : (Idle, Run := 10, Stop) UINT := Idle; END_TYPE
        TYPE Counter : DINT := -2; END_TYPE""",
        "types.st",
    )
    assert [decl.name for decl in program.types] == ["CONFIG", "SAMPLES", "STATE", "COUNTER"]
    fields = program.types[0].definition.fields
    assert [(field.name, field.section, field.type_name) for field in fields] == [
        ("SPEED", "VAR", "INT"),
        ("LIMIT", "VAR", "INT"),
        ("STATE", "VAR", "STATE"),
    ]
    assert fields[0].initial.value == 7
    assert program.types[1].definition.element_type == "CONFIG"
    enum = program.types[2].definition
    assert enum.base_type == "UINT"
    assert [(member.name, member.value) for member in enum.members] == [
        ("IDLE", None),
        ("RUN", 10),
        ("STOP", None),
    ]
    assert program.types[2].initial.parts == ("IDLE",)
    assert program.types[3].initial.operand.value == 2
    assert program.types[2].loc.source == "types.st"
    assert program.pous[0].return_type == "STATE"


def test_enum_default_base_and_signed_explicit_values():
    decl = parse("TYPE State : (Negative := -2, Zero := +0); END_TYPE").types[0]
    assert decl.definition.base_type == "INT"
    assert [member.value for member in decl.definition.members] == [-2, 0]
    assert decl.initial is None


def test_recursive_structure_and_array_declaration_initializers():
    program = parse("""TYPE Config : STRUCT
      values : ARRAY[1..2] OF INT := [2(7)]; child : Child := (enabled := TRUE);
    END_STRUCT := (values := [1, 2]); END_TYPE
    FUNCTION F : INT VAR
      a : ARRAY[0..2] OF Config := [2((values := [3], child := (enabled := FALSE)))];
      b : Config := (values := [1], child := (enabled := TRUE));
      nested : Matrix := [[1, 2], [3]];
      empty : Config := ();
      grouped : INT := (2 + 3);
    END_VAR END_FUNCTION""")
    assert isinstance(program.types[0].initial, syntax.StructInitializer)
    fields = program.types[0].definition.fields
    assert isinstance(fields[0].initial, syntax.ArrayInitializer)
    assert isinstance(fields[1].initial, syntax.StructInitializer)
    variables = program.pous[0].variables
    repeated = variables[0].initial.items[0]
    assert repeated.count == 2
    assert isinstance(repeated.value, syntax.StructInitializer)
    assert isinstance(repeated.value.fields[0][1], syntax.ArrayInitializer)
    assert isinstance(repeated.value.fields[1][1], syntax.StructInitializer)
    assert isinstance(variables[2].initial.items[0].value, syntax.ArrayInitializer)
    assert variables[3].initial.fields == ()
    assert isinstance(variables[4].initial, syntax.Binary)
    assert all(variable.default is None for variable in variables)


def test_alternating_field_index_paths_keep_old_reference_shape():
    pou = parse("""FUNCTION F : INT
      a.b[0].child.values[1][2].speed := state.config.speed;
      f := a[0].child[2].speed;
      use(input := a[0].child, output => a[1].speed);
      FOR a[0].speed := 1 TO 2 DO RETURN; END_FOR;
    END_FUNCTION""").pous[0]
    path = pou.body[0].target
    assert isinstance(path, syntax.Member) and path.name == "SPEED"
    assert isinstance(path.base, syntax.Index)
    assert isinstance(path.base.base, syntax.Index)
    assert path.base.base.base.name == "VALUES"
    assert path.base.base.base.base.name == "CHILD"
    assert path.base.base.base.base.base.base.parts == ("A", "B")
    assert pou.body[0].value.parts == ("STATE", "CONFIG", "SPEED")
    assert pou.body[2].call.arguments[1].value.name == "SPEED"
    assert pou.body[3].variable.name == "SPEED"


def test_enum_case_labels_do_not_consume_following_member_assignments():
    pou = parse("""FUNCTION F : INT CASE state OF
      State.Idle, State.Stop: config.speed := 1;
        IF flag THEN CASE 1 OF -1, 2: RETURN; END_CASE; END_IF;
      State.Run: a[0].speed := 2;
      ELSE F := 0;
    END_CASE; END_FUNCTION""").pous[0]
    case = pou.body[0]
    assert [label.parts for label in case.arms[0][0]] == [("STATE", "IDLE"), ("STATE", "STOP")]
    assert len(case.arms[0][1]) == 2
    assert case.arms[0][1][1].branches[0][1][0].arms[0][0] == (-1, 2)
    assert case.arms[1][0][0].parts == ("STATE", "RUN")


def test_named_array_elements_and_legacy_ast_constructor_defaults():
    assert parse_type("ARRAY[1..2] OF Config").element_type == "CONFIG"
    location = syntax.Location("old.st", 1, 1)
    assert syntax.Program(()).types == ()
    assert syntax.VarDecl("X", "INT", "VAR", None, location).default is None


@pytest.mark.parametrize("definition", ["STRUCT speed : INT; END_STRUCT", "INT", "(Idle, Run)"])
def test_final_type_declaration_can_omit_semicolon_before_end_type(definition):
    program = parse(f"TYPE Config : {definition} END_TYPE FUNCTION F : INT END_FUNCTION")
    assert [decl.name for decl in program.types] == ["CONFIG"]
    assert program.pous[0].name == "F"


def test_multiple_type_declarations_still_require_separator():
    with pytest.raises(ParseError):
        parse("TYPE Config : STRUCT speed : INT; END_STRUCT Other : INT; END_TYPE")


@pytest.mark.parametrize(
    "source",
    [
        "TYPE END_TYPE",
        "TYPE State : (); END_TYPE",
        "TYPE State : (Idle := 1.5); END_TYPE",
        "TYPE State : (Idle := Other.Member); END_TYPE",
        "TYPE State : (Idle,); END_TYPE",
        "TYPE Config : STRUCT EXTENDS Parent END_STRUCT; END_TYPE",
        "TYPE Config : STRUCT VAR speed : INT; END_VAR END_STRUCT; END_TYPE",
        "TYPE Config : STRUCT speed : INT END_STRUCT; END_TYPE",
        "TYPE Config : UNION speed : INT; END_UNION; END_TYPE",
        "TYPE A : INT; FUNCTION F : INT END_FUNCTION END_TYPE",
        "FUNCTION F : INT F := (speed := 1); END_FUNCTION",
        "FUNCTION F : INT use((speed := 1)); END_FUNCTION",
        "FUNCTION F : INT VAR x : Config := (speed => 1); END_VAR END_FUNCTION",
        "FUNCTION F : INT VAR x : Config := (speed := 1,); END_VAR END_FUNCTION",
        "FUNCTION F : INT a[0].child(,); END_FUNCTION",
        "FUNCTION F : INT CASE state OF Idle.Member.Extra: RETURN; END_CASE; END_FUNCTION",
    ],
)
def test_malformed_and_unsupported_udt_forms_rejected(source):
    with pytest.raises(ParseError):
        parse(source)
